"""Tests for Step 1 — Query Intent & Entity Understanding against Unified Ontology."""

from __future__ import annotations

import pytest

from retrieval.query_understanding import (
    ExtractedEntity,
    QueryIntent,
    QueryUnderstandingResult,
    understand_query,
)
from knowledge.session_ids import resolve_session_reference, SessionReference


def test_cross_source_query_understanding() -> None:
    """Validate query asking to connect session 42 with email discussions."""
    query = "Was the issue in session 42 related to the problem discussed in the emails?"
    res = understand_query(query)

    assert res.intent == QueryIntent.CROSS_SOURCE_CORRELATION
    assert res.is_cnc_candidate is True
    assert res.session_id == 42
    assert "session:42" in res.seed_node_ids
    assert any(e.entity_type == "Fault" for e in res.entities)  # "issue" / "problem"
    assert res.provenance.source_type == "query"
    assert res.provenance.extraction_method == "query_understanding"


def test_component_and_fault_extraction() -> None:
    """Validate extraction of component ('spindle'), fault ('bearing fault' / 'tool wear')."""
    query = "Did the spindle show signs of bearing fault and severe tool wear?"
    res = understand_query(query)

    component_entities = res.get_entities_by_type("Component")
    fault_entities = res.get_entities_by_type("Fault")

    assert any(e.canonical_id == "component:spindle" for e in component_entities)
    assert any(e.canonical_id == "fault:bearing_fault" for e in fault_entities)
    assert any(e.canonical_id == "fault:tool_wear" for e in fault_entities)
    assert res.is_cnc_candidate is True
    assert "component:spindle" in res.seed_node_ids
    assert "fault:bearing_fault" in res.seed_node_ids


def test_session_resolving_and_addressing() -> None:
    """Validate session addressing across varied natural language syntaxes."""
    # Test session 42
    r1 = understand_query("What happened in session 42 on Vib_Spindle?")
    assert r1.session_id == 42
    assert r1.channel == "Vib_Spindle"
    assert "session:42" in r1.seed_node_ids
    assert "channel:Vib_Spindle" in r1.seed_node_ids

    # Test condition + recording
    r2 = understand_query("Check Condition 5 Recording 1 for vibration anomalies.")
    assert r2.condition_id == "5"
    assert r2.is_cnc_candidate is True
    assert any(e.entity_type == "Condition" for e in r2.entities)

    # Test "Recording 2 in Condition 3"
    r3 = understand_query("Show me Recording 2 in Condition 3")
    assert r3.condition_id == "3"
    assert r3.is_cnc_candidate is True


def test_channel_normalization() -> None:
    """Validate channel extraction and canonical normalization."""
    # "spindle vibration" -> Vib_Spindle
    r1 = understand_query("Did spindle vibration spike above baseline?")
    assert r1.channel == "Vib_Spindle"
    assert any(e.canonical_id == "channel:Vib_Spindle" for e in r1.entities)

    # "table vibration" -> Vib_Table
    r2 = understand_query("Analyze table vibration during facing")
    assert r2.channel == "Vib_Table"
    assert any(e.canonical_id == "channel:Vib_Table" for e in r2.entities)

    # "motor current" -> Current
    r3 = understand_query("Was motor current abnormal?")
    assert r3.channel == "Current"
    assert any(e.canonical_id == "channel:Current" for e in r3.entities)

    # "x load cell" -> X_Load_Cell
    r4 = understand_query("Show x load cell readings")
    assert r4.channel == "X_Load_Cell"
    assert any(e.canonical_id == "channel:X_Load_Cell" for e in r4.entities)


def test_person_and_organization_extraction() -> None:
    """Validate extraction of people and organizations from queries."""
    query = "Did Skilling or Kenneth Lay send any emails to Enron regarding the CNC lab?"
    res = understand_query(query)

    person_entities = res.get_entities_by_type("Person")
    org_entities = res.get_entities_by_type("Organization")

    assert any("skilling" in e.canonical_id for e in person_entities)
    assert any("lay" in e.canonical_id for e in person_entities)
    assert any("enron" in e.canonical_id for e in org_entities)
    assert any("cnc_lab" in e.canonical_id for e in org_entities)
    assert res.is_cnc_candidate is True


def test_process_parameter_and_procedure_extraction() -> None:
    """Validate extraction of cutting processes, machining parameters, and procedures."""
    query = "What feed rate and spindle speed are required during facing for spindle bearing replacement?"
    res = understand_query(query)

    process_entities = res.get_entities_by_type("Process")
    param_entities = res.get_entities_by_type("Parameter")
    proc_entities = res.get_entities_by_type("Procedure")

    assert any(e.canonical_id == "process:facing" for e in process_entities)
    assert any(e.canonical_id == "parameter:feed_rate" for e in param_entities)
    assert any(e.canonical_id == "parameter:spindle_speed" for e in param_entities)
    assert any(e.canonical_id == "procedure:spindle_bearing_replacement" for e in proc_entities)


def test_glossary_concept_extraction() -> None:
    """Validate extraction of glossary terms from domain.yaml."""
    query = "Explain Mahalanobis distance, kurtosis, and crest factor."
    res = understand_query(query)

    concept_entities = res.get_entities_by_type("Concept")
    assert any("mahalanobis" in e.canonical_id for e in concept_entities)
    assert any("kurtosis" in e.canonical_id for e in concept_entities)
    assert any("crest_factor" in e.canonical_id for e in concept_entities)
    assert res.intent == QueryIntent.GENERAL_KNOWLEDGE


def test_out_of_scope_query_detection() -> None:
    """Validate out-of-scope query classification and gate flag."""
    query = "What is the capital of France and how to make a chocolate cake?"
    res = understand_query(query)

    assert res.is_cnc_candidate is False
    assert res.intent == QueryIntent.OUT_OF_SCOPE
    assert len(res.seed_node_ids) == 0


def test_date_range_extraction() -> None:
    """Validate ISO and month-year date extraction."""
    query = "Did any tool wear incidents occur on 2001-05-12 or during May 2001?"
    res = understand_query(query)

    date_entities = res.get_entities_by_type("DateRange")
    assert len(date_entities) >= 1
    assert res.temporal_scope is not None
    assert res.temporal_scope.get("start") == "2001-05-12"
