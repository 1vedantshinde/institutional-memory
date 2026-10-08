"""Tests for Step 5 — Session Analytics & Cross-Source Reasoning Engine."""

from __future__ import annotations

import pytest

from analytics.session_analyzer import (
    CrossSourceReasoningResult,
    analyze_cross_source_evidence,
    ensure_session_analysis,
    findings_exist,
    get_findings,
    resolve_session,
    run_session_analysis,
)
from knowledge.session_ids import SESSION_REGISTRY
from retrieval.node_data_retriever import (
    RetrievedGraphData,
    RetrievedNodeData,
    retrieve_data_for_subgraph,
)
from retrieval.query_understanding import understand_query
from retrieval.graph_query import Subgraph, traverse
from knowledge.graph_store import Neo4jSimulationDriver


def test_resolve_session_coordinates() -> None:
    """Validate session_id resolution to (condition_id, recording_number)."""
    cid, rec_num = resolve_session(42)
    assert cid is not None
    assert rec_num is not None
    assert isinstance(rec_num, int)


def test_ensure_session_analysis_triggers_and_caches() -> None:
    """Validate that ensure_session_analysis triggers computation when findings don't exist and reuses when cached."""
    session_id = 42
    channel = "Vib_Spindle"
    cid, rec_num = resolve_session(session_id)

    # 1. Trigger analysis for session
    findings = ensure_session_analysis(session_id, channel=channel)
    assert isinstance(findings, list)

    # 2. Verify findings_exist is now True
    assert findings_exist(cid, rec_num, channel) is True

    # 3. Call again and verify cached findings returned immediately
    findings_cached = ensure_session_analysis(session_id, channel=channel)
    assert len(findings_cached) == len(findings)


def test_ensure_session_analysis_channel_filtering() -> None:
    """Validate channel-specific finding retrieval."""
    session_id = 15
    spindle_findings = ensure_session_analysis(session_id, channel="Vib_Spindle")
    for f in spindle_findings:
        assert f.get("channel") == "Vib_Spindle"


def test_analyze_cross_source_evidence_synthesis() -> None:
    """Validate cross-modal reasoning linking session findings with emails and fault docs."""
    query = "Was the issue in session 42 related to the problem discussed in the emails?"
    qu_res = understand_query(query)

    # Mock retrieved data
    driver = Neo4jSimulationDriver()
    driver.merge_node("Session", "name", "session:42", {"session_id": 42})
    driver.merge_node(
        "Email",
        "name",
        "email:eml_101",
        {"subject": "Spindle Vibration Alarm", "body": "Spindle bearings vibrating excessively."},
    )
    driver.merge_node("Component", "name", "component:spindle", {"name": "Spindle"})
    driver.merge_edge("email:eml_101", "component:spindle", "MENTIONS")
    driver.merge_edge("session:42", "component:spindle", "OPERATED_ON")

    subgraph = traverse(seed_entities=["session:42"], max_hops=2, graph_driver=driver)
    retrieved_data = retrieve_data_for_subgraph(subgraph, query=query)

    reasoning_res = analyze_cross_source_evidence(retrieved_data, qu_res)

    assert isinstance(reasoning_res, CrossSourceReasoningResult)
    assert len(reasoning_res.corroborating_emails) >= 1
    assert len(reasoning_res.cross_source_links) >= 1
    assert reasoning_res.is_cross_source is True

    link = reasoning_res.cross_source_links[0]
    assert link.session_id == 42
    assert "Spindle" in link.summary_claim or "anomaly score" in link.summary_claim
