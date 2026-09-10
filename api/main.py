"""FastAPI application entrypoint.

Exposes REST API endpoints for chatbot interaction, document ingestion, and dynamic domain configuration hot-reloading.
"""
import os
import json
import shutil
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Ensure registry components load
import ingestion.parsers
import retrieval.embedder
import retrieval.vector_store

import core.config
from core.schema import Node, Edge
from ingestion.pipeline import IngestionPipeline
from llm.orchestrator import RAGOrchestrator, answer

app = FastAPI(
    title="Institutional Memory API",
    description="A decoupled, format-agnostic knowledge intelligence API backend.",
    version="2.0"
)

# Connect to frontend via CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Central pipeline & RAG instances using InMemory stores
pipeline = IngestionPipeline(
    embedder_key="mock",
    vector_store_key="in_memory",
    graph_store_key="in_memory"
)

# Shared reference updates
orchestrator = RAGOrchestrator(
    llm_key="mock",
    embedder_key="mock",
    vector_store_key="in_memory"
)
orchestrator.vector_store = pipeline.vector_store

# Local directory to store uploads
UPLOADS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)


def save_upload(upload_file: UploadFile) -> str:
    """Saves raw FastAPI upload files locally to the uploads folder."""
    file_path = os.path.join(UPLOADS_DIR, upload_file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(upload_file.file, buffer)
    return file_path


def ingest_file(file_path: str) -> Dict[str, Any]:
    """Ingests local file into the active similarity index and database."""
    basename = os.path.basename(file_path)
    with open(file_path, "rb") as f:
        content_bytes = f.read()
    chunks = pipeline.ingest_file(filename=basename, content_bytes=content_bytes)
    return {
        "status": "success",
        "filename": basename,
        "chunks_count": len(chunks)
    }


def ingest_folder(folder_path: str) -> Dict[str, Any]:
    """Locates and processes all supported documents in a system folder recursively."""
    if not os.path.isdir(folder_path):
        raise HTTPException(status_code=400, detail=f"Provided directory root '{folder_path}' is not valid.")
        
    ingested_files = []
    total_chunks = 0
    errors = {}
    
    from core.registry import PARSER_REGISTRY
    
    for root, _, files in os.walk(folder_path):
        for file in files:
            ext = file.split(".")[-1].lower() if "." in file else ""
            if ext in PARSER_REGISTRY:
                full_path = os.path.join(root, file)
                try:
                    res = ingest_file(full_path)
                    ingested_files.append(file)
                    total_chunks += res["chunks_count"]
                except Exception as e:
                    errors[file] = str(e)
                    
    return {
        "status": "success",
        "folder_path": folder_path,
        "files_ingested": ingested_files,
        "total_chunks_ingested": total_chunks,
        "errors": errors
    }


class QueryRequest(BaseModel):
    q: Optional[str] = None
    query: Optional[str] = None
    limit: Optional[int] = 8
    filters: Optional[Dict[str, Any]] = None


class FolderIngestRequest(BaseModel):
    folder_path: str


class GraphPayload(BaseModel):
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]


@app.post("/ingest")
def ingest(file: UploadFile = File(...)):
    """Uploads and ingests a single document of any registered format."""
    try:
        save_path = save_upload(file)
        result = ingest_file(save_path)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/ingest-folder")
def ingest_folder_endpoint(folder_path: Optional[str] = None, req: Optional[FolderIngestRequest] = None):
    """Processes all compatible document formats inside a directory recursively."""
    target_path = folder_path or (req.folder_path if req else None)
    if not target_path:
        raise HTTPException(status_code=400, detail="Parameter 'folder_path' is required.")
    try:
        return ingest_folder(target_path)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/query")
def query_endpoint(q: Optional[str] = None, req: Optional[QueryRequest] = None):
    """Executes hybrid vector/graph queries and maps grounded answer responses."""
    query_text = q or (req.query if req else None) or (req.q if req else None)
    if not query_text:
        raise HTTPException(status_code=400, detail="Query parameter 'q' or body 'query' is required.")
    limit = req.limit if (req and req.limit) else 8
    filters = req.filters if req else None
    try:
        return orchestrator.query(query_text, limit=limit, filters=filters)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")


@app.get("/config")
def get_config():
    """Fetches the active domain structure configuration."""
    return core.config.DOMAIN


@app.put("/config")
def update_config(new_config: dict):
    """Updates and reloads domain configuration layout during runtime without restart."""
    try:
        core.config.save_domain_config(new_config)
        core.config.reload_domain_config()
        return {"status": "updated"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Config reload failed: {str(e)}")


# Legacy compatibility endpoints
@app.post("/ingest/file")
async def post_ingest_file(
    file: UploadFile = File(...),
    parser_type: str = Form(..., description="Parser key"),
    metadata: Optional[str] = Form(None, description="Optional metadata JSON")
):
    try:
        save_path = save_upload(file)
        return ingest_file(save_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/ingest/graph")
def post_ingest_graph(payload: GraphPayload):
    try:
        pipeline.ingest_graph_elements(payload.nodes, payload.edges)
        return {
            "status": "success",
            "message": f"Successfully ingested {len(payload.nodes)} Nodes and {len(payload.edges)} Edges."
        }
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
