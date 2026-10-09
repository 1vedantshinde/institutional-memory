"""Prompt builder module.

Handles structural rendering of LLM prompt payloads backed by the loaded DOMAIN configuration.
"""
import re
from typing import List, Dict, Any, Optional, Tuple
import core.config
from core.schema import Chunk, Condition, Finding
from knowledge.graph_store import GraphEdge

def build_system_prompt(domain: Any = None) -> str:
    """Renders the system prompt template loaded from domain metadata."""
    if domain is None:
        domain = core.config.DOMAIN
        
    if isinstance(domain, dict):
        return domain.get("system_prompt_template", "").format(
            domain_name=domain.get("domain_name", "Generic Industrial Plant")
        )
    return domain.system_prompt_template.format(domain_name=domain.domain_name)

def _glossary_items(domain: Any) -> List[Tuple[str, str]]:
    """(term, definition) pairs from a DomainConfig or plain dict; accepts
    either ``definition`` or ``meaning`` as the key."""
    items = domain.get("glossary", []) if isinstance(domain, dict) else getattr(domain, "glossary", [])
    pairs = []
    for item in items or []:
        get = item.get if isinstance(item, dict) else (lambda k, d="", _i=item: getattr(_i, k, d))
        term = (get("term", "") or "").strip()
        definition = (get("definition", "") or get("meaning", "") or "").strip()
        if term and definition:
            pairs.append((term, definition))
    return pairs


def match_glossary(text: str, domain: Any = None) -> List[Tuple[str, str]]:
    """Glossary entries whose term appears in ``text``.

    Case-insensitive whole-word match that tolerates punctuation ("RMS?"),
    hyphen/space variants ("Latin square" / "Latin-square") and a plural "s".
    """
    if domain is None:
        domain = core.config.DOMAIN
    matches = []
    for term, definition in _glossary_items(domain):
        words = [re.escape(w) for w in re.split(r"[\s\-]+", term) if w]
        pattern = r"(?<![A-Za-z0-9])" + r"[\s\-]+".join(words) + r"(?:e?s)?(?![A-Za-z0-9])"
        if re.search(pattern, text, re.IGNORECASE):
            matches.append((term, definition))
    return matches


def format_glossary_block(matches: List[Tuple[str, str]], heading: str = "Domain Glossary Definitions:") -> str:
    if not matches:
        return ""
    return heading + "\n" + "\n".join(f"- {term}: {definition}" for term, definition in matches) + "\n\n"


def build_prompt(query: str, context_chunks: List[Chunk], domain: Any = None) -> str:
    """Builds user prompts containing retrieved factual contexts and matching glossary items."""
    if domain is None:
        domain = core.config.DOMAIN

    # Only the question is scanned: retrieved context often mentions most
    # glossary terms, which would paste every definition into every prompt.
    glossary_block = format_glossary_block(match_glossary(query, domain))

    context_text = "\n\n".join(f"[{c.chunk_id}] {c.text}" for c in context_chunks)
    
    return f"""{build_system_prompt(domain)}

{glossary_block}Context:
{context_text}

Question: {query}
Answer with inline citations like [chunk_id]."""

# Retain old compatible interface mapping to build_prompt internally
def build_user_prompt(query: str, context_chunks: List[Chunk]) -> str:
    """Standardized user prompt matching original compatibility mappings."""
    return build_prompt(query, context_chunks, core.config.DOMAIN)


DAQ_EXPLANATION_RULES = """You explain already-computed DAQ findings only.
Do not calculate, estimate, derive, or invent statistics, sampling rates,
feature values, anomaly scores, or conclusions beyond the supplied evidence.
Use only the stated facts. Cite every discussed finding using its supplied
short label, such as [Finding 1]. The structured citation payload carries the
recording path, channel, and sample/time range, so do not repeat file paths in
the conversational answer unless the user explicitly asks for them.
Write a short practical summary followed by at most three representative
findings. Do not repeat every overlapping window unless the user explicitly
asks for a complete list. Do not print raw feature values, baseline values,
long IDs, or JSON-like field names; use the supplied plain-language evidence."""


def _format_graph_context(edges: List[GraphEdge]) -> str:
    if not edges:
        return "None supplied."
    return "\n".join(
        f"- {edge.source} -[:{edge.type}]-> {edge.target}"
        + (f" {edge.properties}" if edge.properties else "")
        for edge in edges
    )


