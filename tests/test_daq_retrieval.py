"""Tests for exact DAQ metadata, numeric similarity, and graph-context fusion."""

from __future__ import annotations

import pytest

from core.schema import Condition, Recording, SignalWindow
from knowledge.graph_store import Neo4jSimulationDriver
from knowledge.ontology import HAS_WINDOW, populate_provenance_graph
from retrieval.feature_store import FeatureStore, FeatureStoreError
from retrieval.metadata_index import MetadataIndex
from retrieval.retriever import DAQRetriever


def _fixtures():
    conditions = [
        Condition(condition_id="4", S=800, F=35, D=0.25, source_folder="4_S800_F35_D0.25"),
        Condition(condition_id="5", S=900, F=35, D=0.25, source_folder="5_S900_F35_D0.25"),
    ]
    records = [
        Recording(recording_id="4/one", condition_id="4", source_path="/dataset/4/one.csv", checksum="a", schema_status="canonical"),
        Recording(recording_id="4/bad", condition_id="4", source_path="/dataset/4/bad.csv", checksum="b", schema_status="quarantined"),
        Recording(recording_id="5/one", condition_id="5", source_path="/dataset/5/one.csv", checksum="c", schema_status="canonical"),
    ]
    windows = [
        SignalWindow(window_id="w4-near", recording_id="4/one", channel="Vib_Spindle", sample_start=0, sample_end=10, feature_vector=[1.0, 0.0]),
        SignalWindow(window_id="w4-far", recording_id="4/one", channel="Vib_Spindle", sample_start=10, sample_end=20, feature_vector=[0.0, 1.0]),
        SignalWindow(window_id="w4-rejected", recording_id="4/bad", channel="Vib_Spindle", sample_start=0, sample_end=10, feature_vector=[1.0, 0.0]),
        SignalWindow(window_id="w5", recording_id="5/one", channel="Current", sample_start=0, sample_end=10, feature_vector=[1.0, 0.0]),
    ]
    return conditions, records, windows


def test_metadata_filter_then_feature_similarity_then_typed_graph_context() -> None:
    conditions, records, windows = _fixtures()
    index = MetadataIndex(conditions, records, windows)
    store = FeatureStore()
    store.insert(windows)
    driver = Neo4jSimulationDriver()
    populate_provenance_graph(driver, conditions, records, windows, [])

    results = DAQRetriever(index, store, driver).query(
        [1.0, 0.0], filters={"S": 800, "channel": "Vib_Spindle"}, top_k=2
    )

    assert [result.window.window.window_id for result in results] == ["w4-near", "w4-far"]
    assert results[0].similarity_score == pytest.approx(1.0)
    assert all(result.window.recording.schema_status == "canonical" for result in results)
    assert any(edge.type == HAS_WINDOW for edge in results[0].graph_context)


def test_feature_store_rejects_dimension_mismatches() -> None:
    _, _, windows = _fixtures()
    store = FeatureStore()
    store.insert(windows[:1])

    with pytest.raises(FeatureStoreError, match="feature_vector_dimension_mismatch"):
        store.similarity_search([1.0, 2.0, 3.0])
