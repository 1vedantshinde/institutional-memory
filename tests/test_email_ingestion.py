"""Comprehensive Unit Tests for Machine Email Ingestion & Filtering.

Verifies:
1. Ingestion of machine operational, maintenance, calibration, and experimental emails.
2. Filtering out & discarding of non-machine emails (e.g. Enron corporate talk, energy trading).
3. Neo4j Knowledge Graph typed node & relationship linking (Person -> SENT -> Email -> MENTIONS -> Component/Fault/Condition).
4. Grounded question answering on the basis of machine emails citing [Email N].
5. Scope Gate rejection for out-of-scope non-machine questions returning IN_SCOPE_DECLARE.
"""

from __future__ import annotations

import os
from pathlib import Path
import pytest

from core.schema import Chunk
from ingestion.pipeline import IngestionPipeline
from ingestion import emails
from knowledge.graph_store import neo4j
from retrieval.query_understanding import understand_query, QueryIntent
from retrieval.scope_gate import evaluate_scope_gate, IN_SCOPE_DECLARE
from llm.orchestrator import answer_unified_query, UnifiedGroundedOrchestrator


@pytest.fixture(autouse=True)
def clean_pipeline():
    """Create fresh in-memory pipeline for test isolation."""
    p = IngestionPipeline(
        embedder_key="mock",
        vector_store_key="in_memory",
        graph_store_key="in_memory"
    )
    # Clear neo4j simulation driver
    neo4j.nodes.clear()
    neo4j.edges.clear()
    return p


def test_machine_relevance_filter():
    """Verify machine relevance filter correctly identifies machine vs non-machine emails."""
    # Machine email text
    machine_text_1 = (
        "Subject: High Spindle Vibration Alert\n"
        "We observed severe kurtosis exceeding +4.8 sigma during Condition 4 face milling operations. "
        "Recommend inspecting the spindle bearing runout."
    )
    is_rel, reason = emails.is_machine_relevant_email(machine_text_1, subject="High Spindle Vibration Alert")
    assert is_rel is True
    assert "matched" in reason

    machine_text_2 = (
        "Subject: Kistler Dynamometer 3-Axis Calibration\n"
        "The piezoelectric load cells X_Load_Cell and Z_Load_Cell were calibrated at 10 kHz."
    )
    is_rel, reason = emails.is_machine_relevant_email(machine_text_2, subject="Calibration Verification")
    assert is_rel is True

    # Non-machine email text (Enron / corporate / trading)
    non_machine_text_1 = (
        "Subject: Associate & Analyst Program\n"
        "Please click the link below to access a message from the Office of the Chairman regarding energy trading contracts."
    )
    is_rel, reason = emails.is_machine_relevant_email(non_machine_text_1, subject="Associate & Analyst Program")
    assert is_rel is False
    assert reason == "discarded_not_machine_related"

    non_machine_text_2 = (
        "Subject: Dinner next Tuesday\n"
        "Hey Bob, are you available for pizza after work? Let me know."
    )
    is_rel, reason = emails.is_machine_relevant_email(non_machine_text_2, subject="Dinner next Tuesday")
    assert is_rel is False
    assert reason == "discarded_not_machine_related"


def test_ingest_machine_emails_links_graph(clean_pipeline):
    """Verify ingest_machine_emails indexes all machine emails and creates graph nodes & edges."""
    res = emails.ingest_machine_emails(clean_pipeline, force=True)
    
    assert res["ingested_count"] >= 6
    assert res["discarded_count"] >= 0
    assert "spindle_vibration_alert_cond4.eml" in res["emails"]
    assert "tool_wear_inspection_cond12.eml" in res["emails"]
    assert "kistler_dynamometer_calibration.eml" in res["emails"]
    assert "quarantine_corrupt_csv_incident.eml" in res["emails"]
    assert "spindle_bearing_lubrication_log.eml" in res["emails"]
    assert "cutting_conditions_latin_square.eml" in res["emails"]

    # Verify Neo4j Graph elements
    nodes = neo4j.nodes
    edges = neo4j.edges

    # Check Email nodes exist
    assert "email:spindle_vibration_alert_cond4.eml" in nodes
    assert "email:tool_wear_inspection_cond12.eml" in nodes

    # Check Person nodes exist
    assert "person:marcus_vance" in nodes
    assert "person:david_chen" in nodes
    assert "person:dr._elena_rodriguez" in nodes or any("rodriguez" in n for n in nodes)

    # Check Relationships
    sent_edges = [e for e in edges if e.type == "SENT"]
    assert len(sent_edges) >= 6

    mentions_edges = [e for e in edges if e.type == "MENTIONS"]
    assert len(mentions_edges) >= 6


def test_scope_gate_allows_machine_email_and_declines_non_machine():
    """Verify scope gate accepts machine engineer/email queries and declines out-of-scope emails."""
    # Machine email questions -> In Scope
    q_machine_1 = "What did Marcus Vance report in his email about spindle vibration?"
    gate_res_1 = evaluate_scope_gate(q_machine_1)
    assert gate_res_1.in_scope is True

    q_machine_2 = "What did David Chen report about flank wear on Condition 12 cutters?"
    gate_res_2 = evaluate_scope_gate(q_machine_2)
    assert gate_res_2.in_scope is True

    q_machine_3 = "What emails discuss Kistler dynamometer calibration?"
    gate_res_3 = evaluate_scope_gate(q_machine_3)
    assert gate_res_3.in_scope is True

    # Non-machine email questions -> Out of Scope (Declined)
    q_non_machine_1 = "What did Jeffrey Skilling say about Enron stock prices?"
    gate_res_non_1 = evaluate_scope_gate(q_non_machine_1)
    assert gate_res_non_1.in_scope is False
    assert gate_res_non_1.decline_message == IN_SCOPE_DECLARE

    q_non_machine_2 = "Summarize emails about California power trading contracts"
    gate_res_non_2 = evaluate_scope_gate(q_non_machine_2)
    assert gate_res_non_2.in_scope is False
    assert gate_res_non_2.decline_message == IN_SCOPE_DECLARE


def test_grounded_answer_from_machine_emails(clean_pipeline):
    """Verify unified orchestrator answers machine email questions with email citations."""
    emails.ingest_machine_emails(clean_pipeline, force=True)

    # Ask about Marcus Vance's Condition 4 alert
    q = "What did Marcus Vance report about high spindle vibration during Condition 4?"
    ans = answer_unified_query(q)

    assert ans["in_scope"] is True
    assert ans["route"] in ("emails", "cross_source", "documents")
    assert len(ans["email_citations"]) >= 1 or len(ans["citations"]) >= 1
    # Check email citation details
    if ans["email_citations"]:
        eml_c = ans["email_citations"][0]
        assert "Email" in eml_c["label"]
        assert "spindle" in eml_c.get("snippet", "").lower() or "vance" in eml_c.get("sender", "").lower() or "spindle" in eml_c.get("subject", "").lower()


def test_non_machine_email_rejected_with_in_scope_declare():
    """Verify non-machine email questions are strictly declined."""
    q_out = "What was Kenneth Lay's compensation discussed in Enron emails?"
    ans = answer_unified_query(q_out)

    assert ans["in_scope"] is False
    assert ans["answer"] == IN_SCOPE_DECLARE
    assert ans["route"] == "declined"
    assert len(ans["email_citations"]) == 0
    assert len(ans["finding_citations"]) == 0
