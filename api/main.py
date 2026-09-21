"""FastAPI application entrypoint.

Exposes REST API endpoints for chatbot interaction, document ingestion, and dynamic domain configuration hot-reloading.
"""
import os
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Ensure registry components load
import ingestion.parsers
import retrieval.embedder
import retrieval.vector_store

import core.config
from core.schema import Condition, Finding, Node, Edge, Recording, SignalWindow
from ingestion.manifest import discover_manifest
from ingestion.pipeline import IngestionPipeline, ingest_daq_dataset
from ingestion.parsers.csv_daq_parser import load_full_numeric_array
from llm.orchestrator import DAQExplanationOrchestrator, RAGOrchestrator, answer, llm
from analytics.anomaly import detect_anomalies
from analytics.baselines import build_per_condition_baselines
from knowledge.graph_store import Neo4jSimulationDriver
from knowledge.ontology import populate_provenance_graph
from retrieval.feature_store import FeatureStore
from retrieval.metadata_index import MetadataIndex
from retrieval.retriever import DAQRetriever
from signal.features import extract_window_features
from signal.preprocessing import SamplingRateError, compute_sampling_rate, preprocess_channel
from signal.windowing import window_recording

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


@dataclass
class DAQServiceState:
    """In-process state produced by DAQ ingest and consumed by later endpoints."""

    dataset_root: str | None = None
    summary: dict[str, Any] | None = None
    conditions: dict[str, Condition] = field(default_factory=dict)
    recordings: list[Recording] = field(default_factory=list)
    windows: list[SignalWindow] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    graph_driver: Neo4jSimulationDriver = field(default_factory=Neo4jSimulationDriver)
    feature_store: FeatureStore | None = None
    metadata_index: MetadataIndex | None = None


daq_state = DAQServiceState()

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
    question: Optional[str] = None
    limit: Optional[int] = 8
    filters: Optional[Dict[str, Any]] = None
    feature_vector: Optional[List[float]] = None


class FolderIngestRequest(BaseModel):
    folder_path: str


class DAQIngestRequest(BaseModel):
    folder_path: str
    config_path: str = "config/domain.yaml"


class AnalyseRequest(BaseModel):
    condition_id: Optional[str] = None
    recording_id: Optional[str] = None
    window_size_samples: int = 2048
    overlap: float = 0.5
    anomaly_threshold: float = 3.0


class DAQQueryRequest(BaseModel):
    question: str
    filters: Dict[str, Any] = Field(default_factory=dict)
    feature_vector: Optional[List[float]] = None
    top_k: int = 5


class GraphPayload(BaseModel):
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]


@app.post("/ingest")
async def ingest(request: Request):
    """Run DAQ manifest/quality ingestion for JSON, retaining legacy uploads."""
    try:
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            payload = DAQIngestRequest(**(await request.json()))
            run = ingest_daq_dataset(payload.folder_path, config_path=payload.config_path)
            manifest = discover_manifest(payload.folder_path, config_path=payload.config_path)
            conditions = {
                entry["condition_id"]: Condition(
                    condition_id=entry["condition_id"], S=entry["S"], F=entry["F"], D=entry["D"],
                    source_folder=Path(entry["source_path"]).parent.name,
                )
                for entry in manifest
            }
            daq_state.dataset_root = payload.folder_path
            daq_state.summary = run.summary.as_dict()
            daq_state.conditions = conditions
            daq_state.recordings = run.recordings
            daq_state.windows = []
            daq_state.findings = []
            daq_state.graph_driver = Neo4jSimulationDriver()
            daq_state.feature_store = None
            daq_state.metadata_index = None
            return {"status": "success", "summary": daq_state.summary}
        form = await request.form()
        upload = form.get("file")
        if upload is None or not hasattr(upload, "filename") or not hasattr(upload, "file"):
            raise HTTPException(status_code=400, detail="JSON folder_path or multipart file is required.")
        return ingest_file(save_upload(upload))
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/profile")
def profile() -> Dict[str, Any]:
    """Return the latest DAQ run's evidence-grade discovery/quality summary."""
    if daq_state.summary is None:
        raise HTTPException(status_code=404, detail="No DAQ ingest run is available.")
    return daq_state.summary


