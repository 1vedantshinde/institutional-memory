"""FastAPI application entrypoint.

Exposes REST API endpoints for chatbot interaction, document ingestion, and dynamic domain configuration hot-reloading.
"""
from dotenv import load_dotenv
load_dotenv()  # Load .env before any other imports that read env vars

import os
import json
import shutil
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends, Header
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

# CORS — tighten allow_origins once you have a fixed frontend URL
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
    embedder_key="mock",
    vector_store_key="in_memory"
)
orchestrator.vector_store = pipeline.vector_store

# Local directory to store uploads
UPLOADS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)

# --- API Key Authentication (C4) ---

_API_KEY = os.getenv("API_KEY")  # empty string → auth disabled


def verify_api_key(x_api_key: Optional[str] = Header(None)):
    """Enforces X-API-Key header on protected endpoints when API_KEY env var is set."""
    if _API_KEY and x_api_key != _API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key. Set X-API-Key header.")


# --- Helpers ---

def save_upload(upload_file: UploadFile) -> str:
    """Saves raw FastAPI upload files locally to the uploads folder."""
    file_path = os.path.join(UPLOADS_DIR, upload_file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(upload_file.file, buffer)
    return file_path


def ingest_file(file_path: str) -> Dict[str, Any]:
    """Ingests local file into the active similarity index and database.

    Returns a structured result dict with status, filename, chunk count, and
    stage info on failure — never raises, so batch ingest can continue past errors.
    """
    basename = os.path.basename(file_path)
    try:
        with open(file_path, "rb") as f:
            content_bytes = f.read()
    except Exception as e:
        return {"status": "failed", "filename": basename, "stage": "file_read", "error": str(e)}

    try:
        chunks = pipeline.ingest_file(filename=basename, content_bytes=content_bytes)
        return {
            "status": "success",
            "filename": basename,
            "chunks_count": len(chunks)
        }
    except Exception as e:
        return {"status": "failed", "filename": basename, "stage": "ingest_pipeline", "error": str(e)}


def ingest_folder(folder_path: str) -> Dict[str, Any]:
    """Locates and processes all supported documents in a system folder recursively."""
    if not os.path.isdir(folder_path):
        raise HTTPException(status_code=400, detail=f"Provided directory root '{folder_path}' is not valid.")

    ingested_files = []
    failed_files = []
    total_chunks = 0

    from core.registry import PARSER_REGISTRY

    for root, _, files in os.walk(folder_path):
        for file in files:
            ext = file.split(".")[-1].lower() if "." in file else ""
            if ext in PARSER_REGISTRY:
                full_path = os.path.join(root, file)
                res = ingest_file(full_path)
                if res["status"] == "success":
                    ingested_files.append(file)
                    total_chunks += res["chunks_count"]
                else:
                    failed_files.append({"file": file, "stage": res.get("stage"), "error": res.get("error")})

    return {
        "status": "success",
        "folder_path": folder_path,
        "files_ingested": ingested_files,
        "total_chunks_ingested": total_chunks,
        "failed_files": failed_files,
    }


# --- Request/Response Models ---

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


# --- Endpoints ---

@app.post("/ingest", dependencies=[Depends(verify_api_key)])
def ingest(file: UploadFile = File(...)):
    """Uploads and ingests a single document of any registered format."""
    try:
        save_path = save_upload(file)
        result = ingest_file(save_path)
        if result["status"] == "failed":
            raise HTTPException(status_code=500, detail=result.get("error", "Ingestion failed"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/ingest-folder", dependencies=[Depends(verify_api_key)])
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


@app.put("/config", dependencies=[Depends(verify_api_key)])
def update_config(new_config: dict):
    """Updates and reloads domain configuration layout during runtime without restart."""
    try:
        core.config.save_domain_config(new_config)
        core.config.reload_domain_config()
        return {"status": "updated"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Config reload failed: {str(e)}")


# Legacy compatibility endpoints
@app.post("/ingest/file", dependencies=[Depends(verify_api_key)])
async def post_ingest_file(
    file: UploadFile = File(...),
    parser_type: str = Form(..., description="Parser key"),
    metadata: Optional[str] = Form(None, description="Optional metadata JSON")
):
    try:
        save_path = save_upload(file)
        result = ingest_file(save_path)
        if result["status"] == "failed":
            raise HTTPException(status_code=500, detail=result.get("error", "Ingestion failed"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/ingest/graph", dependencies=[Depends(verify_api_key)])
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
