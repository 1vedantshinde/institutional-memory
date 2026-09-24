"""FastAPI application entrypoint.

Exposes REST API endpoints for chatbot interaction, document ingestion, and dynamic domain configuration hot-reloading.
"""
import os
import json
import shutil
import threading
import hashlib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Ensure registry components load
import ingestion.parsers
import retrieval.embedder
import retrieval.vector_store

import core.config
from core.schema import Condition, Finding, Node, Edge, Recording, SignalWindow
from core.registry import LLMProviderUnavailableError
from ingestion.manifest import discover_manifest
from ingestion.pipeline import IngestionPipeline, ingest_daq_dataset
from ingestion.parsers.csv_daq_parser import load_full_numeric_array
from llm.orchestrator import DAQExplanationOrchestrator, RAGOrchestrator, answer, llm
from analytics.anomaly import MODEL_VERSION, detect_anomalies
from analytics.baselines import (
    BaselineCollection,
    ConditionChannelBaseline,
    build_per_condition_baselines,
)
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
    baselines: BaselineCollection | None = None
    dataset_fingerprint: str | None = None
    ingest_status: str = "idle"
    ingest_error: str | None = None
    analysis_status: str = "idle"
    analysis_error: str | None = None
    analysis_result: dict[str, Any] | None = None


daq_state = DAQServiceState()
daq_state_lock = threading.Lock()

# Local directory to store uploads
UPLOADS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DAQ_CACHE_DIR = PROJECT_ROOT / "runtime" / "daq_cache"


def _write_cache(path: Path, payload: dict[str, Any]) -> None:
    """Atomically persist local, derived DAQ state for later API runs."""
    DAQ_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    temporary.replace(path)


