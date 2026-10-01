"""Tests for typed DAQ provenance graph storage and ontology relationships."""

from __future__ import annotations

from core.schema import Condition, Finding, Recording, SignalWindow
from knowledge.graph_store import GraphEdge, Neo4jSimulationDriver
from knowledge.ontology import (
    CAPTURED_UNDER,
    EXHIBITS_PATTERN,
    HAS_WINDOW,
    SIMILAR_TO,
    condition_node_id,
    link_similar_windows,
    populate_provenance_graph,
    recording_node_id,
    window_node_id,
)


def test_populates_the_typed_condition_recording_window_finding_lineage() -> None:
    driver = Neo4jSimulationDriver()
    condition = Condition(condition_id="4", S=800, F=35, D=0.25, source_folder="4_S800_F35_D0.25")
    recording = Recording(recording_id="4/Recording 1", condition_id="4", source_path="/dataset/4_S800_F35_D0.25/Recording 1.csv", checksum="test", schema_status="canonical")
    window = SignalWindow(window_id="4/Recording 1:Vib_Spindle:0:2048", recording_id=recording.recording_id, channel="Vib_Spindle", sample_start=0, sample_end=2048, time_start=0.0, time_end=20.47)
    finding = Finding(finding_id="finding-1", recording_id=recording.recording_id, window_id=window.window_id, finding_type="anomaly", score=4.2, evidence={"source_path": recording.source_path, "channel": window.channel}, model_version="mahalanobis-diagonal-v1")

    populate_provenance_graph(driver, [condition], [recording], [window], [finding])

    condition_edges = driver.get_neighbors(condition_node_id("4"))
    recording_edges = driver.get_neighbors(recording_node_id(recording.recording_id))
    window_edges = driver.get_neighbors(window_node_id(window.window_id))
    assert all(isinstance(edge, GraphEdge) for edge in condition_edges)
    assert [(edge.type, edge.source, edge.target) for edge in condition_edges] == [(CAPTURED_UNDER, condition_node_id("4"), recording_node_id(recording.recording_id))]
    assert any(edge.type == HAS_WINDOW for edge in recording_edges)
    assert any(edge.type == EXHIBITS_PATTERN for edge in window_edges)


def test_similar_window_links_use_the_reserved_typed_edge() -> None:
    driver = Neo4jSimulationDriver()
    first = SignalWindow(window_id="first", recording_id="r1", channel="Current", sample_start=0, sample_end=2)
    second = SignalWindow(window_id="second", recording_id="r2", channel="Current", sample_start=0, sample_end=2)

    link_similar_windows(driver, first, second, similarity=0.98)

    edge = driver.get_neighbors(window_node_id("first"))[0]
    assert edge.type == SIMILAR_TO
    assert edge.properties == {"similarity": 0.98}