def _selected_recordings(request: AnalyseRequest) -> list[Recording]:
    if not daq_state.recordings:
        raise HTTPException(status_code=409, detail="Run POST /ingest on a DAQ folder first.")
    if request.condition_id and request.recording_id:
        raise HTTPException(status_code=400, detail="Specify condition_id or recording_id, not both.")
    selected = [recording for recording in daq_state.recordings if recording.schema_status == "canonical"]
    if request.condition_id:
        selected = [recording for recording in selected if recording.condition_id == request.condition_id]
    if request.recording_id:
        selected = [recording for recording in selected if recording.recording_id == request.recording_id]
    if not selected:
        raise HTTPException(status_code=404, detail="No canonical recordings match the requested scope.")
    return selected


@app.post("/analyse")
def analyse(request: AnalyseRequest) -> Dict[str, Any]:
    """Compute windows/features/baselines/unsupervised findings for DAQ scope."""
    selected = _selected_recordings(request)
    windows: list[SignalWindow] = []
    feature_names: list[str] | None = None
    for recording in selected:
        numeric_array = load_full_numeric_array(recording)
        time_values = [row[0] for row in numeric_array]
        try:
            fs: float | None = compute_sampling_rate(time_values)
        except SamplingRateError:
            fs = None
        recording_windows = window_recording(
            recording, numeric_array, window_size_samples=request.window_size_samples, overlap=request.overlap
        )
        channel_index = {name: index for index, name in enumerate(recording.channel_names)}
        for window in recording_windows:
            values = [row[channel_index[window.channel]] for row in numeric_array[window.sample_start:window.sample_end]]
            prepared = preprocess_channel(values).values
            extraction = extract_window_features(window, prepared, fs=fs)
            if feature_names is None:
                feature_names = extraction.feature_names
            elif extraction.feature_names != feature_names:
                raise HTTPException(status_code=409, detail="Feature layouts differ across analysis scope.")
        windows.extend(recording_windows)
    assert feature_names is not None
    baselines = build_per_condition_baselines(windows, selected, feature_names)
    recording_map = {recording.recording_id: recording for recording in selected}
    findings = detect_anomalies(windows, recording_map, baselines, threshold=request.anomaly_threshold)
    daq_state.windows = windows
    daq_state.findings = findings
    daq_state.feature_store = FeatureStore()
    daq_state.feature_store.insert(windows)
    daq_state.metadata_index = MetadataIndex(daq_state.conditions.values(), daq_state.recordings, windows)
    daq_state.graph_driver = Neo4jSimulationDriver()
    populate_provenance_graph(daq_state.graph_driver, daq_state.conditions.values(), daq_state.recordings, windows, findings)
    return {"recordings_analysed": len(selected), "windows": len(windows), "findings": len(findings)}


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
    """Explain retrieved DAQ findings, or retain legacy document-RAG querying."""
    query_text = q or (req.question if req else None) or (req.query if req else None) or (req.q if req else None)
    if not query_text:
        raise HTTPException(status_code=400, detail="Query parameter 'q' or body 'query' is required.")
    limit = req.limit if (req and req.limit) else 8
    filters = req.filters if req else None
    try:
        if req and req.question is not None:
            if not daq_state.windows:
                raise HTTPException(status_code=409, detail="Run POST /analyse before DAQ querying.")
            if req.feature_vector is not None:
                assert daq_state.metadata_index is not None and daq_state.feature_store is not None
                matches = DAQRetriever(
                    daq_state.metadata_index, daq_state.feature_store, daq_state.graph_driver
                ).query(req.feature_vector, filters=filters, top_k=limit)
                matched_window_ids = {match.window.window.window_id for match in matches}
            else:
                matched_window_ids = {
                    indexed.window.window_id
                    for indexed in daq_state.metadata_index.filter(**(filters or {}))
                }
            findings = [finding for finding in daq_state.findings if finding.window_id in matched_window_ids]
            if not findings:
                raise HTTPException(status_code=404, detail="No computed findings match the DAQ query scope.")
            return DAQExplanationOrchestrator(llm, daq_state.graph_driver).explain(
                query_text, findings[:limit], daq_state.conditions
            )
        return orchestrator.query(query_text, limit=limit, filters=filters)
    except HTTPException:
        raise
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
