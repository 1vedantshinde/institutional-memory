"""Frontend-facing conversational server for DAQ Institutional Memory.

Run with ``python3 -m uvicorn server:app --reload``.  The `/chat` route turns
a question such as "Why is spindle vibration high for condition 4?" into a
condition/channel-scoped analytics request before asking the LLM to explain
the resulting findings. The LLM never selects data or performs signal math.
"""

from __future__ import annotations

import os
import re
import threading
from pathlib import Path
from typing import Any
from dotenv import load_dotenv

# Ensure environment variables (.env) are loaded
load_dotenv(Path(__file__).resolve().parent / ".env")

from fastapi import HTTPException, Response
from pydantic import BaseModel, Field

import api.main as daq_api
from core.registry import LLMProviderUnavailableError
from ingestion import knowledge_docs


app = daq_api.app



CHANNEL_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Vib_Spindle", ("spindle", "spindle vibration")),
    ("Vib_Table", ("table", "table vibration")),
    ("X_Load_Cell", ("x load", "x-axis load", "x axis load", "x_load")),
    ("Y_Load_Cell", ("y load", "y-axis load", "y axis load", "y_load")),
    ("Z_Load_Cell", ("z load", "z-axis load", "z axis load", "z_load")),
    ("Current", ("current", "motor current", "spindle current")),
)


class ChatRequest(BaseModel):
    """A frontend question with optional explicit scope overrides."""

    question: str = Field(min_length=3)
    condition_id: str | None = None
    channel: str | None = None
    top_k: int = Field(default=3, ge=1, le=10)


def infer_condition_id(question: str) -> str | None:
    """Extract only explicit condition identifiers; never guess process settings."""
    match = re.search(r"\bcondition(?:\s+id)?\s*[:#-]?\s*(\d+)\b", question, re.I)
    return match.group(1) if match else None


def infer_channel(question: str) -> str | None:
    """Map clear DAQ channel language to the canonical channel names."""
    normalized = question.lower().replace("_", " ")
    matches = [
        channel
        for channel, phrases in CHANNEL_PATTERNS
        if any(re.search(rf"\b{re.escape(phrase)}\b", normalized) for phrase in phrases)
    ]
    return matches[0] if len(matches) == 1 else None


def _scope_is_ready(condition_id: str, channel: str) -> bool:
    """Whether the active in-memory analysis contains the requested scope."""
    index = daq_api.daq_state.metadata_index
    return bool(index and index.filter(condition_id=condition_id, channel=channel))


def _start_automatic_ingest() -> None:
    try:
        raw_root = os.environ.get("DAQ_DATASET_ROOT", "dataset/Readngs_DAQ_Data")
        dataset_root = daq_api.resolve_daq_dataset_root(raw_root)
        config_path = daq_api.resolve_project_path(
            os.environ.get("DAQ_CONFIG_PATH", "config/domain.yaml")
        )
    except Exception as e:
        print(f"[AutoIngest] DAQ CSV dataset not available ({e}). Skipping DAQ CSV ingest.")
        with daq_api.daq_state_lock:
            daq_api.daq_state.ingest_status = "idle"
        return

    with daq_api.daq_state_lock:
        if daq_api.daq_state.ingest_status == "running":
            return
        daq_api.daq_state.ingest_status = "running"
        daq_api.daq_state.ingest_error = None
    threading.Thread(
        target=daq_api._run_daq_ingest, args=(dataset_root, config_path), daemon=True
    ).start()


def _covering_requests(condition_id: str, channel: str) -> list[daq_api.AnalyseRequest]:
    """Default-settings analysis scopes whose findings include (condition, channel).

    Baselines and findings are computed per (condition_id, channel) from that
    group's canonical windows only, so a broader run (all channels, or the
    whole dataset) yields exactly the findings a narrow run would. Narrowest
    first: those cache files are the smallest to load.
    """
    return [
        daq_api.AnalyseRequest(condition_id=condition_id, channels=[channel]),
        daq_api.AnalyseRequest(condition_id=condition_id),
        daq_api.AnalyseRequest(channels=[channel]),
        daq_api.AnalyseRequest(),
    ]


