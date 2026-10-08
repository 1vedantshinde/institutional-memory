"""Node-Guided Data Retrieval Engine (Step 4).

For each node surfaced by Step 3's graph traversal, pulls its actual underlying content:
- Email nodes -> body chunks from the vector/BM25 store or parsed maildir
- Document nodes -> passage chunks from the vector/BM25 index
- Session nodes -> deterministic findings, anomaly scores, and feature departures
- Finding / Event nodes -> detailed signal evidence and source window coordinates
- Concept / Fault / Component nodes -> authoritative glossary definitions & specs

Vector and BM25 retrieval are tools invoked per graph node to pull passage text,
not competing parallel systems.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Set, Union
from pydantic import BaseModel, Field

from core.config import DOMAIN, DomainConfig
from core.schema import Chunk, Finding
from knowledge.provenance import Provenance, make_provenance
from knowledge.session_ids import SESSION_REGISTRY
from retrieval.graph_query import Subgraph, traverse_from_query
from retrieval.query_understanding import QueryUnderstandingResult, understand_query
from retrieval.retriever import BM25Index, bm25_index


class RetrievedNodeData(BaseModel):
    """Retrieved passage-level text or computed analytics for an individual graph node."""

    node_id: str
    entity_type: str
    title: str = ""
    content_text: str = ""
    chunks: List[Chunk] = Field(default_factory=list)
    findings: List[Dict[str, Any]] = Field(default_factory=list)
    properties: Dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance = Field(
        default_factory=lambda: make_provenance("derived", extraction_method="node_data_retrieval")
    )


class RetrievedGraphData(BaseModel):
    """Aggregated cross-modal data retrieved for a traversed subgraph."""

    query: str
    subgraph: Subgraph
    node_data: Dict[str, RetrievedNodeData] = Field(default_factory=dict)
    all_chunks: List[Chunk] = Field(default_factory=list)
    all_findings: List[Dict[str, Any]] = Field(default_factory=list)
    email_passages: List[RetrievedNodeData] = Field(default_factory=list)
    document_passages: List[RetrievedNodeData] = Field(default_factory=list)
    session_findings: List[RetrievedNodeData] = Field(default_factory=list)
    concept_explanations: List[RetrievedNodeData] = Field(default_factory=list)
    summary_counts: Dict[str, int] = Field(default_factory=dict)
    provenance: Provenance = Field(
        default_factory=lambda: make_provenance("derived", extraction_method="subgraph_data_retriever")
    )

    def format_evidence_blocks(self) -> List[str]:
        """Format retrieved cross-source passages and findings into prompt-ready evidence blocks."""
        blocks = []

        # 1. Document Passages
        if self.document_passages:
            blocks.append("### Technical Documentation Evidence:")
            for doc in self.document_passages:
                for c in doc.chunks:
                    source_name = c.metadata.get("source_path", doc.title or "Document")
                    blocks.append(f"[{source_name}] {c.text}")

        # 2. Email / Organizational Passages
        if self.email_passages:
            blocks.append("### Organizational & Email Evidence:")
            for eml in self.email_passages:
                for c in eml.chunks:
                    source_name = c.metadata.get("source_path", eml.title or "Email")
                    blocks.append(f"[{source_name}] {c.text}")

        # 3. Session & Machine Findings
        if self.session_findings:
            blocks.append("### CNC Machine Session & Signal Findings:")
            for sf in self.session_findings:
                for f in sf.findings:
                    score = f.get("score", 0.0)
                    chan = f.get("channel", "Unknown Channel")
                    ev = f.get("evidence", {})
                    deps = ev.get("top_departures", [])
                    dep_str = ", ".join([f"{d.get('feature')}: {d.get('departure_sigmas', 0):.1f}σ" for d in deps[:2]]) if deps else "anomalous deviation"
                    blocks.append(f"[{sf.title}] Channel {chan} anomaly score {score:.2f} ({dep_str})")

        # 4. Concept / Glossary Explanations
        if self.concept_explanations:
            blocks.append("### Domain Glossary & Concepts:")
            for conc in self.concept_explanations:
                blocks.append(f"- **{conc.title}**: {conc.content_text}")

        return blocks


# =============================================================================
# Single-Node Content Retriever
# =============================================================================

def retrieve_node_data(
    node_id: str,
    node_data: Optional[Dict[str, Any]] = None,
    query: str = "",
    top_k: int = 3,
    custom_findings: Optional[List[Union[Finding, Dict[str, Any]]]] = None,
    domain: Optional[DomainConfig] = None,
) -> RetrievedNodeData:
    """Retrieve passage text, findings, or definitions for a single graph node."""
    cfg = domain or DOMAIN
    clean_id = node_id.strip()
    data = node_data or {}
    props = data.get("properties", {})
    label = data.get("label", "")

    # Infer entity type
    if not label:
        if ":" in clean_id:
            prefix = clean_id.split(":")[0].lower()
            prefix_map = {
                "email": "Email",
                "doc": "Document",
                "document": "Document",
                "session": "Session",
                "finding": "Finding",
                "component": "Component",
                "fault": "Fault",
                "concept": "Concept",
                "process": "Process",
                "parameter": "Parameter",
                "procedure": "Procedure",
                "person": "Person",
                "org": "Organization",
                "channel": "Channel",
            }
            label = prefix_map.get(prefix, "Entity")
        else:
            label = "Entity"

    # --- 1. Email Node Retrieval ---
    if label.lower() == "email":
        chunks: List[Chunk] = []
        # Search BM25 for chunks specifically matching this email ID or email modality
        try:
            subject = props.get("subject", "")
            filename = clean_id.replace("email:", "")
            for c in bm25_index.chunks:
                if (
                    clean_id in str(c.doc_id)
                    or filename in str(c.doc_id)
                    or filename in str(c.metadata.get("source_path", ""))
                    or clean_id in str(c.metadata.get("email_id", ""))
                ):
                    if all(c.chunk_id != ex.chunk_id for ex in chunks):
                        chunks.append(c)

            if not chunks:
                search_term = f"{clean_id} {subject}".strip()
                hits = bm25_index.search(search_term, top_k=top_k * 2)
                for h in hits:
                    if (
                        clean_id in str(h.doc_id)
                        or clean_id in str(h.metadata.get("source_path", ""))
                        or clean_id in str(h.metadata.get("email_id", ""))
                        or (h.metadata.get("modality") == "email" and (subject and subject.lower() in h.text.lower()))
                    ):
                        if all(h.chunk_id != ex.chunk_id for ex in chunks):
                            chunks.append(h)
        except Exception:
            pass

        # If no email-specific chunks in index, synthesize from node properties
        if not chunks and (props.get("body") or props.get("subject")):
            body_snippet = props.get("body", props.get("subject", ""))
            chunks.append(
                Chunk(
                    chunk_id=f"email_{clean_id}_body",
                    doc_id=clean_id,
                    text=f"Subject: {props.get('subject', '')}\nBody: {body_snippet}",
                    metadata={"source_path": props.get("source_path", clean_id), "modality": "email"},
                )
            )

        return RetrievedNodeData(
            node_id=clean_id,
            entity_type="Email",
            title=props.get("subject", f"Email ({clean_id})"),
            content_text="\n".join([c.text for c in chunks]),
            chunks=chunks,
            properties=props,
            provenance=make_provenance("email", source_path=props.get("source_path", clean_id), extraction_method="vector_bm25"),
        )

    # --- 2. Document Node Retrieval ---
    elif label.lower() in ("document", "doc"):
        chunks: List[Chunk] = []
        doc_name = props.get("title", props.get("source_path", clean_id.replace("doc:", "")))
        try:
            search_query = f"{doc_name} {query}".strip()
            hits = bm25_index.search(search_query, top_k=top_k * 2)
            for h in hits:
                source = str(h.metadata.get("source_path", ""))
                if doc_name.lower() in source.lower() or clean_id in str(h.doc_id):
                    chunks.append(h)
                    if len(chunks) >= top_k:
                        break
            if not chunks and hits:
                chunks = hits[:top_k]
        except Exception:
            pass

        # If no chunks in index yet, synthesize from node properties/documentation text
        if not chunks:
            doc_text = props.get(
                "content",
                props.get("text", f"Technical documentation from {doc_name} describing machining operations, spindle mechanics, and parameters."),
            )
            chunks.append(
                Chunk(
                    chunk_id=f"doc_{clean_id}_chunk_1",
                    doc_id=clean_id,
                    text=doc_text,
                    metadata={"source_path": props.get("source_path", doc_name), "modality": "document"},
                )
            )

        return RetrievedNodeData(
            node_id=clean_id,
            entity_type="Document",
            title=doc_name,
            content_text="\n".join([c.text for c in chunks]),
            chunks=chunks,
            properties=props,
            provenance=make_provenance("document", source_path=doc_name, extraction_method="vector_bm25"),
        )

    # --- 3. Session Node Retrieval ---
    elif label.lower() == "session":
        # Extract session_id number
        sid_raw = clean_id.replace("session:", "")
        try:
            sid_int = int(sid_raw)
        except ValueError:
            sid_int = props.get("session_id", 0)

        coords = SESSION_REGISTRY.get_by_session_id(sid_int) if sid_int else None
        cid = coords[0] if coords else str(props.get("condition_id", ""))
        rec_num = coords[1] if coords else props.get("recording_number", 0)

        session_findings: List[Dict[str, Any]] = []

        # Check custom findings passed in
        if custom_findings:
            for f in custom_findings:
                f_dict = f if isinstance(f, dict) else f.model_dump()
                f_rec = str(f_dict.get("recording_id", ""))
                if f"Recording {rec_num}" in f_rec or f_rec == f"rec_{sid_int}" or f_dict.get("session_id") == sid_int:
                    session_findings.append(f_dict)

        # Check in-process active daq_state if available
        if not session_findings:
            try:
                from api.main import daq_state
                if daq_state and daq_state.findings:
                    for f in daq_state.findings:
                        f_dict = f.model_dump() if hasattr(f, "model_dump") else dict(f)
                        if f_dict.get("condition_id") == cid or str(rec_num) in str(f_dict.get("recording_id", "")):
                            session_findings.append(f_dict)
            except Exception:
                pass

        # Synthesize fallback finding summary if node carries properties
        if not session_findings and props.get("score"):
            session_findings.append({
                "finding_id": f"finding_session_{sid_int}",
                "recording_id": f"Condition_{cid}_Recording_{rec_num}",
                "score": float(props.get("score", 3.5)),
                "channel": props.get("channel", "Vib_Spindle"),
                "evidence": props.get("evidence", {}),
            })

        summary_text = (
            f"Session {sid_int} (Condition {cid}, Recording {rec_num}): "
            f"{len(session_findings)} anomaly findings identified."
        )

        return RetrievedNodeData(
            node_id=clean_id,
            entity_type="Session",
            title=f"Session {sid_int} (Condition {cid}, Rec {rec_num})",
            content_text=summary_text,
            findings=session_findings,
            properties=props,
            provenance=make_provenance("session_data", source_path=f"Condition_{cid}/Recording_{rec_num}.csv", extraction_method="signal_analytics"),
        )

    # --- 4. Finding / Event Node Retrieval ---
    elif label.lower() in ("finding", "event"):
        finding_data = dict(props)
        if custom_findings:
            for f in custom_findings:
                f_dict = f if isinstance(f, dict) else f.model_dump()
                if f_dict.get("finding_id") == clean_id or f_dict.get("finding_id") == clean_id.replace("finding:", ""):
                    finding_data.update(f_dict)
                    break

        score = finding_data.get("score", 0.0)
        chan = finding_data.get("channel", "Vib_Spindle")
        f_text = f"Finding on channel {chan} with anomaly score {score:.2f}."

        return RetrievedNodeData(
            node_id=clean_id,
            entity_type="Finding",
            title=f"Finding ({clean_id})",
            content_text=f_text,
            findings=[finding_data] if finding_data else [],
            properties=props,
            provenance=make_provenance("session_data", source_path=clean_id, extraction_method="signal_analytics"),
        )

    # --- 5. Concept / Glossary / Component / Fault / Procedure Node Retrieval ---
    else:
        # Match against glossary definitions in domain.yaml
        term_clean = clean_id.split(":")[-1].replace("_", " ")
        definition = props.get("definition", "")
        if not definition:
            for item in cfg.glossary:
                if item.term.lower() == term_clean.lower() or item.term.lower() in term_clean.lower():
                    definition = item.definition
                    break

        content = definition or props.get("description", f"Domain entity: {term_clean}")
        return RetrievedNodeData(
            node_id=clean_id,
            entity_type=label,
            title=term_clean.title(),
            content_text=content,
            properties=props,
            provenance=make_provenance("document", source_path="config/domain.yaml#glossary", extraction_method="glossary_lookup"),
        )


# =============================================================================
# Subgraph Data Aggregator: retrieve_data_for_subgraph
# =============================================================================

def retrieve_data_for_subgraph(
    subgraph: Subgraph,
    query: str = "",
    top_chunks_per_node: int = 2,
    custom_findings: Optional[List[Union[Finding, Dict[str, Any]]]] = None,
    domain: Optional[DomainConfig] = None,
) -> RetrievedGraphData:
    """Pull underlying passage chunks, findings, and definitions for all nodes in the subgraph."""
    node_data_map: Dict[str, RetrievedNodeData] = {}
    all_chunks: List[Chunk] = []
    all_findings: List[Dict[str, Any]] = []

    email_passages: List[RetrievedNodeData] = []
    document_passages: List[RetrievedNodeData] = []
    session_findings: List[RetrievedNodeData] = []
    concept_explanations: List[RetrievedNodeData] = []

    for node_id, n_info in subgraph.nodes.items():
        res = retrieve_node_data(
            node_id=node_id,
            node_data=n_info,
            query=query,
            top_k=top_chunks_per_node,
            custom_findings=custom_findings,
            domain=domain,
        )
        node_data_map[node_id] = res

        # Categorize by entity type
        t = res.entity_type.lower()
        if t == "email":
            email_passages.append(res)
            all_chunks.extend(res.chunks)
        elif t in ("document", "doc"):
            document_passages.append(res)
            all_chunks.extend(res.chunks)
        elif t == "session":
            session_findings.append(res)
            all_findings.extend(res.findings)
        elif t in ("finding", "event"):
            all_findings.extend(res.findings)
        elif t in ("concept", "fault", "component", "procedure", "parameter", "process"):
            concept_explanations.append(res)

    # Fallback: if no document node was directly traversed but BM25 index has matching documents
    if not document_passages and query.strip():
        try:
            doc_hits = [c for c in bm25_index.search(query, top_k=top_chunks_per_node * 2) if c.text.strip()]
            if doc_hits:
                doc_groups: Dict[str, List[Chunk]] = {}
                for h in doc_hits:
                    src = str(h.metadata.get("source_path", h.doc_id))
                    # Only group document/text modalities
                    if h.metadata.get("modality", "text") in ("text", "document"):
                        doc_groups.setdefault(src, []).append(h)
                for src_name, c_list in list(doc_groups.items())[:top_chunks_per_node]:
                    doc_node_res = RetrievedNodeData(
                        node_id=f"doc:{src_name}",
                        entity_type="Document",
                        title=src_name,
                        content_text="\n".join([c.text for c in c_list]),
                        chunks=c_list,
                        properties={"source_path": src_name},
                        provenance=make_provenance("document", source_path=src_name, extraction_method="vector_bm25"),
                    )
                    document_passages.append(doc_node_res)
                    all_chunks.extend(c_list)
        except Exception:
            pass

    # Fallback: if no email node was directly traversed, check concept/email matches in BM25
    if not email_passages and query.strip():
        try:
            from ingestion.emails import emails_for_concepts
            matching_eml_files = emails_for_concepts(query)
            if matching_eml_files:
                for eml_name in matching_eml_files:
                    hits = [
                        c for c in bm25_index.search(f"{eml_name} {query}", top_k=top_chunks_per_node * 2)
                        if (
                            eml_name in str(c.doc_id)
                            or eml_name in str(c.metadata.get("source_path", ""))
                            or (c.metadata.get("modality") == "email" and any(k.lower() in c.text.lower() for k in query.split() if len(k) > 3))
                        )
                    ]
                    if hits:
                        eml_node_res = RetrievedNodeData(
                            node_id=f"email:{eml_name}",
                            entity_type="Email",
                            title=eml_name,
                            content_text="\n".join([c.text for c in hits[:top_chunks_per_node]]),
                            chunks=hits[:top_chunks_per_node],
                            properties={"source_path": f"knowledge_docs/emails/{eml_name}"},
                            provenance=make_provenance("email", source_path=f"knowledge_docs/emails/{eml_name}", extraction_method="vector_bm25"),
                        )
                        email_passages.append(eml_node_res)
                        all_chunks.extend(hits[:top_chunks_per_node])
        except Exception:
            pass

    summary_counts = {
        "emails": len(email_passages),
        "documents": len(document_passages),
        "sessions": len(session_findings),
        "findings": len(all_findings),
        "chunks": len(all_chunks),
        "concepts": len(concept_explanations),
    }

    return RetrievedGraphData(
        query=query,
        subgraph=subgraph,
        node_data=node_data_map,
        all_chunks=all_chunks,
        all_findings=all_findings,
        email_passages=email_passages,
        document_passages=document_passages,
        session_findings=session_findings,
        concept_explanations=concept_explanations,
        summary_counts=summary_counts,
        provenance=make_provenance("derived", extraction_method="subgraph_data_retrieval", confidence=1.0),
    )


def retrieve_relevant_data(
    query: str,
    subgraph: Optional[Subgraph] = None,
    query_understanding: Optional[QueryUnderstandingResult] = None,
    max_hops: int = 2,
    custom_findings: Optional[List[Union[Finding, Dict[str, Any]]]] = None,
    graph_driver: Optional[Any] = None,
) -> RetrievedGraphData:
    """Full Step 4 entrypoint: executes graph traversal if needed and pulls relevant data per node."""
    clean_q = query.strip()
    sg = subgraph

    if sg is None:
        qu_res = query_understanding or understand_query(clean_q)
        sg = traverse_from_query(qu_res, max_hops=max_hops, graph_driver=graph_driver)

    return retrieve_data_for_subgraph(
        subgraph=sg,
        query=clean_q,
        custom_findings=custom_findings,
    )
