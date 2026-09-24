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
from typing import Any

from fastapi import HTTPException, Response
from pydantic import BaseModel, Field

import api.main as daq_api


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
    dataset_root = daq_api.resolve_daq_dataset_root(
        os.environ.get("DAQ_DATASET_ROOT", "dataset/Readngs_DAQ_Data")
    )
    config_path = daq_api.resolve_project_path(
        os.environ.get("DAQ_CONFIG_PATH", "config/domain.yaml")
    )
    with daq_api.daq_state_lock:
        if daq_api.daq_state.ingest_status == "running":
            return
        daq_api.daq_state.ingest_status = "running"
        daq_api.daq_state.ingest_error = None
    threading.Thread(
        target=daq_api._run_daq_ingest, args=(dataset_root, config_path), daemon=True
    ).start()


def _start_automatic_analysis(condition_id: str, channel: str) -> bool:
    """Start one scoped job, or restore an exact persisted result immediately."""
    request = daq_api.AnalyseRequest(condition_id=condition_id, channels=[channel])
    if daq_api.daq_state.dataset_fingerprint is None:
        return False
    cache_key = daq_api._analysis_cache_key(daq_api.daq_state.dataset_fingerprint, request)
    cached = daq_api._read_cache(daq_api._analysis_cache_path(cache_key))
    if cached is not None:
        daq_api._restore_analysis_cache(cached)
        with daq_api.daq_state_lock:
            daq_api.daq_state.analysis_status = "complete"
            daq_api.daq_state.analysis_result = cached["result"]
        return True
    with daq_api.daq_state_lock:
        if daq_api.daq_state.analysis_status == "running":
            return False
        daq_api.daq_state.analysis_status = "running"
        daq_api.daq_state.analysis_error = None
        daq_api.daq_state.analysis_result = None
    threading.Thread(target=daq_api._background_analysis, args=(request,), daemon=True).start()
    return False


@app.post("/chat")
def chat(request: ChatRequest, response: Response) -> dict[str, Any]:
    """Answer a frontend question, automatically preparing the needed evidence.

    A new scope responds with HTTP 202 while analytics runs. Re-submit the same
    question after `/chat/status` reports ``analysis_ready``. A cached scope
    restores and answers in the same request.
    """
    condition_id = request.condition_id or infer_condition_id(request.question)
    channel = request.channel or infer_channel(request.question)
    if not condition_id or not channel:
        raise HTTPException(
            status_code=422,
            detail=(
                "State both a condition and one signal, for example: 'Explain spindle "
                "vibration for condition 4.' You may also send condition_id and channel."
            ),
        )

    if daq_api.daq_state.ingest_status in {"idle", "failed"} or not daq_api.daq_state.recordings:
        _start_automatic_ingest()
        response.status_code = 202
        return {"status": "ingesting", "message": "Preparing the DAQ inventory. Retry shortly."}
    if daq_api.daq_state.ingest_status == "running":
        response.status_code = 202
        return {"status": "ingesting", "message": "Preparing the DAQ inventory. Retry shortly."}
    if condition_id not in daq_api.daq_state.conditions:
        raise HTTPException(status_code=404, detail=f"Unknown condition_id: {condition_id}")

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