def _restore_scope_from_cache(condition_id: str, channel: str) -> bool:
    """Load persisted findings for the scope, keeping scopes already in memory.

    Merging (rather than replacing, as ``_restore_analysis_cache`` does) means
    switching between previously asked conditions/channels needs no reload.
    """
    fingerprint = daq_api.daq_state.dataset_fingerprint
    if fingerprint is None:
        return False
    for request in _covering_requests(condition_id, channel):
        cache_path = daq_api._analysis_cache_path(daq_api._analysis_cache_key(fingerprint, request))
        cached = daq_api._read_cache(cache_path)
        if cached is None:
            continue
        state = daq_api.daq_state
        windows = {w.window_id: w for w in state.windows}
        windows.update(
            (w.window_id, w) for w in (daq_api.SignalWindow.model_validate(i) for i in cached["windows"])
        )
        findings = {f.finding_id: f for f in state.findings}
        findings.update(
            (f.finding_id, f) for f in (daq_api.Finding.model_validate(i) for i in cached["findings"])
        )
        profiles = dict(state.baselines.profiles) if state.baselines else {}
        profiles.update(
            ((item["condition_id"], item["channel"]), daq_api.ConditionChannelBaseline(**item))
            for item in cached["baselines"]
        )
        daq_api._hydrate_analysis_state(
            list(windows.values()), list(findings.values()), daq_api.BaselineCollection(profiles=profiles)
        )
        with daq_api.daq_state_lock:
            daq_api.daq_state.analysis_status = "complete"
            daq_api.daq_state.analysis_result = cached["result"]
        return True
    return False


def _start_automatic_analysis(condition_id: str, channel: str) -> bool:
    """Start one scoped job, or restore a covering persisted result immediately."""
    request = daq_api.AnalyseRequest(condition_id=condition_id, channels=[channel])
    if daq_api.daq_state.dataset_fingerprint is None:
        return False
    if daq_api.daq_state.analysis_status != "running" and _restore_scope_from_cache(condition_id, channel):
        return True
    with daq_api.daq_state_lock:
        if daq_api.daq_state.analysis_status == "running":
            return False
        daq_api.daq_state.analysis_status = "running"
        daq_api.daq_state.analysis_error = None
        daq_api.daq_state.analysis_result = None
    threading.Thread(target=daq_api._background_analysis, args=(request,), daemon=True).start()
    return False


def _answer_from_knowledge_docs(question: str) -> dict[str, Any]:
    from llm.orchestrator import answer_unified_query, answer_from_documents, llm

<<<<<<< HEAD
    # 1. First run the unified 6-step cross-source pipeline (PDFs, emails, ontology, sessions)
    try:
        u_ans = answer_unified_query(question)
        if not u_ans.get("in_scope") or u_ans.get("route") == "declined":
            return {
                "answer": u_ans.get("answer", "This system answers questions about the CNC machine, its operation, documentation, sessions, and associated knowledge."),
                "citations": [],
                "finding_count": 0,
                "sources": [],
                "route": "declined",
            }

        sources = []
        for idx, doc in enumerate(u_ans.get("doc_citations", []), start=1):
            sources.append({
                "label": f"Source {idx}",
                "source_path": doc.get("source_path", "knowledge_docs"),
                "doc_id": doc.get("doc_id"),
                "chunk_id": doc.get("chunk_id"),
                "snippet": doc.get("snippet", ""),
            })
        for idx, eml in enumerate(u_ans.get("email_citations", []), start=1):
            sources.append({
                "label": f"Email {idx}",
                "source_path": eml.get("source_path", "knowledge_docs/emails"),
                "doc_id": eml.get("email_id"),
                "chunk_id": eml.get("chunk_id"),
                "subject": eml.get("subject", ""),
                "sender": eml.get("sender", ""),
                "snippet": eml.get("snippet", ""),
            })
        for idx, fnd in enumerate(u_ans.get("finding_citations", []), start=1):
            sources.append({
                "label": f"Finding {idx}",
                "source_path": fnd.get("source_path", "session_data"),
                "finding_id": fnd.get("finding_id"),
                "channel": fnd.get("channel"),
                "snippet": fnd.get("snippet", ""),
            })

        # If unified pipeline retrieved sources or answered successfully
        if sources or u_ans.get("answer"):
            return {
                "answer": u_ans.get("answer", ""),
                "citations": u_ans.get("finding_citations", []),
                "finding_count": len(u_ans.get("finding_citations", [])),
                "email_citations": u_ans.get("email_citations", []),
                "doc_citations": u_ans.get("doc_citations", []),
                "sources": sources,
                "route": u_ans.get("route", "unified"),
            }
    except LLMProviderUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as e:
        print(f"[KnowledgeQuery] unified pipeline error: {e}")

    # 2. Try document-only retrieval fallback
