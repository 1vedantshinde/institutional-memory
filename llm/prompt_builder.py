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
