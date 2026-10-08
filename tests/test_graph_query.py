"""Tests for Step 3 — Multi-Hop Knowledge Graph Traversal Engine."""

from __future__ import annotations

import pytest

from core.schema import Edge, Node
from knowledge.graph_store import Neo4jSimulationDriver
from retrieval.graph_query import (
    GraphPath,
    Subgraph,
    subgraph_to_context_chunks,
    traverse,
    traverse_from_query,
)
from retrieval.query_understanding import understand_query


@pytest.fixture
def mock_graph_driver() -> Neo4jSimulationDriver:
    """Populate a test simulation graph spanning People, Emails, Components, Docs, Faults, and Sessions."""
    driver = Neo4jSimulationDriver()

    # Nodes
    driver.merge_node("Person", "name", "person:kenneth_lay", {"name": "Kenneth Lay"})
    driver.merge_node("Person", "name", "person:jeffrey_skilling", {"name": "Jeffrey Skilling"})
    driver.merge_node("Email", "name", "email:eml_101", {"subject": "Spindle Vibration & Tool Wear Issue"})
    driver.merge_node("Component", "name", "component:spindle", {"name": "Main Spindle"})
    driver.merge_node("Component", "name", "component:spindle_motor", {"name": "Spindle Drive Motor"})
    driver.merge_node("Fault", "name", "fault:bearing_fault", {"name": "Spindle Bearing Fault"})
    driver.merge_node("Document", "name", "doc:machine_fact_sheet", {"title": "Machine Fact Sheet"})
    driver.merge_node("Session", "name", "session:42", {"session_id": 42, "condition_id": "5", "recording_number": 1})
    driver.merge_node("Finding", "name", "finding:f_42_vib", {"score": 4.8, "channel": "Vib_Spindle"})

    # Edges
    # 1. Email <-> Person / Component
    driver.merge_edge("person:kenneth_lay", "email:eml_101", "SENT")
    driver.merge_edge("person:jeffrey_skilling", "email:eml_101", "RECEIVED")
    driver.merge_edge("email:eml_101", "component:spindle", "MENTIONS")

    # 2. Hierarchy & Documentation
    driver.merge_edge("component:spindle_motor", "component:spindle", "PART_OF")
    driver.merge_edge("doc:machine_fact_sheet", "component:spindle", "DOCUMENTS")

    # 3. Fault <-> Component
    driver.merge_edge("fault:bearing_fault", "component:spindle", "CAUSED_BY")

    # 4. DAQ Session <-> Finding <-> Fault / Email (Cross-Source Edges)
    driver.merge_edge("session:42", "finding:f_42_vib", "EXHIBITS_PATTERN")
    driver.merge_edge("finding:f_42_vib", "fault:bearing_fault", "RELATED_TO")
    driver.merge_edge("email:eml_101", "finding:f_42_vib", "CORROBORATES")

    return driver


def test_one_hop_traversal_around_component(mock_graph_driver: Neo4jSimulationDriver) -> None:
    """Validate 1-hop traversal around component:spindle."""
    subgraph = traverse(
        seed_entities=["component:spindle"],
        max_hops=1,
        graph_driver=mock_graph_driver,
    )

    assert "component:spindle" in subgraph.seed_node_ids
    assert len(subgraph.nodes) >= 4
    assert any("PART_OF" in t for t in subgraph.triplets)
    assert any("DOCUMENTS" in t for t in subgraph.triplets)
    assert any("MENTIONS" in t for t in subgraph.triplets)
    assert any("CAUSED_BY" in t for t in subgraph.triplets)
    assert subgraph.max_hops_reached == 1


def test_two_hop_cross_source_traversal(mock_graph_driver: Neo4jSimulationDriver) -> None:
    """Validate 2-hop traversal connecting Person -> Email -> Component -> Fault -> Finding -> Session."""
    # Seed from Person Kenneth Lay
    subgraph = traverse(
        seed_entities=["person:kenneth_lay"],
        max_hops=2,
        graph_driver=mock_graph_driver,
    )

    assert "person:kenneth_lay" in subgraph.seed_node_ids
    assert "email:eml_101" in subgraph.nodes
    assert "component:spindle" in subgraph.nodes

    # Check 2-hop paths
    path_formatted_list = [p.formatted for p in subgraph.paths]
    assert any("person:kenneth_lay -[:SENT]-> email:eml_101 -[:MENTIONS]-> component:spindle" in p for p in path_formatted_list)
    assert subgraph.max_hops_reached == 2
    assert "Component" in subgraph.entities_by_type
    assert "Email" in subgraph.entities_by_type


def test_traversal_from_session_seeds(mock_graph_driver: Neo4jSimulationDriver) -> None:
    """Validate 2-hop traversal starting from session:42 reaching findings, faults, and corroborating emails."""
    subgraph = traverse(
        seed_entities=["session:42"],
        max_hops=2,
        graph_driver=mock_graph_driver,
    )

    assert "session:42" in subgraph.seed_node_ids
    assert "finding:f_42_vib" in subgraph.nodes
    assert "fault:bearing_fault" in subgraph.nodes
    assert "email:eml_101" in subgraph.nodes  # via finding:f_42_vib -[:CORROBORATES]-> email:eml_101

    assert "Finding" in subgraph.entities_by_type
    assert "Fault" in subgraph.entities_by_type
    assert "Email" in subgraph.entities_by_type


def test_traverse_from_query_understanding(mock_graph_driver: Neo4jSimulationDriver) -> None:
    """Validate traverse_from_query connecting Step 1 entity understanding directly to Step 3 graph traversal."""
    query = "Was the issue in session 42 related to the problem discussed in the emails?"
    qu_res = understand_query(query)

    subgraph = traverse_from_query(
        query_understanding=qu_res,
        max_hops=2,
        graph_driver=mock_graph_driver,
    )

    assert "session:42" in subgraph.seed_node_ids
    assert "finding:f_42_vib" in subgraph.nodes
    assert len(subgraph.paths) > 0


def test_traversal_size_and_hop_capping(mock_graph_driver: Neo4jSimulationDriver) -> None:
    """Ensure hard limits on max_nodes and max_edges prevent explosive expansion."""
    subgraph = traverse(
        seed_entities=["component:spindle"],
        max_hops=3,
        max_nodes=3,
        max_edges=2,
        graph_driver=mock_graph_driver,
    )

    assert len(subgraph.nodes) <= 4
    assert len(subgraph.edges) <= 3
    assert subgraph.is_capped is True


def test_subgraph_to_context_chunks_formatting(mock_graph_driver: Neo4jSimulationDriver) -> None:
    """Validate conversion of Subgraph paths and triplets into retrieval Context Chunks."""
    subgraph = traverse(
        seed_entities=["person:kenneth_lay"],
        max_hops=2,
        graph_driver=mock_graph_driver,
    )

    chunks = subgraph_to_context_chunks(subgraph, max_chunks=5)
    assert len(chunks) > 0
    assert chunks[0].doc_id == "knowledge_graph"
    assert chunks[0].metadata["modality"] == "graph"
    assert "Graph Path" in chunks[0].text
    assert "SENT" in chunks[0].text