def _read_cache(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _manifest_fingerprint(manifest: list[dict[str, Any]], config_path: Path) -> str:
    """Fingerprint metadata, not signal contents, to detect changed inputs cheaply.

    A full SHA-256 of 41 GB would defeat the cache. File path, byte size and
    modification time provide a cheap invalidation check; ``force`` is exposed
    for a deliberate re-run when source contents change without metadata.
    """
    inputs = []
    for entry in manifest:
        stat = Path(entry["source_path"]).stat()
        inputs.append({
            "path": str(Path(entry["source_path"]).resolve()),
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        })
    config_hash = hashlib.sha256(config_path.read_bytes()).hexdigest()
    encoded = json.dumps({"config": config_hash, "inputs": inputs}, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _ingest_cache_path(fingerprint: str) -> Path:
    return DAQ_CACHE_DIR / f"ingest-{fingerprint}.json"


def _analysis_cache_path(cache_key: str) -> Path:
    return DAQ_CACHE_DIR / f"analysis-{cache_key}.json"


def _analysis_cache_key(fingerprint: str, request: "AnalyseRequest") -> str:
    settings = {
        "dataset_fingerprint": fingerprint,
        "condition_id": request.condition_id,
        "recording_id": request.recording_id,
        "window_size_samples": request.window_size_samples,
        "overlap": request.overlap,
        "anomaly_threshold": request.anomaly_threshold,
        "channels": sorted(request.channels) if request.channels else None,
        "model_version": MODEL_VERSION,
    }
    return hashlib.sha256(json.dumps(settings, sort_keys=True).encode("utf-8")).hexdigest()


def resolve_daq_dataset_root(folder_path: str) -> Path:
    """Resolve an explicit DAQ root, including the project-local dataset mount.

    ``Readngs_DAQ_Data`` is accepted as a convenient project-relative alias for
    ``dataset/Readngs_DAQ_Data``. No directory is guessed beyond those explicit
    locations, and an invalid request produces a 400 rather than a 500.
    """
    requested = Path(folder_path).expanduser()
    candidates = [requested]
    if not requested.is_absolute():
        candidates.extend([PROJECT_ROOT / requested, PROJECT_ROOT / "dataset" / requested.name])
    for candidate in candidates:
        if candidate.is_dir():
            return candidate.resolve()
    raise HTTPException(
        status_code=400,
        detail=(
            f"DAQ dataset directory does not exist: {folder_path}. "
            f"Use an absolute path or {PROJECT_ROOT / 'dataset' / 'Readngs_DAQ_Data'}."
        ),
    )


def resolve_project_path(path: str) -> Path:
    """Resolve a config path relative to the project root when necessary."""
    requested = Path(path).expanduser()
    if requested.is_file():
        return requested.resolve()
    project_relative = PROJECT_ROOT / requested
    if project_relative.is_file():
        return project_relative.resolve()
    raise HTTPException(status_code=400, detail=f"Configuration file does not exist: {path}")


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
    top_k: Optional[int] = None


class FolderIngestRequest(BaseModel):
    folder_path: str


class DAQIngestRequest(BaseModel):
    folder_path: str
    config_path: str = "config/domain.yaml"
    wait: bool = False
    force: bool = False


class AnalyseRequest(BaseModel):
    condition_id: Optional[str] = None
    recording_id: Optional[str] = None
    window_size_samples: int = 2048
    overlap: float = 0.5
    anomaly_threshold: float = 3.0
    channels: Optional[List[str]] = None
    wait: bool = False
    force: bool = False


class DAQQueryRequest(BaseModel):
    question: str
    filters: Dict[str, Any] = Field(default_factory=dict)
    feature_vector: Optional[List[float]] = None
    top_k: int = 5


class GraphPayload(BaseModel):
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]


def _restore_ingest_cache(cached: dict[str, Any], dataset_root: Path, fingerprint: str) -> None:
    """Hydrate profile metadata without re-reading every raw CSV."""
    with daq_state_lock:
        daq_state.dataset_root = str(dataset_root)
        daq_state.dataset_fingerprint = fingerprint
        daq_state.summary = cached["summary"]
        daq_state.conditions = {
            item["condition_id"]: Condition.model_validate(item)
            for item in cached["conditions"]
        }
        daq_state.recordings = [Recording.model_validate(item) for item in cached["recordings"]]
        daq_state.windows = []
        daq_state.findings = []
        daq_state.baselines = None
        daq_state.graph_driver = Neo4jSimulationDriver()
        daq_state.feature_store = None
        daq_state.metadata_index = None
        daq_state.ingest_status = "complete"
        daq_state.ingest_error = None


def _run_daq_ingest(dataset_root: Path, config_path: Path, force: bool = False) -> None:
    """Profile the corpus in a worker so the API remains responsive."""
    try:
        manifest = discover_manifest(str(dataset_root), config_path=str(config_path))
        fingerprint = _manifest_fingerprint(manifest, config_path)
        cached = None if force else _read_cache(_ingest_cache_path(fingerprint))
        if cached is not None:
            _restore_ingest_cache(cached, dataset_root, fingerprint)
            return
        # A 41 GB corpus is profiled once here. Full numeric reads happen only
        # for the condition/recording selected by POST /analyse.
        run = ingest_daq_dataset(
            str(dataset_root), config_path=str(config_path), validate_full_numeric=False, manifest=manifest
        )
        conditions = {
            entry["condition_id"]: Condition(
                condition_id=entry["condition_id"], S=entry["S"], F=entry["F"], D=entry["D"],
                source_folder=Path(entry["source_path"]).parent.name,
            )
            for entry in manifest
        }
        _write_cache(_ingest_cache_path(fingerprint), {
            "summary": run.summary.as_dict(),
            "conditions": [condition.model_dump(mode="json") for condition in conditions.values()],
            "recordings": [recording.model_dump(mode="json") for recording in run.recordings],
        })
        with daq_state_lock:
            daq_state.dataset_root = str(dataset_root)
            daq_state.dataset_fingerprint = fingerprint
            daq_state.summary = run.summary.as_dict()
            daq_state.conditions = conditions
            daq_state.recordings = run.recordings
            daq_state.windows = []
            daq_state.findings = []
            daq_state.graph_driver = Neo4jSimulationDriver()
            daq_state.feature_store = None
            daq_state.metadata_index = None
            daq_state.baselines = None
            daq_state.ingest_status = "complete"
            daq_state.ingest_error = None
    except Exception as exc:
        with daq_state_lock:
            daq_state.ingest_status = "failed"
            daq_state.ingest_error = str(exc)


@app.post("/ingest")
async def ingest(request: Request, response: Response):
    """Run DAQ manifest/quality ingestion for JSON, retaining legacy uploads."""
    try:
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            payload = DAQIngestRequest(**(await request.json()))
            dataset_root = resolve_daq_dataset_root(payload.folder_path)
            config_path = resolve_project_path(payload.config_path)
            with daq_state_lock:
                if daq_state.ingest_status == "running":
                    raise HTTPException(status_code=409, detail="DAQ ingest is already running.")
                daq_state.ingest_status = "running"
                daq_state.ingest_error = None
                daq_state.summary = None
            if payload.wait:
                _run_daq_ingest(dataset_root, config_path, payload.force)
                if daq_state.ingest_status == "failed":
                    raise HTTPException(status_code=500, detail=daq_state.ingest_error)
                return {"status": "complete", "summary": daq_state.summary}
            threading.Thread(
                target=_run_daq_ingest, args=(dataset_root, config_path, payload.force), daemon=True
            ).start()
            response.status_code = 202
            return {"status": "running", "profile_url": "/profile"}
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
    if daq_state.ingest_status == "running":
        return {"status": "running", "message": "DAQ profiling is still running."}
    if daq_state.ingest_status == "failed":
        raise HTTPException(status_code=500, detail=daq_state.ingest_error)
    if daq_state.summary is None:
        raise HTTPException(status_code=404, detail="No DAQ ingest run is available.")
    return {"status": "complete", **daq_state.summary}


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


def _run_analysis(request: AnalyseRequest) -> dict[str, Any]:
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
            recording, numeric_array, window_size_samples=request.window_size_samples,
            overlap=request.overlap, channels=request.channels,
        )
        channel_index = {name: index for index, name in enumerate(recording.channel_names)}
        prepared_channels = {
            channel: preprocess_channel([row[index] for row in numeric_array]).values
            for channel, index in channel_index.items()
            if channel != "Time" and (request.channels is None or channel in request.channels)
        }
        for window in recording_windows:
            values = prepared_channels[window.channel][window.sample_start:window.sample_end]
            extraction = extract_window_features(window, values, fs=fs)
            if feature_names is None:
                feature_names = extraction.feature_names
            elif extraction.feature_names != feature_names:
                raise HTTPException(status_code=409, detail="Feature layouts differ across analysis scope.")
        windows.extend(recording_windows)
    assert feature_names is not None
    baselines = build_per_condition_baselines(windows, selected, feature_names)
    recording_map = {recording.recording_id: recording for recording in selected}
    findings = detect_anomalies(windows, recording_map, baselines, threshold=request.anomaly_threshold)
    _hydrate_analysis_state(windows, findings, baselines)
    return {"recordings_analysed": len(selected), "windows": len(windows), "findings": len(findings)}