=======
    # 1. Try document/glossary retrieval first (for glossary terms, RMS, kurtosis, SOPs)
>>>>>>> 0b6fcce (fix(retrieval): refine email modality filter and knowledge doc chat routing)
    try:
        ans = answer_from_documents(question)
        if ans is not None and ans.get("sources"):
            return ans
    except LLMProviderUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as e:
<<<<<<< HEAD
        print(f"[KnowledgeQuery] documents fallback error: {e}")

    return {
        "answer": "This system answers questions about the CNC machine, its operation, technical documentation, operational emails, and sensor diagnostics.",
        "citations": [],
        "finding_count": 0,
        "sources": [],
        "route": "general_knowledge",
    }
=======
        print(f"[KnowledgeDocs] document retrieval fallback error: {e}")

    # 2. Run the unified 6-step cross-source pipeline (emails, ontology, cross-source knowledge)
    try:
        u_ans = answer_unified_query(question)
        if not u_ans.get("in_scope") or u_ans.get("route") == "declined":
            return None

        sources = []
        for idx, doc in enumerate(u_ans.get("doc_citations", []), start=1):
            sources.append({
                "label": f"Source {idx}",
                "source_path": doc.get("source_path", "knowledge_docs"),
                "doc_id": doc.get("doc_id"),
                "chunk_id": doc.get("chunk_id"),
                "snippet": doc.get("snippet", ""),
            })
        for idx, eml in enumerate(u_ans.get("email_citations", []), start=1):
            sources.append({
                "label": f"Email {idx}",
                "source_path": eml.get("source_path", "knowledge_docs/emails"),
                "doc_id": eml.get("email_id"),
                "chunk_id": eml.get("chunk_id"),
                "subject": eml.get("subject", ""),
                "sender": eml.get("sender", ""),
                "snippet": eml.get("snippet", ""),
            })
        for idx, fnd in enumerate(u_ans.get("finding_citations", []), start=1):
            sources.append({
                "label": f"Finding {idx}",
                "source_path": fnd.get("source_path", "session_data"),
                "finding_id": fnd.get("finding_id"),
                "channel": fnd.get("channel"),
                "snippet": fnd.get("snippet", ""),
            })

        if sources or u_ans.get("answer"):
            return {
                "answer": u_ans.get("answer", ""),
                "citations": u_ans.get("finding_citations", []),
                "finding_count": len(u_ans.get("finding_citations", [])),
                "email_citations": u_ans.get("email_citations", []),
                "doc_citations": u_ans.get("doc_citations", []),
                "sources": sources,
                "route": u_ans.get("route", "unified"),
            }
    except LLMProviderUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as e:
        print(f"[KnowledgeDocs] unified query error: {e}")

    return None
>>>>>>> 0b6fcce (fix(retrieval): refine email modality filter and knowledge doc chat routing)