def build_daq_explanation_prompt(
    request: str,
    findings: List[Finding],
    conditions: Dict[str, Condition],
    graph_context: List[GraphEdge],
) -> str:
    """Render facts for explanation without admitting raw arrays or signal math.

    This function accepts only computed Finding evidence, condition metadata,
    and typed graph relationships. Raw signal samples are intentionally absent
    from this interface.
    """
    if not findings:
        raise ValueError("at_least_one_finding_is_required_for_a_daq_explanation")
    rendered_findings: list[str] = []
    for number, finding in enumerate(findings, start=1):
        condition = conditions.get(finding.evidence.get("condition_id"))
        condition_text = (
            f"condition_id={condition.condition_id}, S={condition.S}, F={condition.F}, D={condition.D}"
            if condition is not None
            else f"condition_id={finding.evidence.get('condition_id', 'unknown')}"
        )
        evidence = finding.evidence
        citation = {
            "channel": evidence["channel"],
            "window_id": evidence["window_id"],
            "sample_range": evidence["sample_range"],
            "time_range": evidence.get("time_range"),
        }
        plain_language = [
            item["plain_language"]
            for item in evidence.get("dominant_feature_deviations", [])
            if "plain_language" in item
        ]
        rendered_findings.append(
            f"[Finding {number}]\n"
            f"type={finding.finding_type}; anomaly threshold exceeded; model={finding.model_version}\n"
            f"condition: {condition_text}\n"
            f"citation: {citation}\n"
            f"computed_evidence_in_plain_language: {plain_language}"
        )
    findings_text = "\n\n".join(rendered_findings)
    # "condition 4" names the scope; it isn't a request to define "Condition"
    glossary_block = format_glossary_block(
        match_glossary(re.sub(r"\bcondition\s*(?:id)?\s*[:#-]?\s*\d+", " ", request, flags=re.IGNORECASE)),
        heading="Definitions of terms the user mentioned (background only; use them if they help the explanation):",
    )
    return f"""{DAQ_EXPLANATION_RULES}

{glossary_block}User request: {request}

Retrieved finding count: {len(findings)}

Already-computed findings:
{findings_text}

Relevant provenance graph context:
{_format_graph_context(graph_context)}

Write a concise evidence-grounded explanation. Do not perform signal math."""


DOCUMENT_ANSWER_RULES = """You answer questions about this project using only the supplied
project documents and glossary definitions. The documents explain how the
system works, the machine and the dataset; they contain no measurements of
individual runs. Do not calculate, estimate or invent anything they don't say.
Cite each claim with the supplied source label, one per bracket, such as
[Source 1] or [Source 1][Source 3]. If the
documents don't answer the question, say so plainly. If the user is asking how
the machine actually behaved in a specific run, explain that they should name a
condition number and a signal (for example: "spindle vibration for condition 4")
so the system can look up computed findings. Keep the answer short and practical."""


def build_document_answer_prompt(question: str, sources: List[Chunk], domain: Any = None) -> str:
    """Evidence-only prompt over retrieved knowledge-document chunks, labelled [Source N]."""
    glossary_block = format_glossary_block(match_glossary(question, domain))
    rendered = "\n\n".join(
        f"[Source {number}] (from {chunk.metadata.get('source_path', chunk.doc_id)})\n{chunk.text}"
        for number, chunk in enumerate(sources, start=1)
    ) or "None found."
    return f"""{DOCUMENT_ANSWER_RULES}

{glossary_block}Question: {question}

Project documents:
{rendered}

Answer:"""


# =============================================================================
# Step 6 — Unified Multi-Source Grounded Prompt Builder
# =============================================================================

GROUNDED_ANSWER_RULES = """You generate evidence-grounded answers based STRICTLY on the supplied evidence.
Do not calculate, estimate, derive, or invent numbers, statistics, or relationships not present in the evidence.
Use only the stated facts. Cite each claim using distinct citation markers per evidence type:
- Use [Finding N] when discussing machine session findings or signal anomalies.
- Use [Doc N] when citing technical documentation passages or standard operating procedures.
- Use [Email N] when citing email communications or organizational discussions.
Only assert cross-source connections (such as an email being related to a machine fault or session anomaly) if explicitly confirmed by the supplied Graph Traversal Context or Cross-Source Analytical Links.
If the supplied evidence is insufficient to answer the question, state that clearly and concisely without guessing."""


