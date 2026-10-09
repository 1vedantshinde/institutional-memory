"""Standard provenance model and helpers for all knowledge graph entities, relations, and query extractions."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional
from pydantic import BaseModel, Field


class Provenance(BaseModel):
    """Explicit provenance metadata carried by every graph node, edge, and query extraction."""

    source_type: Literal["email", "document", "session_data", "query", "derived"]
    source_path: str = ""  # .eml path / PDF path / CSV path / user query string
    extracted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    extraction_method: str = "rule_based"  # "spacy_ner" | "llm_extraction" | "rule_based" | "signal_analytics" | "query_parser" | "derived"
    confidence: Optional[float] = None  # Probabilistic for NER/LLM, deterministic (1.0) for signal/header

    def to_properties(self) -> Dict[str, Any]:
        """Serialize provenance fields for graph store node/edge property dictionaries."""
        return {
            "source_type": self.source_type,
            "source_path": self.source_path,
            "extracted_at": self.extracted_at.isoformat(),
            "extraction_method": self.extraction_method,
            "confidence": self.confidence,
        }


def make_provenance(
    source_type: Literal["email", "document", "session_data", "query", "derived"],
    source_path: str = "",
    extraction_method: str = "rule_based",
    confidence: Optional[float] = None,
) -> Provenance:
    """Helper factory for constructing typed Provenance records."""
    return Provenance(
        source_type=source_type,
        source_path=source_path,
        extracted_at=datetime.now(timezone.utc),
        extraction_method=extraction_method,
        confidence=confidence,
    )
