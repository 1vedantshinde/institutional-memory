"""Project knowledge documents (Tier-1 explainer PDFs).

Short PDFs that explain the machine, the quality gate, how findings are
computed, and the vocabulary. They are ingested through the normal document
pipeline (parse → chunk → embed → vector store) so /chat can answer general
questions from them, and each is linked to the concepts it explains with
``Document -[:DOCUMENTS]-> Concept`` edges.

They live in ``knowledge_docs/pdfs/``, next to ``dataset/`` rather than inside
it, and contain explanations only — no measurements from individual runs.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

KNOWLEDGE_DOCS_ROOT = Path(__file__).resolve().parents[1] / "knowledge_docs" / "pdfs"

# Hand-written seed list of the concepts each document explains. Extend it as
# real questions reveal concepts that aren't covered.
CONCEPTS_PER_DOC: dict[str, list[str]] = {
    "machine_fact_sheet.pdf": [
        "condition", "spindle speed", "feed rate", "depth of cut",
        "latin square", "raw voltage", "sampling rate",
    ],
    "quarantine_policy_explainer.pdf": ["quarantine", "canonical schema", "null bytes"],
    "finding_explainer.pdf": ["finding", "baseline", "window", "anomaly score", "citation"],
    "glossary.pdf": [
        "rms", "kurtosis", "crest factor", "skewness",
        "spectral band energy", "spectral centroid", "mahalanobis distance",
    ],
}

# filename -> number of chunks indexed, filled by ingest_knowledge_docs()
_ingested: dict[str, int] = {}


def knowledge_doc_ids() -> set[str]:
    """doc_ids of ingested knowledge documents (as assigned by the PDF parser)."""
    from core.schema import make_doc_id

    return {make_doc_id("text", name) for name in _ingested}


def ingested_documents() -> dict[str, int]:
    return dict(_ingested)


def ingest_knowledge_docs(pipeline: Any, root: Path | str = KNOWLEDGE_DOCS_ROOT) -> dict[str, Any]:
    """Ingest every PDF under ``root`` and write its DOCUMENTS edges.

    Re-running is safe: chunk IDs are stable, so the vector store overwrites
    rather than duplicates, and graph MERGE semantics dedupe nodes/edges.
    """
    root = Path(root)
    results: dict[str, Any] = {"root": str(root), "documents": {}, "failed": {}}
    if not root.is_dir():
        results["failed"]["<root>"] = f"Folder not found: {root}"
        return results

    for path in sorted(root.glob("*.pdf")):
        try:
            chunks = pipeline.ingest_file(filename=path.name, content_bytes=path.read_bytes())
        except Exception as exc:  # one bad file must not stop the others
            results["failed"][path.name] = str(exc)
            continue
        if not chunks:
            # Zero chunks means no text was extracted; don't pretend it's searchable
            results["failed"][path.name] = "No extractable text (0 chunks)"
            continue
        _ingested[path.name] = len(chunks)
        results["documents"][path.name] = len(chunks)
        _link_concepts(pipeline, path.name)
    return results


def _link_concepts(pipeline: Any, filename: str) -> None:
    concepts = CONCEPTS_PER_DOC.get(filename, [])
    nodes = [{"id": filename, "name": filename, "type": "Document", "properties": {"path": f"knowledge_docs/pdfs/{filename}"}}]
    nodes += [{"id": c, "name": c, "type": "Concept"} for c in concepts]
    edges = [{"source_id": filename, "target_id": c, "type": "DOCUMENTS"} for c in concepts]
    pipeline.ingest_graph_elements(nodes, edges)


def documents_for_concepts(question: str) -> list[str]:
    """Knowledge documents linked (via DOCUMENTS edges) to concepts named in the question."""
    from knowledge.graph_store import neo4j

    # Same normalisation as the concept names: lowercase words, punctuation dropped
    q = " " + " ".join(re.findall(r"[a-z0-9]+", question.lower())) + " "
    docs: list[str] = []
    for filename in _ingested:
        for edge in neo4j.get_neighbors(filename):
            if edge.type == "DOCUMENTS" and f" {edge.target} " in q and filename not in docs:
                docs.append(filename)
    return docs


def knowledge_docs_enabled() -> bool:
    return os.environ.get("KNOWLEDGE_DOCS_ENABLED", "1") != "0"