def build_grounded_answer_prompt(
    query: str,
    reasoning_result: Optional[Any] = None,
    retrieved_data: Optional[Any] = None,
    findings: Optional[List[Dict[str, Any]]] = None,
    document_chunks: Optional[List[Chunk]] = None,
    email_chunks: Optional[List[Chunk]] = None,
    graph_paths: Optional[List[str]] = None,
    domain: Any = None,
) -> str:
    """Build a unified multi-source prompt with [Finding N], [Doc N], [Email N] citation tags."""
    if domain is None:
        domain = core.config.DOMAIN

    # 1. Domain Glossary
    glossary_block = format_glossary_block(
        match_glossary(re.sub(r"\b(?:session|condition)\s*[:#-]?\s*\d+", " ", query, flags=re.IGNORECASE), domain),
        heading="Domain Glossary Definitions (background only):",
    )

    # 2. Extract Evidence Lists
    all_findings: List[Dict[str, Any]] = []
    if findings is not None:
        all_findings.extend(findings)
    elif reasoning_result and getattr(reasoning_result, "session_findings", None):
        all_findings.extend(reasoning_result.session_findings)
    elif retrieved_data and getattr(retrieved_data, "all_findings", None):
        all_findings.extend(retrieved_data.all_findings)

    all_docs: List[Chunk] = []
    if document_chunks is not None:
        all_docs.extend(document_chunks)
    elif retrieved_data and getattr(retrieved_data, "document_passages", None):
        for doc_node in retrieved_data.document_passages:
            all_docs.extend(doc_node.chunks)

    all_emails: List[Chunk] = []
    if email_chunks is not None:
        all_emails.extend(email_chunks)
    elif retrieved_data and getattr(retrieved_data, "email_passages", None):
        for eml_node in retrieved_data.email_passages:
            all_emails.extend(eml_node.chunks)

    # 3. Format Finding Blocks [Finding N]
    finding_blocks: List[str] = []
    for idx, f in enumerate(all_findings, start=1):
        f_dict = f if isinstance(f, dict) else (f.model_dump() if hasattr(f, "model_dump") else dict(f))
        sid = f_dict.get("session_id", "N/A")
        cid = f_dict.get("condition_id", "N/A")
        rec = f_dict.get("recording_number", f_dict.get("recording_id", "N/A"))
        chan = f_dict.get("channel", "N/A")
        score = f_dict.get("score", 0.0)
        ev = f_dict.get("evidence", {})
        deps = ev.get("top_departures", ev.get("dominant_feature_deviations", []))
        dep_str = ", ".join(
            [f"{d.get('feature')}: {d.get('departure_sigmas', 0):.1f}σ" for d in deps[:2]]
        ) if deps else "anomaly threshold exceeded"

        finding_blocks.append(
            f"[Finding {idx}]\n"
            f"- Session / Recording: Session {sid} (Condition {cid}, Rec {rec})\n"
            f"- Channel: {chan}\n"
            f"- Anomaly Score: {score:.2f}\n"
            f"- Computed Plain-Language Evidence: {dep_str}"
        )

    # 4. Format Document Blocks [Doc N]
    doc_blocks: List[str] = []
    for idx, doc in enumerate(all_docs, start=1):
        src = doc.metadata.get("source_path", doc.doc_id)
        doc_blocks.append(f"[Doc {idx}] (from {src})\n{doc.text.strip()}")

    # 5. Format Email Blocks [Email N]
    email_blocks: List[str] = []
    for idx, eml in enumerate(all_emails, start=1):
        src = eml.metadata.get("source_path", eml.doc_id)
        subject = eml.metadata.get("subject", "")
        sender = eml.metadata.get("from", eml.metadata.get("sender", "Unknown"))
        header_info = f"From: {sender} | Subject: {subject}" if subject else f"Source: {src}"
        email_blocks.append(f"[Email {idx}] ({header_info})\n{eml.text.strip()}")

    # 6. Format Graph Traversal Paths
    paths_rendered: List[str] = []
    if graph_paths:
        paths_rendered.extend(graph_paths)
    elif retrieved_data and getattr(retrieved_data, "subgraph", None) and retrieved_data.subgraph.paths:
        for p in retrieved_data.subgraph.paths:
            p_str = p.to_text() if hasattr(p, "to_text") else (getattr(p, "formatted", str(p)))
            paths_rendered.append(str(p_str))
    elif retrieved_data and getattr(retrieved_data, "subgraph", None) and retrieved_data.subgraph.triplets:
        paths_rendered.extend(retrieved_data.subgraph.triplets)

    # 7. Format Cross-Source Analytical Links
    cross_links_rendered: List[str] = []
    if reasoning_result and getattr(reasoning_result, "cross_source_links", None):
        for link in reasoning_result.cross_source_links:
            cross_links_rendered.append(f"- {link.summary_claim}")

    # Build Complete Prompt Body
    sections = [GROUNDED_ANSWER_RULES, ""]
    if glossary_block:
        sections.append(glossary_block.strip())
        sections.append("")

    sections.append(f"User Question: {query}\n")

    if finding_blocks:
        sections.append("### Computed Machine & Session Findings:")
        sections.append("\n\n".join(finding_blocks))
        sections.append("")

    if doc_blocks:
        sections.append("### Technical Documentation Passages:")
        sections.append("\n\n".join(doc_blocks))
        sections.append("")

    if email_blocks:
        sections.append("### Organizational & Email Communications:")
        sections.append("\n\n".join(email_blocks))
        sections.append("")

    if paths_rendered:
        sections.append("### Graph Traversal Context & Provenance Paths:")
        sections.append("\n".join(f"- {path}" for path in paths_rendered[:15]))
        sections.append("")

    if cross_links_rendered:
        sections.append("### Cross-Source Analytical Corroborations:")
        sections.append("\n".join(cross_links_rendered[:10]))
        sections.append("")

    if not finding_blocks and not doc_blocks and not email_blocks:
        sections.append("No direct evidence passages found in the knowledge base.\n")

    sections.append("Synthesize a concise, grounded explanation with distinct [Finding N], [Doc N], [Email N] citations:")
    return "\n".join(sections)