def _hydrate_analysis_state(
    windows: list[SignalWindow], findings: list[Finding], baselines: BaselineCollection
) -> None:
    """Recreate in-memory retrieval indexes and graph from persisted facts."""
    feature_store = FeatureStore()
    feature_store.insert(windows)
    metadata_index = MetadataIndex(daq_state.conditions.values(), daq_state.recordings, windows)
    graph_driver = Neo4jSimulationDriver()
    populate_provenance_graph(
        graph_driver, daq_state.conditions.values(), daq_state.recordings, windows, findings
    )
    with daq_state_lock:
        daq_state.windows = windows
        daq_state.findings = findings
        daq_state.baselines = baselines
        daq_state.feature_store = feature_store
        daq_state.metadata_index = metadata_index
        daq_state.graph_driver = graph_driver


def _save_analysis_cache(cache_key: str, result: dict[str, Any]) -> None:
    assert daq_state.baselines is not None
    _write_cache(_analysis_cache_path(cache_key), {
        "result": result,
        "windows": [window.model_dump(mode="json") for window in daq_state.windows],
        "findings": [finding.model_dump(mode="json") for finding in daq_state.findings],
        "baselines": [asdict(profile) for profile in daq_state.baselines.profiles.values()],
    })


def _restore_analysis_cache(cached: dict[str, Any]) -> dict[str, Any]:
    windows = [SignalWindow.model_validate(item) for item in cached["windows"]]
    findings = [Finding.model_validate(item) for item in cached["findings"]]
    profiles = {
        (item["condition_id"], item["channel"]): ConditionChannelBaseline(**item)
        for item in cached["baselines"]
    }
    _hydrate_analysis_state(windows, findings, BaselineCollection(profiles=profiles))
    return dict(cached["result"])