@app.get("/knowledge-docs")
def list_knowledge_docs() -> dict[str, Any]:
    """Indexed project knowledge documents and their chunk counts."""
    return {
        "root": str(knowledge_docs.KNOWLEDGE_DOCS_ROOT),
        "documents": knowledge_docs.ingested_documents(),
        "concepts": knowledge_docs.CONCEPTS_PER_DOC,
    }


@app.post("/knowledge-docs/ingest", dependencies=[daq_api.Depends(daq_api.verify_api_key)])
def reingest_knowledge_docs() -> dict[str, Any]:
    """Re-index knowledge_docs/pdfs/ (e.g. after adding or replacing a PDF)."""
    return knowledge_docs.ingest_knowledge_docs(daq_api.pipeline)


@app.post("/chat")
def chat(request: ChatRequest, response: Response) -> dict[str, Any]:
    """Answer a frontend question, automatically preparing the needed evidence.

    In dataset-free mode, queries are answered from the unified multi-source
    knowledge base (PDFs, emails, ontology). When raw DAQ CSVs are mounted,
    numerical window analysis runs with 202 async polling.
    """
    condition_id = request.condition_id or infer_condition_id(request.question)
    channel = request.channel or infer_channel(request.question)

    is_knowledge_or_email = bool(
        re.search(
            r"\b(email|mail|message|report|document|person|who|author|calibration|quarantine|log|maintenance|matrix|latin\s*square|policy|standard|iso|sop|spec)\b",
            request.question,
            re.I,
        )
    )

    # Check if raw DAQ CSV recordings are available on disk
    dataset_present = False
    try:
        raw_root = os.environ.get("DAQ_DATASET_ROOT", "dataset/Readngs_DAQ_Data")
        dataset_root = daq_api.resolve_daq_dataset_root(raw_root)
        dataset_present = dataset_root.is_dir()
    except Exception:
        dataset_present = False

    # In dataset-free mode, or for knowledge/email queries, route directly to the unified knowledge pipeline
    if not dataset_present or is_knowledge_or_email or not condition_id or not channel:
        return _answer_from_knowledge_docs(request.question)

    if daq_api.daq_state.ingest_status in {"idle", "failed"} or not daq_api.daq_state.recordings:
        _start_automatic_ingest()
        response.status_code = 202
        return {"status": "ingesting", "message": "Preparing the DAQ inventory. Retry shortly."}
    if daq_api.daq_state.ingest_status == "running":
        response.status_code = 202
        return {"status": "ingesting", "message": "Preparing the DAQ inventory. Retry shortly."}
    if condition_id not in daq_api.daq_state.conditions:
        return _answer_from_knowledge_docs(request.question)

    if not _scope_is_ready(condition_id, channel):
        restored = _start_automatic_analysis(condition_id, channel)
        if not restored:
            response.status_code = 202
            return {
                "status": "analysing",
                "condition_id": condition_id,
                "channel": channel,
                "message": "Analysing the requested signal. Retry this question when status is analysis_ready.",
                "status_url": "/chat/status",
            }

    return daq_api.query_endpoint(
        req=daq_api.QueryRequest(
            question=request.question,
            filters={"condition_id": condition_id, "channel": channel},
            top_k=request.top_k,
        )
    )


@app.get("/chat/status")
def chat_status() -> dict[str, Any]:
    """Small frontend polling endpoint for automatic preparation jobs."""
    if daq_api.daq_state.ingest_status == "running":
        return {"status": "ingesting"}
    if daq_api.daq_state.ingest_status == "failed":
        raise HTTPException(status_code=500, detail=daq_api.daq_state.ingest_error)
    if daq_api.daq_state.analysis_status == "running":
        return {"status": "analysing"}
    if daq_api.daq_state.analysis_status == "failed":
        raise HTTPException(status_code=500, detail=daq_api.daq_state.analysis_error)
    return {"status": "analysis_ready" if daq_api.daq_state.windows else "ready"}
