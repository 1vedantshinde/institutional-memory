"""Prompt builder module.

Handles structural rendering of LLM prompt payloads backed by the loaded DOMAIN configuration.
"""
from typing import List, Dict, Any, Optional
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

def build_prompt(query: str, context_chunks: List[Chunk], domain: Any = None) -> str:
    """Builds user prompts containing retrieved factual contexts and matching glossary items."""
    if domain is None:
        domain = core.config.DOMAIN
        
    # Extract glossary items based on config structure
    glossary_matches = []
    combined_text = (query + " " + " ".join(c.text for c in context_chunks)).lower()
    
    if isinstance(domain, dict):
        glossary = domain.get("glossary", [])
        for item in glossary:
            term = item.get("term", "") if isinstance(item, dict) else getattr(item, "term", "")
            meaning = item.get("meaning", "") if isinstance(item, dict) else getattr(item, "meaning", "")
            term_lower = term.lower()
            if term_lower and (f" {term_lower} " in f" {combined_text} " or combined_text.startswith(term_lower) or combined_text.endswith(term_lower)):
                glossary_matches.append(f"- {term}: {meaning}")
    else:
        for item in getattr(domain, "glossary", []):
            term_lower = item.term.lower()
            if f" {term_lower} " in f" {combined_text} " or combined_text.startswith(term_lower) or combined_text.endswith(term_lower):
                glossary_matches.append(f"- {item.term}: {item.meaning}")
                
    glossary_block = ""
    if glossary_matches:
        glossary_block = (
            "Domain Glossary Definitions:\n"
            + "\n".join(glossary_matches)
            + "\n\n"
        )
        
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
Use only the stated facts. Cite every discussed finding as [finding_id] and
include its recording path, channel, and sample/time range."""


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
    for finding in findings:
        condition = conditions.get(finding.evidence.get("condition_id"))
        condition_text = (
            f"condition_id={condition.condition_id}, S={condition.S}, F={condition.F}, D={condition.D}"
            if condition is not None
            else f"condition_id={finding.evidence.get('condition_id', 'unknown')}"
        )
        rendered_findings.append(
            f"[{finding.finding_id}]\n"
            f"type={finding.finding_type}; computed_score={finding.score}; model_version={finding.model_version}\n"
            f"condition: {condition_text}\n"
            f"evidence: {finding.evidence}"
        )
    findings_text = "\n\n".join(rendered_findings)
    return f"""{DAQ_EXPLANATION_RULES}

User request: {request}

Already-computed findings:
{findings_text}

Relevant provenance graph context:
{_format_graph_context(graph_context)}

Write a concise evidence-grounded explanation. Do not perform signal math."""