def build_grounded_citations(
    findings: Optional[List[Dict[str, Any]]] = None,
    document_chunks: Optional[List[Chunk]] = None,
    email_chunks: Optional[List[Chunk]] = None,
    reasoning_result: Optional[Any] = None,
    retrieved_data: Optional[Any] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Generate structured, verifiable citation records mapped to distinct labels."""
    all_findings: List[Dict[str, Any]] = []
    if findings is not None:
        all_findings.extend(findings)
    elif reasoning_result and getattr(reasoning_result, "session_findings", None):
        all_findings.extend(reasoning_result.session_findings)
    elif retrieved_data and getattr(retrieved_data, "all_findings", None):
        all_findings.extend(retrieved_data.all_findings)

    all_docs: List[Chunk] = []
    if document_chunks is not None:
        all_docs.extend(document_chunks)
    elif retrieved_data and getattr(retrieved_data, "document_passages", None):
        for doc_node in retrieved_data.document_passages:
            all_docs.extend(doc_node.chunks)

    all_emails: List[Chunk] = []
    if email_chunks is not None:
        all_emails.extend(email_chunks)
    elif retrieved_data and getattr(retrieved_data, "email_passages", None):
        for eml_node in retrieved_data.email_passages:
            all_emails.extend(eml_node.chunks)

    finding_citations = [
        {
            "label": f"Finding {idx}",
            "finding_id": f.get("finding_id", f"finding_{idx}"),
            "session_id": f.get("session_id"),
            "condition_id": f.get("condition_id"),
            "recording_number": f.get("recording_number"),
            "channel": f.get("channel"),
            "score": f.get("score"),
            "source_path": f.get("recording_id", f.get("source_path", "DAQ Dataset")),
            "evidence": f.get("evidence", {}),
        }
        for idx, f in enumerate(all_findings, start=1)
    ]

    doc_citations = [
        {
            "label": f"Doc {idx}",
            "doc_id": c.doc_id,
            "chunk_id": c.chunk_id,
            "source_path": c.metadata.get("source_path", c.doc_id),
            "snippet": " ".join(c.text.split())[:300],
        }
        for idx, c in enumerate(all_docs, start=1)
    ]

    email_citations = [
        {
            "label": f"Email {idx}",
            "email_id": c.doc_id,
            "chunk_id": c.chunk_id,
            "source_path": c.metadata.get("source_path", c.doc_id),
            "subject": c.metadata.get("subject", ""),
            "sender": c.metadata.get("from", c.metadata.get("sender", "Unknown")),
            "snippet": " ".join(c.text.split())[:300],
        }
        for idx, c in enumerate(all_emails, start=1)
    ]

    unified_citations = finding_citations + doc_citations + email_citations
    return {
        "citations": unified_citations,
        "finding_citations": finding_citations,
        "doc_citations": doc_citations,
        "email_citations": email_citations,
    }

