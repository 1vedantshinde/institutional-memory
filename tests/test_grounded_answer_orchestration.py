"""Tests for Step 6 — Unified Multi-Source Grounded Answer Generation."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
import pytest

from core.schema import Chunk
from knowledge.graph_store import Neo4jSimulationDriver, neo4j
from llm.orchestrator import (
    UnifiedGroundedOrchestrator,
    answer_unified_query,
)
from llm.prompt_builder import (
    GROUNDED_ANSWER_RULES,
    build_grounded_answer_prompt,
    build_grounded_citations,
)
from retrieval.scope_gate import IN_SCOPE_DECLARE


class _CapturingMockLLM:
    """Mock LLM provider that captures prompts and produces grounded answers."""

    def __init__(self, response_text: str = "Grounded synthesized answer."):
        self.prompts: List[str] = []
        self.system_prompts: List[Optional[str]] = []
        self.response_text = response_text

    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        self.prompts.append(prompt)
        self.system_prompts.append(system_prompt)
        return self.response_text


def test_build_grounded_answer_prompt_formatting() -> None:
    """Validate prompt rendering with distinct [Finding N], [Doc N], [Email N] tags."""
    findings = [
        {
            "finding_id": "f_1",
            "session_id": 42,
            "condition_id": "5",
            "recording_number": 1,
            "channel": "Vib_Spindle",
            "score": 3.85,
            "evidence": {
                "top_departures": [{"feature": "band_energy_low", "departure_sigmas": 3.9}]
            },
        }
    ]
    docs = [
        Chunk(
            chunk_id="doc_chunk_1",
            doc_id="machine_fact_sheet.pdf",
            text="The spindle operates at speed S800 under Latin-square conditions.",
            metadata={"source_path": "machine_fact_sheet.pdf"},
        )
    ]
    emails = [
        Chunk(
            chunk_id="email_chunk_1",
            doc_id="email_101",
            text="Kenneth Lay reported severe spindle vibration during high-speed tests.",
            metadata={"source_path": "101.eml", "subject": "Spindle Vibration", "from": "klay@company.com"},
        )
    ]
    paths = [
        "Session(session:42) -[:EXHIBITS_PATTERN]-> Finding(f_1) -[:RELATED_TO]-> Fault(fault:spindle_fault)"
    ]

    prompt = build_grounded_answer_prompt(
        query="Was the spindle issue in session 42 related to the email discussions?",
        findings=findings,
        document_chunks=docs,
        email_chunks=emails,
        graph_paths=paths,
    )

    assert GROUNDED_ANSWER_RULES in prompt
    assert "[Finding 1]" in prompt
    assert "Session 42 (Condition 5, Rec 1)" in prompt
    assert "Vib_Spindle" in prompt
    assert "[Doc 1] (from machine_fact_sheet.pdf)" in prompt
    assert "[Email 1] (From: klay@company.com | Subject: Spindle Vibration)" in prompt
    assert "Session(session:42) -[:EXHIBITS_PATTERN]-> Finding(f_1)" in prompt


def test_build_grounded_citations_mapping() -> None:
    """Validate structured citation extraction."""
    findings = [
        {
            "finding_id": "f_42",
            "session_id": 42,
            "condition_id": "4",
            "recording_number": 8,
            "channel": "Current",
            "score": 4.1,
            "recording_id": "dataset/4_S800/Recording 8.csv",
        }
    ]
    docs = [
        Chunk(
            chunk_id="c_doc_1",
            doc_id="glossary.pdf",
            text="Kurtosis measures impulsiveness.",
            metadata={"source_path": "knowledge_docs/pdfs/glossary.pdf"},
        )
    ]
    emails = [
        Chunk(
            chunk_id="c_eml_1",
            doc_id="eml_50",
            text="Inspection scheduled for next Tuesday.",
            metadata={"source_path": "inbox/50.eml", "subject": "Inspection Notice", "from": "ops@plant.com"},
        )
    ]

    citations = build_grounded_citations(
        findings=findings,
        document_chunks=docs,
        email_chunks=emails,
    )

    assert len(citations["finding_citations"]) == 1
    assert citations["finding_citations"][0]["label"] == "Finding 1"
    assert citations["finding_citations"][0]["session_id"] == 42
    assert citations["finding_citations"][0]["channel"] == "Current"

    assert len(citations["doc_citations"]) == 1
    assert citations["doc_citations"][0]["label"] == "Doc 1"
    assert "glossary.pdf" in citations["doc_citations"][0]["source_path"]

    assert len(citations["email_citations"]) == 1
    assert citations["email_citations"][0]["label"] == "Email 1"
    assert citations["email_citations"][0]["subject"] == "Inspection Notice"

    assert len(citations["citations"]) == 3


def test_worked_example_1_document_only() -> None:
    """Section 9 Worked Example 1: 'How does the spindle work?' -> Grounded in [Doc N]."""
    # Seed graph with Document -DOCUMENTS-> Component(Spindle)
    neo4j.merge_node("Document", "name", "doc:machine_fact_sheet.pdf", {"title": "machine_fact_sheet.pdf", "source_path": "knowledge_docs/pdfs/machine_fact_sheet.pdf"})
    neo4j.merge_node("Component", "name", "component:spindle", {"name": "Spindle"})
    neo4j.merge_edge("doc:machine_fact_sheet.pdf", "component:spindle", "DOCUMENTS")

    mock_llm = _CapturingMockLLM("The spindle operates with high-speed bearings [Doc 1].")
    query = "How does the spindle work?"

    res = answer_unified_query(query=query, llm_provider=mock_llm)

    assert res["in_scope"] is True
    assert res["answer"] == "The spindle operates with high-speed bearings [Doc 1]."
    assert len(res["doc_citations"]) >= 1
    assert len(mock_llm.prompts) == 1
    assert "How does the spindle work?" in mock_llm.prompts[0]


def test_worked_example_2_email_and_person() -> None:
    """Section 9 Worked Example 2: 'Who discussed the spindle problem?' -> Grounded in [Email N] + Person."""
    # Seed graph with Person -SENT-> Email -MENTIONS-> Component(Spindle)
    neo4j.merge_node("Person", "name", "person:kenneth_lay", {"name": "Kenneth Lay"})
    neo4j.merge_node(
        "Email",
        "name",
        "email:eml_101",
        {"subject": "Spindle Vibration Issue", "body": "Discussed spindle vibration with technicians.", "source_path": "101.eml"},
    )
    neo4j.merge_node("Component", "name", "component:spindle", {"name": "Spindle"})
    neo4j.merge_edge("person:kenneth_lay", "email:eml_101", "SENT")
    neo4j.merge_edge("email:eml_101", "component:spindle", "MENTIONS")

    mock_llm = _CapturingMockLLM("Kenneth Lay discussed the spindle vibration issue in [Email 1].")
    query = "Who discussed the spindle problem?"

    res = answer_unified_query(query=query, llm_provider=mock_llm, max_hops=2)

    assert res["in_scope"] is True
    assert len(res["email_citations"]) >= 1
    assert any("kenneth_lay" in p or "eml_101" in p for p in res["graph_paths"])


def test_worked_example_3_session_finding() -> None:
    """Section 9 Worked Example 3: 'What happened to the spindle in session 42?' -> Grounded in [Finding N]."""
    mock_llm = _CapturingMockLLM("In session 42, spindle vibration showed high low-band energy [Finding 1].")
    query = "What happened to the spindle in session 42?"

    res = answer_unified_query(query=query, llm_provider=mock_llm)

    assert res["in_scope"] is True
    assert len(res["finding_citations"]) >= 1
    assert res["finding_citations"][0]["channel"] == "Vib_Spindle"
    assert "[Finding 1]" in mock_llm.prompts[0]


def test_worked_example_4_cross_source_all_in_one() -> None:
    """Section 9 Worked Example 4: 'Was the issue in session 42 related to the problem discussed in the emails?'

    Grounded in [Finding N] + [Doc N] + [Email N] all in one unified answer.
    """
    neo4j.merge_node("Session", "name", "session:42", {"session_id": 42})
    neo4j.merge_node("Component", "name", "component:spindle", {"name": "Spindle"})
    neo4j.merge_node("Fault", "name", "fault:spindle_fault", {"name": "Spindle Bearing Fault"})
    neo4j.merge_node(
        "Email",
        "name",
        "email:eml_101",
        {"subject": "Spindle Vibration Issue", "body": "Spindle bearing fault suspected."},
    )
    neo4j.merge_edge("session:42", "component:spindle", "OPERATED_ON")
    neo4j.merge_edge("email:eml_101", "component:spindle", "MENTIONS")
    neo4j.merge_edge("fault:spindle_fault", "component:spindle", "CAUSED_BY")

    mock_llm = _CapturingMockLLM(
        "The anomaly in session 42 [Finding 1] aligns with the spindle bearing fault [Doc 1] "
        "and was discussed by the maintenance team in [Email 1]."
    )
    query = "Was the issue in session 42 related to the problem discussed in the emails?"

    orchestrator = UnifiedGroundedOrchestrator(llm_provider=mock_llm)
    res = orchestrator.query(query)

    assert res["in_scope"] is True
    assert res["route"] == "cross_source"
    assert len(res["finding_citations"]) >= 1
    assert len(res["email_citations"]) >= 1
    assert len(res["cross_source_links"]) >= 1
    assert len(res["citations"]) >= 2


def test_out_of_scope_query_strict_decline() -> None:
    """Validate that out-of-scope queries return exact decline declaration with zero LLM generation."""
    mock_llm = _CapturingMockLLM("Should not run.")
    query = "What is the capital of France?"

    res = answer_unified_query(query=query, llm_provider=mock_llm)

    assert res["in_scope"] is False
    assert res["answer"] == IN_SCOPE_DECLARE
    assert res["citations"] == []
    assert res["finding_count"] == 0
    assert res["doc_count"] == 0
    assert res["email_count"] == 0
    assert len(mock_llm.prompts) == 0  # LLM never called for out-of-scope query
