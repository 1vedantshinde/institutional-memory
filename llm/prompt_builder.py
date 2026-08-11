"""Prompt builder module.

Handles structural rendering of LLM prompt payloads backed by the loaded DOMAIN configuration.
"""
from typing import List, Dict, Any, Optional
import core.config
from core.schema import Chunk

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