def _background_analysis(request: AnalyseRequest) -> None:
    """Run computational signal analysis away from the API request worker."""
    try:
        if daq_state.dataset_fingerprint is None:
            raise RuntimeError("analysis_requires_a_completed_daq_ingest")
        cache_key = _analysis_cache_key(daq_state.dataset_fingerprint, request)
        cached = None if request.force else _read_cache(_analysis_cache_path(cache_key))
        result = _restore_analysis_cache(cached) if cached is not None else _run_analysis(request)
        if cached is None:
            _save_analysis_cache(cache_key, result)
        with daq_state_lock:
            daq_state.analysis_result = result
            daq_state.analysis_status = "complete"
            daq_state.analysis_error = None
    except Exception as exc:
        with daq_state_lock:
            daq_state.analysis_status = "failed"
            daq_state.analysis_error = str(exc)


@app.post("/analyse")
def analyse(request: AnalyseRequest, response: Response) -> Dict[str, Any]:
    """Start condition/recording analysis without blocking the API worker."""
    _selected_recordings(request)  # validate scope before acknowledging the job
    with daq_state_lock:
        if daq_state.analysis_status == "running":
            raise HTTPException(status_code=409, detail="DAQ analysis is already running.")
        daq_state.analysis_status = "running"
        daq_state.analysis_error = None
        daq_state.analysis_result = None
    if request.wait:
        _background_analysis(request)
        if daq_state.analysis_status == "failed":
            raise HTTPException(status_code=500, detail=daq_state.analysis_error)
        return {"status": "complete", **(daq_state.analysis_result or {})}
    threading.Thread(target=_background_analysis, args=(request,), daemon=True).start()
    response.status_code = 202
    return {"status": "running", "analysis_status_url": "/analyse/status"}


@app.get("/analyse/status")
def analyse_status() -> Dict[str, Any]:
    """Report analysis job progress state without blocking on signal processing."""
    with daq_state_lock:
        if daq_state.analysis_status == "failed":
            raise HTTPException(status_code=500, detail=daq_state.analysis_error)
        if daq_state.analysis_status == "complete":
            return {"status": "complete", **(daq_state.analysis_result or {})}
        return {"status": daq_state.analysis_status}


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
    except LLMProviderUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/query")
def query_endpoint(q: Optional[str] = None, req: Optional[QueryRequest] = None):
    """Explain retrieved DAQ findings, or retain legacy document-RAG querying."""
    query_text = q or (req.question if req else None) or (req.query if req else None) or (req.q if req else None)
    if not query_text:
        raise HTTPException(status_code=400, detail="Query parameter 'q' or body 'query' is required.")
    limit = (req.top_k if req and req.question and req.top_k is not None else (req.limit if req and req.limit else 8))
    filters = req.filters if req else None
    try:
        if req and req.question is not None:
            if not daq_state.windows:
                raise HTTPException(status_code=409, detail="Run POST /analyse before DAQ querying.")
            if llm.__class__.__name__ == "MockLLM":
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "A real LLM is not configured. Set LLM_PROVIDER=openai and "
                        "OPENAI_API_KEY, then restart the API server."
                    ),
                )
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
    except LLMProviderUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
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
