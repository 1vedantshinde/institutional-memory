"""Tests for Step 4 — Node-Guided Data Retrieval Engine."""

from __future__ import annotations

import pytest

from core.schema import Chunk, Finding
from knowledge.graph_store import Neo4jSimulationDriver
from retrieval.graph_query import Subgraph, traverse
from retrieval.node_data_retriever import (
    RetrievedGraphData,
    RetrievedNodeData,
    retrieve_data_for_subgraph,
    retrieve_node_data,
    retrieve_relevant_data,
)


@pytest.fixture
def mock_subgraph_and_driver() -> tuple[Subgraph, Neo4jSimulationDriver]:
    """Create a populated graph and traverse a multi-modal subgraph."""
    driver = Neo4jSimulationDriver()

    # Merge nodes with rich properties
    driver.merge_node("Person", "name", "person:kenneth_lay", {"name": "Kenneth Lay"})
    driver.merge_node(
        "Email",
        "name",
        "email:eml_101",
        {
            "subject": "Spindle Vibration Issue in Lab",
            "body": "We observed excessive vibration on the main spindle during facing operations.",
            "source_path": "email_corpus/enron/lay-k/inbox/101.eml",
        },
    )
    driver.merge_node("Component", "name", "component:spindle", {"name": "Main Spindle"})
    driver.merge_node("Document", "name", "doc:machine_fact_sheet.pdf", {"title": "machine_fact_sheet.pdf", "source_path": "machine_fact_sheet.pdf"})
    driver.merge_node("Concept", "name", "concept:kurtosis", {"term": "Kurtosis"})
    driver.merge_node(
        "Session",
        "name",
        "session:42",
        {"session_id": 42, "condition_id": "5", "recording_number": 1, "score": 4.5, "channel": "Vib_Spindle"},
    )

    # Merge edges
    driver.merge_edge("person:kenneth_lay", "email:eml_101", "SENT")
    driver.merge_edge("email:eml_101", "component:spindle", "MENTIONS")
    driver.merge_edge("doc:machine_fact_sheet.pdf", "component:spindle", "DOCUMENTS")
    driver.merge_edge("session:42", "component:spindle", "OPERATED_ON")
    driver.merge_edge("doc:machine_fact_sheet.pdf", "concept:kurtosis", "EXPLAINS")

    subgraph = traverse(
        seed_entities=["component:spindle"],
        max_hops=2,
        graph_driver=driver,
    )
    return subgraph, driver


def test_individual_email_node_retrieval() -> None:
    """Validate data retrieval for an individual email node."""
    node_data = {
        "label": "Email",
        "properties": {
            "subject": "Spindle Vibration Anomaly",
            "body": "The vibration on spindle bearings reached critical levels.",
            "source_path": "emails/inbox/202.eml",
        },
    }
    res = retrieve_node_data(
        node_id="email:202",
        node_data=node_data,
        query="spindle vibration",
    )

    assert res.entity_type == "Email"
    assert "Spindle Vibration Anomaly" in res.title
    assert len(res.chunks) >= 1
    assert "critical levels" in res.content_text
    assert res.provenance.source_type == "email"


def test_individual_session_node_retrieval() -> None:
    """Validate data retrieval for a session node pulling findings."""
    custom_finding = {
        "finding_id": "finding_42",
        "recording_id": "Condition_5_Recording_1",
        "session_id": 42,
        "score": 4.8,
        "channel": "Vib_Spindle",
        "evidence": {
            "top_departures": [
                {"feature": "band_energy_low", "departure_sigmas": 4.8},
                {"feature": "kurtosis", "departure_sigmas": 3.2},
            ]
        },
    }
    node_data = {
        "label": "Session",
        "properties": {"session_id": 42, "condition_id": "5", "recording_number": 1},
    }
    res = retrieve_node_data(
        node_id="session:42",
        node_data=node_data,
        custom_findings=[custom_finding],
    )

    assert res.entity_type == "Session"
    assert len(res.findings) >= 1
    assert res.findings[0]["score"] == 4.8
    assert res.provenance.source_type == "session_data"


def test_individual_concept_node_retrieval() -> None:
    """Validate data retrieval for a concept node resolving glossary definitions."""
    node_data = {"label": "Concept", "properties": {}}
    res = retrieve_node_data(
        node_id="concept:kurtosis",
        node_data=node_data,
    )

    assert res.entity_type == "Concept"
    assert "Kurtosis" in res.title
    # Definition should be populated from domain.yaml
    assert "spiky" in res.content_text.lower() or "signal" in res.content_text.lower()


def test_subgraph_data_retrieval_aggregation(
    mock_subgraph_and_driver: tuple[Subgraph, Neo4jSimulationDriver]
) -> None:
    """Validate aggregated retrieval over a multi-modal traversed subgraph."""
    subgraph, _ = mock_subgraph_and_driver
    retrieved_data = retrieve_data_for_subgraph(
        subgraph=subgraph,
        query="spindle vibration issues",
    )

    assert isinstance(retrieved_data, RetrievedGraphData)
    assert len(retrieved_data.node_data) == len(subgraph.nodes)
    assert len(retrieved_data.email_passages) >= 1
    assert len(retrieved_data.session_findings) >= 1
    assert len(retrieved_data.concept_explanations) >= 1

    # Verify structured evidence blocks
    blocks = retrieved_data.format_evidence_blocks()
    assert len(blocks) > 0
    full_text = "\n".join(blocks)
    assert "Organizational & Email Evidence" in full_text
    assert "CNC Machine Session & Signal Findings" in full_text


def test_retrieve_relevant_data_e2e(
    mock_subgraph_and_driver: tuple[Subgraph, Neo4jSimulationDriver]
) -> None:
    """Validate end-to-end Step 4 entrypoint retrieve_relevant_data."""
    _, driver = mock_subgraph_and_driver
    query = "Was the spindle issue in session 42 discussed in emails?"

    retrieved = retrieve_relevant_data(
        query=query,
        max_hops=2,
        graph_driver=driver,
    )

    assert isinstance(retrieved, RetrievedGraphData)
    assert retrieved.query == query
    assert len(retrieved.node_data) > 0
