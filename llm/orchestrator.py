"""LLM generation, grounding, citation, and confidence orchestration module.

Decoupled orchestrator handling hybrid retrieval, prompt rendering,
LLM response generation, confidence scoring, and citation mapping.
"""
import re
import os
from typing import List, Dict, Any, Optional
from core.registry import llm_registry, vector_store_registry, embedder_registry
from core.schema import Chunk
from llm.prompt_builder import build_system_prompt, build_prompt
from retrieval.retriever import hybrid_retrieve, graph_augment
import llm.providers  # noqa: F401 — ensure provider registration side-effects run

# Default Confidence Threshold
CONFIDENCE_THRESHOLD = 0.5

# Global LLM provider instance: controlled by LLM_PROVIDER env var (default: "mock")
# Switch to real backend: export LLM_PROVIDER=anthropic
llm = llm_registry.get(os.getenv("LLM_PROVIDER", "mock"))()


def score_confidence(response: str, context_chunks: List[Chunk]) -> float:
    """Calculates word-recall overlap confidence score between LLM response and context chunks (0.0 - 1.0)."""
    if not context_chunks or not response:
        return 0.0

    # Tokenize response words (alphanumeric, length >= 3)
    response_words = set(w.lower() for w in re.findall(r'\b\w+\b', response) if len(w) >= 3)
    if not response_words:
        return 0.0

    # Gather context words from all retrieved chunks
    context_words = set()
    for chunk in context_chunks:
        context_words.update(w.lower() for w in re.findall(r'\b\w+\b', chunk.text) if len(w) >= 3)

    if not context_words:
        return 0.0

    # Word-recall overlap: fraction of response words present in the retrieved context
    overlap = response_words.intersection(context_words)
    recall = len(overlap) / len(response_words)

    # Clamp value strictly to range [0.0, 1.0]
    return max(0.0, min(1.0, float(recall)))


def map_citations(response: str, context_chunks: List[Chunk]) -> List[Dict[str, Any]]:
    """Scans response for explicit [chunk_id] tags using regex, falling back to key-term overlap."""
    if not context_chunks:
        return []

    citations = []
    response_lower = response.lower()
    
    # 1. Regex scan for bracketed tag citations: e.g. [chunk_123]
    explicit_tags = set(re.findall(r"\[([a-zA-Z0-9_\-]+)\]", response))

    for chunk in context_chunks:
        cited = False
        chunk_id = chunk.chunk_id

        # Only trust explicit [chunk_id] bracket citations from the LLM
        if chunk_id in explicit_tags or f"[{chunk_id}]" in response:
            cited = True

        if cited:
            snippet_text = chunk.text[:150] + "..." if len(chunk.text) > 150 else chunk.text
            citations.append({
                "doc_id": chunk.doc_id,
                "chunk_id": chunk.chunk_id,
                "chunk_index": chunk.metadata.get("chunk_index", 0),
                "source_path": chunk.metadata.get("source_path", "Unknown"),
                "modality": chunk.metadata.get("modality", "Unknown"),
                "snippet": snippet_text
            })

    return citations


def answer(query: str, limit: int = 8) -> Dict[str, Any]:
    """Orchestrates hybrid retrieval, graph augmentation, LLM generation, confidence scoring, and citation mapping."""
    # 1. Step 9 Hybrid Retrieval & Step 6 Graph Augmentation
    context = hybrid_retrieve(query, top_k=limit)
    context = graph_augment(query, context)

    # 2. Step 10 Domain Prompt Construction
    prompt = build_prompt(query, context)

    # 3. LLM Generation
    response = llm.generate(prompt)

    # 4. Score Confidence (Word-recall overlap)
    confidence = score_confidence(response, context)

    # 5. Reject / Flag if confidence below threshold
    if confidence < CONFIDENCE_THRESHOLD:
        return {
            "answer": "I don't have enough evidence in the knowledge base to answer that.",
            "citations": [],
            "confidence": confidence
        }

    # 6. Map Citations
    citations = map_citations(response, context)
    return {
        "answer": response,
        "citations": citations,
        "confidence": confidence
    }


class TargetLLMProxy:
    """Delegation proxy directing generate calls to the module-level active LLM provider instance."""
    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        return llm.generate(prompt, system_prompt=system_prompt)


class RAGOrchestrator:
    """Thin class wrapper around answer() providing optional metadata filtering for API consumption."""

    def __init__(
        self,
        llm_key: str = None,
        embedder_key: str = "mock",
        vector_store_key: str = "in_memory"
    ):
        # Respect LLM_PROVIDER env var, falling back to passed llm_key, then "mock"
        resolved_llm_key = os.getenv("LLM_PROVIDER", llm_key or "mock")
        self.llm = TargetLLMProxy()
        self.vector_store = vector_store_registry.get(vector_store_key)

    def query(self, user_query: str, limit: int = 3, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Runs retrieval query with metadata filters, builds prompt, generates answer, scores confidence, and returns citations."""
        # 1. Retrieve hybrid context
        context = hybrid_retrieve(user_query, top_k=limit)

        # 2. Apply optional metadata filters
        if filters:
            filtered_context = []
            for chunk in context:
                matches = True
                for fk, fval in filters.items():
                    if chunk.metadata.get(fk) != fval:
                        matches = False
                        break
                if matches:
                    filtered_context.append(chunk)
            context = filtered_context

        # 3. Graph Augmentation
        context = graph_augment(user_query, context)

        # 4. Build Domain Prompt
        prompt = build_prompt(user_query, context)
        system_prompt = build_system_prompt()

        # 5. LLM Generation
        response_text = self.llm.generate(prompt)

        # 6. Confidence Scoring & Citation Mapping
        confidence = score_confidence(response_text, context)

        if confidence < CONFIDENCE_THRESHOLD:
            return {
                "query": user_query,
                "answer": "I don't have enough evidence in the knowledge base to answer that.",
                "citations": [],
                "confidence": confidence,
                "system_prompt": system_prompt
            }

        citations = map_citations(response_text, context)
        return {
            "query": user_query,
            "answer": response_text,
            "citations": citations,
            "confidence": confidence,
            "system_prompt": system_prompt
        }
