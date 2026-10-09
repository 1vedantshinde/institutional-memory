"""Lightweight rule-based query router.

Classifies each query into a RouteType and returns retrieval weighting hints
that the hybrid_retrieve() function uses to blend vector vs. BM25 results via
weighted RRF. Graph hop depth is advisory and consumed by graph_augment().
"""
import re
from enum import Enum
from typing import Dict


EQUIPMENT_TAG_PATTERN = re.compile(
    r'\b(?:[A-Za-z]{1,5}[- ]?\d{2,4}[A-Za-z]?|[A-Z]{2,4}-\d{2,4})\b'
)

LOOKUP_KEYWORDS = {"what is", "define", "what does", "who is", "describe", "meaning of"}
PROCEDURAL_KEYWORDS = {"procedure", "applies to", "should i", "maintain", "how to", "step", "checklist", "protocol"}


class RouteType(str, Enum):
    LOOKUP = "lookup"          # "What is SOP-402?" — exact tag/keyword match dominant
    PROCEDURAL = "procedural"  # "What procedure applies to Pump-101?" — graph-heavy
    SEMANTIC = "semantic"      # "Explain why the pressure spiked" — vector-dominant


def classify_query(query: str) -> RouteType:
    """Classifies a query string into a RouteType.

    Rules (in priority order):
    1. Has equipment/procedure tag AND a lookup keyword → LOOKUP
    2. Has equipment/procedure tag AND a procedural keyword → PROCEDURAL
    3. Has equipment/procedure tag (no keyword match) → PROCEDURAL (graph will help)
    4. Everything else → SEMANTIC
    """
    q_lower = query.lower()
    has_tag = bool(EQUIPMENT_TAG_PATTERN.search(query))

    if has_tag and any(kw in q_lower for kw in LOOKUP_KEYWORDS):
        return RouteType.LOOKUP
    if has_tag and any(kw in q_lower for kw in PROCEDURAL_KEYWORDS):
        return RouteType.PROCEDURAL
    if has_tag:
        return RouteType.PROCEDURAL
    return RouteType.SEMANTIC


def route_weights(route: RouteType) -> Dict[str, float]:
    """Returns retrieval weighting hints for the given route.

    Keys:
        bm25_weight:   relative weight for keyword (BM25) hits in RRF
        vector_weight: relative weight for vector hits in RRF
        graph_hops:    advisory number of graph hops for graph_augment()
    """
    return {
        RouteType.LOOKUP: {
            "bm25_weight": 0.7,
            "vector_weight": 0.3,
            "graph_hops": 0,
        },
        RouteType.PROCEDURAL: {
            "bm25_weight": 0.3,
            "vector_weight": 0.3,
            "graph_hops": 2,
        },
        RouteType.SEMANTIC: {
            "bm25_weight": 0.2,
            "vector_weight": 0.8,
            "graph_hops": 1,
        },
    }[route]
