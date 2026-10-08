"""Typed DAQ, Document, and Organizational provenance ontology and graph population helpers."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from core.schema import Condition, Finding, Recording, SignalWindow
from knowledge.graph_store import Neo4jSimulationDriver


# DAQ Relation Types
CAPTURED_UNDER = "CAPTURED_UNDER"
HAS_WINDOW = "HAS_WINDOW"
EXHIBITS_PATTERN = "EXHIBITS_PATTERN"
OCCURRED_DURING = "OCCURRED_DURING"

# Documentation Relation Types
DOCUMENTS = "DOCUMENTS"
PART_OF = "PART_OF"
REQUIRES = "REQUIRES"
CAUSED_BY = "CAUSED_BY"
EXPLAINS = "EXPLAINS"

# Email / Organizational Relation Types
SENT = "SENT"
RECEIVED = "RECEIVED"
PART_OF_THREAD = "PART_OF_THREAD"
WORKS_AT = "WORKS_AT"
MENTIONS = "MENTIONS"
DISCUSSES = "DISCUSSES"

# Cross-Source Relation Types
RELATED_TO = "RELATED_TO"
CORROBORATES = "CORROBORATES"
MAINTAINED_BY = "MAINTAINED_BY"
SIMILAR_TO = "SIMILAR_TO"
SUPERSEDES = "SUPERSEDES"
MENTIONED_IN = "MENTIONED_IN"

DAQ_RELATION_TYPES = {
    CAPTURED_UNDER,
    HAS_WINDOW,
    EXHIBITS_PATTERN,
    OCCURRED_DURING,
    SIMILAR_TO,
}

UNIFIED_RELATION_TYPES = {
    CAPTURED_UNDER,
    HAS_WINDOW,
    EXHIBITS_PATTERN,
    OCCURRED_DURING,
    DOCUMENTS,
    PART_OF,
    REQUIRES,
    CAUSED_BY,
    EXPLAINS,
    SENT,
    RECEIVED,
    PART_OF_THREAD,
    WORKS_AT,
    MENTIONS,
    DISCUSSES,
    RELATED_TO,
    CORROBORATES,
    MAINTAINED_BY,
    SIMILAR_TO,
    SUPERSEDES,
    MENTIONED_IN,
}


class OntologyError(ValueError):
    """A graph relationship is missing required typed provenance or violates ontology constraints."""


# --- Node ID Generators ------------------------------------------------------

def condition_node_id(condition_id: str) -> str:
    return f"condition:{condition_id}"


def recording_node_id(recording_id: str) -> str:
    return f"recording:{recording_id}"


def session_node_id(session_id: Any) -> str:
    return f"session:{session_id}"


def window_node_id(window_id: str) -> str:
    return f"window:{window_id}"


def finding_node_id(finding_id: str) -> str:
    return f"finding:{finding_id}"


def event_node_id(event_id: str) -> str:
    return f"event:{event_id}"


def component_node_id(name: str) -> str:
    clean = name.strip().lower().replace(" ", "_").replace("-", "_")
    return f"component:{clean}"


def fault_node_id(name: str) -> str:
    clean = name.strip().lower().replace(" ", "_").replace("-", "_")
    return f"fault:{clean}"


def process_node_id(name: str) -> str:
    clean = name.strip().lower().replace(" ", "_").replace("-", "_")
    return f"process:{clean}"


def procedure_node_id(name: str) -> str:
    clean = name.strip().lower().replace(" ", "_").replace("-", "_")
    return f"procedure:{clean}"


def parameter_node_id(name: str) -> str:
    clean = name.strip().lower().replace(" ", "_").replace("-", "_")
    return f"parameter:{clean}"


def channel_node_id(name: str) -> str:
    return f"channel:{name.strip()}"


def person_node_id(name: str) -> str:
    clean = name.strip().lower().replace(" ", "_")
    return f"person:{clean}"


def organization_node_id(name: str) -> str:
    clean = name.strip().lower().replace(" ", "_")
    return f"org:{clean}"


def email_node_id(msg_id: str) -> str:
    clean = msg_id.strip().strip("<>").replace(" ", "_")
    return f"email:{clean}"


def thread_node_id(thread_id: str) -> str:
    return f"thread:{thread_id.strip()}"


def document_node_id(doc_id: str) -> str:
    return f"doc:{doc_id.strip()}"


def concept_node_id(term: str) -> str:
    clean = term.strip().lower().replace(" ", "_")
    return f"concept:{clean}"


# --- Graph Population Helpers ------------------------------------------------

def add_condition(driver: Neo4jSimulationDriver, condition: Condition) -> str:
    node_id = condition_node_id(condition.condition_id)
    driver.merge_node("Condition", "condition_id", node_id, condition.model_dump())
    return node_id


def add_recording(driver: Neo4jSimulationDriver, condition: Condition, recording: Recording) -> str:
    if recording.condition_id != condition.condition_id:
        raise OntologyError("recording_condition_id_mismatch")
    condition_id = add_condition(driver, condition)
    node_id = recording_node_id(recording.recording_id)
    driver.merge_node("Recording", "recording_id", node_id, recording.model_dump())
    driver.merge_edge(condition_id, node_id, CAPTURED_UNDER)
    return node_id


def add_window(driver: Neo4jSimulationDriver, recording: Recording, window: SignalWindow) -> str:
    if window.recording_id != recording.recording_id:
        raise OntologyError("window_recording_id_mismatch")
    node_id = window_node_id(window.window_id)
    driver.merge_node("SignalWindow", "window_id", node_id, window.model_dump())
    driver.merge_edge(recording_node_id(recording.recording_id), node_id, HAS_WINDOW)
    return node_id


def add_finding(driver: Neo4jSimulationDriver, window: SignalWindow, finding: Finding) -> str:
    if finding.window_id != window.window_id or finding.recording_id != window.recording_id:
        raise OntologyError("finding_window_or_recording_id_mismatch")
    node_id = finding_node_id(finding.finding_id)
    driver.merge_node("Finding", "finding_id", node_id, finding.model_dump())
    driver.merge_edge(window_node_id(window.window_id), node_id, EXHIBITS_PATTERN)
    return node_id


def link_similar_windows(
    driver: Neo4jSimulationDriver,
    source_window: SignalWindow,
    target_window: SignalWindow,
    *,
    similarity: float,
) -> None:
    """Store a feature-similarity link after both window nodes exist."""
    if source_window.window_id == target_window.window_id:
        raise OntologyError("self_similarity_link_not_allowed")
    driver.merge_edge(
        window_node_id(source_window.window_id),
        window_node_id(target_window.window_id),
        SIMILAR_TO,
        {"similarity": float(similarity)},
    )


def populate_provenance_graph(
    driver: Neo4jSimulationDriver,
    conditions: Iterable[Condition],
    recordings: Iterable[Recording],
    windows: Iterable[SignalWindow],
    findings: Iterable[Finding],
) -> None:
    """Populate Condition → Recording → Window → Finding provenance edges."""
    condition_index = {condition.condition_id: condition for condition in conditions}
    recording_index = {recording.recording_id: recording for recording in recordings}
    window_index = {window.window_id: window for window in windows}
    for condition in condition_index.values():
        add_condition(driver, condition)
    for recording in recording_index.values():
        condition = condition_index.get(recording.condition_id)
        if condition is None:
            raise OntologyError(f"recording_references_unknown_condition:{recording.condition_id}")
        add_recording(driver, condition, recording)
    for window in window_index.values():
        recording = recording_index.get(window.recording_id)
        if recording is None:
            raise OntologyError(f"window_references_unknown_recording:{window.recording_id}")
        add_window(driver, recording, window)
    for finding in findings:
        if finding.window_id is None:
            raise OntologyError("finding_without_window_cannot_form_daq_provenance_edge")
        window = window_index.get(finding.window_id)
        if window is None:
            raise OntologyError(f"finding_references_unknown_window:{finding.window_id}")
        add_finding(driver, window, finding)
