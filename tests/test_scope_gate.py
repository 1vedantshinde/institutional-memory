"""Tests for Step 2 — Validate CNC Context (Scope Gate)."""

from __future__ import annotations

import pytest

from retrieval.query_understanding import understand_query
from retrieval.scope_gate import (
    IN_SCOPE_DECLARE,
    ScopeGateResult,
    evaluate_scope_gate,
    validate_cnc_context,
)


@pytest.mark.parametrize("in_scope_query", [
    "Was the issue in session 42 related to the problem discussed in the emails?",
    "Check spindle vibration for tool wear and bearing fault.",
    "What is the procedure for spindle bearing replacement?",
    "Explain Mahalanobis distance and crest factor in signal analysis.",
    "Did Kenneth Lay or Jeffrey Skilling discuss machine maintenance?",
    "Show anomalous readings on channel Vib_Spindle under condition 5.",
    "Tell me about this machine's maintenance history.",
    "What is the sampling rate measured for session 12?",
    "Why was recording 4 quarantined?",
])
def test_in_scope_queries_pass_gate(in_scope_query: str) -> None:
    """Validate that in-scope CNC and organizational queries pass the scope gate."""
    # Test boolean helper
    is_valid = validate_cnc_context(in_scope_query)
    assert is_valid is True

    # Test detailed evaluator
    result = evaluate_scope_gate(in_scope_query)
    assert result.in_scope is True
    assert result.decline_message is None
    assert result.validation_method in ("entity_match", "domain_heuristic", "llm_semantic_check")
    assert result.provenance.source_type == "query"


@pytest.mark.parametrize("out_of_scope_query", [
    "What is the capital of France?",
    "Write a poem about the ocean and the sunrise.",
    "How do I bake chocolate chip cookies at home?",
    "What is the current stock price of Apple and Microsoft?",
    "Who won the 1998 FIFA World Cup in soccer?",
    "Can you help me solve this algebra equation: 2x + 5 = 15?",
])
def test_out_of_scope_queries_declined_with_exact_declaration(out_of_scope_query: str) -> None:
    """Validate that out-of-scope queries are rejected immediately with IN_SCOPE_DECLARE verbatim."""
    # Test boolean helper
    is_valid = validate_cnc_context(out_of_scope_query)
    assert is_valid is False

    # Test detailed evaluator
    result = evaluate_scope_gate(out_of_scope_query)
    assert result.in_scope is False
    assert result.decline_message == IN_SCOPE_DECLARE
    assert result.validation_method == "declined"
    assert result.decline_message == (
        "This system answers questions about the CNC machine, its operation, "
        "documentation, sessions, and associated knowledge."
    )


def test_empty_query_declined() -> None:
    """Validate empty or whitespace query behavior."""
    assert validate_cnc_context("") is False
    result = evaluate_scope_gate("   ")
    assert result.in_scope is False
    assert result.decline_message == IN_SCOPE_DECLARE


def test_scope_gate_reuses_existing_query_understanding() -> None:
    """Validate that Step 2 consumes Step 1's QueryUnderstandingResult without duplicate parsing."""
    query = "Check session 42 for spindle anomalies"
    qu_res = understand_query(query)
    assert qu_res.session_id == 42

    result = evaluate_scope_gate(query, query_understanding=qu_res)
    assert result.in_scope is True
    assert result.query_understanding is qu_res
