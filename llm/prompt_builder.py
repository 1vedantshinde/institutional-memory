"""Prompt builder module.

Handles structural rendering of LLM prompt payloads backed by the loaded DOMAIN configuration.
"""
from typing import List
from core.config import DOMAIN
from core.schema import Chunk

def build_system_prompt() -> str:
    """Renders the system prompt template loaded from config/domain.yaml metadata."""
    return DOMAIN.system_prompt_template.format(domain_name=DOMAIN.domain_name)

def build_user_prompt(query: str, context_chunks: List[Chunk]) -> str:
    """Builds user prompts containing retrieved factual contexts and matching glossary items.
    
    Dynamically scans query and context strings for domain jargon defined in 
    the active domain configuration's glossary, inserting explanations directly 
    into the context section.
    """
    # 1. Format the retrieved context passages
    formatted_contexts = []
    for chunk in context_chunks:
        source_name = chunk.metadata.get("source_path", "Unknown Source")
        doc_type = chunk.metadata.get("modality", "Unknown Format")
        chunk_index = chunk.metadata.get("chunk_index", 0)
        passage = (
            f"[Source: {source_name} ({doc_type}), Chunk {chunk_index}]\n"
            f"{chunk.text.strip()}"
        )
        formatted_contexts.append(passage)
        
    context_block = "\n\n".join(formatted_contexts)
    
    # 2. Match glossary terms present in query or contexts to guide model jargon resolution
    glossary_matches = []
    combined_text = (query + " " + " ".join(c.text for c in context_chunks)).lower()
    
    for item in DOMAIN.glossary:
        term_lower = item.term.lower()
        # Look for full word matching to avoid substring collision (e.g. 'ot' in 'other')
        if f" {term_lower} " in f" {combined_text} " or combined_text.startswith(term_lower) or combined_text.endswith(term_lower):
            glossary_matches.append(f"- {item.term}: {item.meaning}")
            
    glossary_block = ""
    if glossary_matches:
        glossary_block = (
            "Domain Glossary Definitions:\n"
            + "\n".join(glossary_matches)
            + "\n\n"
        )
        
    # 3. Assemble prompt structure
    return (
        f"{glossary_block}"
        f"Context Information:\n"
        f"---------------------\n"
        f"{context_block or 'No context available.'}\n"
        f"---------------------\n"
        f"User Query: {query}\n\n"
        f"Answer:"
    )
