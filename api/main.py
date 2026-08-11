"""FastAPI application entrypoint.

Exposes REST API endpoints for chatbot interaction, document ingestion, and graph verification.
"""
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import json

# Ensure registry components load
import ingestion.parsers
import retrieval.embedder
import retrieval.vector_store

from core.config import DOMAIN
from core.schema import Node, Edge
from ingestion.pipeline import IngestionPipeline
from llm.orchestrator import RAGOrchestrator

app = FastAPI(
    title="Institutional Memory API",
    description="A decoupled, dynamic chatbot backend adaptable to any industry context or data format.",
    version="2.0"
)

# Central pipeline & RAG instances using InMemory stores
pipeline = IngestionPipeline(
    embedder_key="mock",
    vector_store_key="in_memory",
    graph_store_key="in_memory"
)

orchestrator = RAGOrchestrator(
    llm_key="mock",
    embedder_key="mock",
    vector_store_key="in_memory"
)

# Share the vector database reference so queries match uploaded files
orchestrator.vector_store = pipeline.vector_store


class QueryRequest(BaseModel):
    query: str
    limit: Optional[int] = 3
    filters: Optional[Dict[str, Any]] = None


class GraphPayload(BaseModel):
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]


@app.get("/config")
def get_domain_configuration():
    """Retrieve active domain entity types, relation schema, prompt definitions and jargon glossaries."""
    return DOMAIN.model_dump()


@app.post("/query")
def post_query(req: QueryRequest):
    """Answer standard user queries using grounding chunks and prompt context templates.
    
    Dynamically injects active domain prompt guidelines and glossary matching keywords.
    """
    try:
        response = orchestrator.query(req.query, limit=req.limit, filters=req.filters)
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Retrieval orchestrator failure: {str(e)}")


@app.post("/ingest/file")
async def post_ingest_file(
    file: UploadFile = File(...),
    parser_type: str = Form(..., description="Parser key registered in parser_registry (e.g. 'pdf', 'cad', 'email')"),
    metadata: Optional[str] = Form(None, description="Optional JSON-string metadata to attach to the document")
):
    """Ingest, parse, chunk, embed, and store document files.
    
    Compatible with any file type; parses are resolved via plug-in registries.
    """
    meta_dict = {}
    if metadata:
        try:
            meta_dict = json.loads(metadata)
        except Exception:
            raise HTTPException(status_code=400, detail="Metadata argument must be a valid serialized JSON object.")
            
    try:
        content_bytes = await file.read()
        chunks = pipeline.ingest_file(
            filename=file.filename,
            content_bytes=content_bytes,
            parser_type=parser_type,
            metadata=meta_dict
        )
        return {
            "status": "success",
            "filename": file.filename,
            "document_type": parser_type.upper(),
            "chunks_count": len(chunks),
            "chunks": [
                {
                    "index": chunk.metadata.get("index", 0),
                    "content_snippet": chunk.text[:150] + "..." if len(chunk.text) > 150 else chunk.text,
                    "metadata": chunk.metadata
                }
                for chunk in chunks
            ]
        }
    except KeyError as ke:
        raise HTTPException(status_code=400, detail=str(ke))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ingestion processing error: {str(e)}")


@app.post("/ingest/graph")
def post_ingest_graph(payload: GraphPayload):
    """Submit entity nodes and relationships to load into the Knowledge Graph database.
    
    Input elements are dynamically validated against the active domain.yaml types at run-time.
    """
    try:
        pipeline.ingest_graph_elements(payload.nodes, payload.edges)
        return {
            "status": "success",
            "message": f"Successfully verified and ingested {len(payload.nodes)} Nodes and {len(payload.edges)} Edges."
        }
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=f"Ontology Validation Violation: {str(ve)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Graph database load error: {str(e)}")
