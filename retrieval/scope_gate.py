"""Strict CNC Scope Gate (Step 2).

Enforces strict domain boundaries:
1. Entity-match gate (zero LLM cost): verifies matches against Component, Process, Parameter,
   Procedure, Fault, Concept, Session, Channel, Event, or known Person/Organization.
2. Fallback semantic check: for queries with no exact entity match, checks domain heuristics
   or issues a cheap 1-token classification call.
3. Fixed decline: out-of-scope questions return IN_SCOPE_DECLARE verbatim.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field

from core.registry import llm_registry
from knowledge.provenance import Provenance, make_provenance
from retrieval.query_understanding import (
    ExtractedEntity,
    QueryIntent,
    QueryUnderstandingResult,
    understand_query,
)

IN_SCOPE_DECLARE = (
    "This system answers questions about the CNC machine, its operation, "
    "documentation, sessions, and associated knowledge."
)

# Semantic domain keywords for high-precision heuristic fallback
_CNC_DOMAIN_KEYWORDS = {
    "cnc", "machine", "machining", "milling", "lathe", "spindle", "bearing", "bearings",
    "vibration", "vibrations", "sensor", "sensors", "accelerometer", "dynamometer",
    "load cell", "loadcell", "current", "motor", "tool", "tools", "cutter", "tool wear",
    "toolwear", "flank wear", "chatter", "feed rate", "feedrate", "spindle speed", "depth of cut",
    "sampling rate", "mahalanobis", "kurtosis", "crest factor", "rms", "skewness",
    "anomaly", "anomalies", "finding", "findings", "quarantine", "canonical",
    "condition", "session", "recording", "readings", "baseline", "maintenance",
    "operating history", "dataset", "mondragon", "kistler", "deckel", "vance",
    "chen", "rodriguez", "rivera", "torres", "bradley", "jenkins"
}


class ScopeGateResult(BaseModel):
    """Result of Step 2 scope validation."""

    in_scope: bool
    decline_message: Optional[str] = None
    reason: str = ""
    validation_method: str = "entity_match"  # "entity_match" | "domain_heuristic" | "llm_semantic_check" | "declined"
    query_understanding: Optional[QueryUnderstandingResult] = None
    provenance: Provenance = Field(
        default_factory=lambda: make_provenance("query", extraction_method="scope_gate")
    )


def _call_llm_classifier(question: str) -> Optional[bool]:
    """Fallback cheap classification call: 'is this question about CNC/machining/data/people?'"""
    prompt = (
        f"You are a strict binary domain classifier.\n"
        f"Domain: CNC machining, milling machines, sensor signals (vibration, load cells, current), "
        f"machine documentation, session recordings, maintenance procedures, and related personnel.\n\n"
        f"Question: \"{question}\"\n\n"
        f"Is this question plausibly about this domain or its associated organizational communications?\n"
        f"Answer ONLY with 'YES' or 'NO'."
    )
    # Try getting the configured LLM provider
    for provider_name in ["gemini", "openai", "anthropic", "mock"]:
        try:
            llm_cls = llm_registry.get(provider_name)
            llm = llm_cls()
            response = llm.generate(prompt=prompt, system_prompt="You are a binary domain classifier.")
            clean_resp = response.strip().upper()
            if "YES" in clean_resp:
                return True
            if "NO" in clean_resp:
                return False
        except Exception:
            continue
    return None


def validate_cnc_context(
    question: str,
    graph_entity_matches: Optional[Union[List[ExtractedEntity], List[Any]]] = None,
    query_understanding: Optional[QueryUnderstandingResult] = None,
    use_llm_fallback: bool = True,
    domain: Optional[Any] = None,
    llm_provider: Optional[Any] = None,
) -> bool:
    """True if the question plausibly concerns the machine itself, its components/processes/

    parameters, its documentation, a session/recording, a sensor channel, or a person/email
    discussing any of the above. False otherwise.
    """
    result = evaluate_scope_gate(
        question=question,
        graph_entity_matches=graph_entity_matches,
        query_understanding=query_understanding,
        use_llm_fallback=use_llm_fallback,
        domain=domain,
        llm_provider=llm_provider,
    )
    return result.in_scope


def evaluate_scope_gate(
    question: str,
    graph_entity_matches: Optional[Union[List[ExtractedEntity], List[Any]]] = None,
    query_understanding: Optional[QueryUnderstandingResult] = None,
    use_llm_fallback: bool = True,
    domain: Optional[Any] = None,
    llm_provider: Optional[Any] = None,
) -> ScopeGateResult:
    """Execute Step 2 strict CNC-scope gate check.

    Returns ScopeGateResult. When in_scope is False, decline_message contains
    IN_SCOPE_DECLARE verbatim.
    """
    clean_q = question.strip()
    if not clean_q:
        return ScopeGateResult(
            in_scope=False,
            decline_message=IN_SCOPE_DECLARE,
            reason="empty_query",
            validation_method="declined",
        )

    # 1. Get or compute QueryUnderstandingResult
    qu_res = query_understanding
    if qu_res is None:
        qu_res = understand_query(clean_q)

    # 2. Gate 1: Entity-Match Gate (Zero LLM cost)
    # Check explicitly passed entity matches or query understanding entities
    entities = list(qu_res.entities)
    if graph_entity_matches:
        for match in graph_entity_matches:
            if match not in entities:
                entities.append(match)

    # Valid domain entity types that grant immediate in-scope admission
    valid_domain_types = {
        "component", "session", "condition", "channel", "fault",
        "process", "parameter", "procedure", "concept", "event",
        "document"
    }
    machine_person_keys = {"vance", "rodriguez", "chen", "rivera", "torres", "bradley", "jenkins"}
    machine_org_keys = {"machining", "mondragon", "kistler", "deckel", "cnc_lab", "plant", "facility"}

    matching_domain_entities = []
    for e in entities:
        t = (getattr(e, "entity_type", "") or "").lower()
        cid = (getattr(e, "canonical_id", "") or "").lower()
        if t in valid_domain_types:
            matching_domain_entities.append(e)
        elif t == "person":
            if any(k in cid for k in machine_person_keys):
                matching_domain_entities.append(e)
        elif t == "organization":
            if any(k in cid for k in machine_org_keys):
                matching_domain_entities.append(e)

    # If query intent is already explicitly OUT_OF_SCOPE and zero domain entities matched
    if qu_res.intent == QueryIntent.OUT_OF_SCOPE and not matching_domain_entities:
        return ScopeGateResult(
            in_scope=False,
            decline_message=IN_SCOPE_DECLARE,
            reason="out_of_domain_intent",
            validation_method="declined",
            query_understanding=qu_res,
        )

    if len(matching_domain_entities) > 0:
        return ScopeGateResult(
            in_scope=True,
            decline_message=None,
            reason=f"matched_{len(matching_domain_entities)}_domain_entities",
            validation_method="entity_match",
            query_understanding=qu_res,
        )

    # 3. Gate 2: Domain Heuristic Keyword Matcher
    q_words = set(re.findall(r"\b[a-z_]+\b", clean_q.lower()))
    keyword_overlap = q_words.intersection(_CNC_DOMAIN_KEYWORDS)
    if keyword_overlap:
        return ScopeGateResult(
            in_scope=True,
            decline_message=None,
            reason=f"matched_domain_keywords:{','.join(sorted(keyword_overlap))}",
            validation_method="domain_heuristic",
            query_understanding=qu_res,
        )

    # 4. Gate 3: Fallback Semantic LLM Classifier (if enabled)
    if use_llm_fallback:
        llm_decision = _call_llm_classifier(clean_q)
        if llm_decision is True:
            return ScopeGateResult(
                in_scope=True,
                decline_message=None,
                reason="llm_classified_in_scope",
                validation_method="llm_semantic_check",
                query_understanding=qu_res,
            )
        elif llm_decision is False:
            return ScopeGateResult(
                in_scope=False,
                decline_message=IN_SCOPE_DECLARE,
                reason="llm_classified_out_of_scope",
                validation_method="declined",
                query_understanding=qu_res,
            )

    # 5. Fixed Decline
    return ScopeGateResult(
        in_scope=False,
        decline_message=IN_SCOPE_DECLARE,
        reason="no_domain_entities_or_context",
        validation_method="declined",
        query_understanding=qu_res,
    )


# Convenient alias matching standard naming conventions
validate_cnc_scope = evaluate_scope_gate

