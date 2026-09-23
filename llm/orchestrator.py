"""LLM generation, grounding, citation, and confidence orchestration module.

Decoupled orchestrator handling hybrid retrieval, prompt rendering,
LLM response generation, confidence scoring, and citation mapping.
"""
import os
import re
from pathlib import Path
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
from core.registry import llm_registry, vector_store_registry, embedder_registry
from core.schema import Chunk, Condition, Finding
from knowledge.graph_store import GraphEdge, Neo4jSimulationDriver
from knowledge.ontology import (
    CAPTURED_UNDER,
    EXHIBITS_PATTERN,
    HAS_WINDOW,
    SIMILAR_TO,
    recording_node_id,
    window_node_id,
)
from llm.prompt_builder import build_daq_explanation_prompt, build_system_prompt, build_prompt
from retrieval.retriever import hybrid_retrieve, graph_augment

# Load only the project-local ignored credential file. Environment variables
# still take precedence, which is appropriate for deployments and CI.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

# Default Confidence Threshold
CONFIDENCE_THRESHOLD = 0.5

def _configured_llm() -> Any:
    """Create the explicitly configured provider; never silently substitute one."""
    provider = os.environ.get("LLM_PROVIDER", "mock").strip().lower()
    return llm_registry.get(provider)()


# ``mock`` remains the safe default for local tests. Production must set
# LLM_PROVIDER=openai and OPENAI_API_KEY; the DAQ API rejects mock answers.
llm = _configured_llm()


def score_confidence(response: str, context_chunks: List[Chunk]) -> float:
    """Calculates word-recall overlap confidence score between LLM response and context chunks (0.0 - 1.0)."""
    if not context_chunks or not response:
        return 0.0

    # High default score for simulated/mock answers
    if "[mock llm response]" in response.lower():
        return 0.95

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

        # Check explicit regex match or exact tag substring match
        if chunk_id in explicit_tags or f"[{chunk_id}]" in response or chunk_id.lower() in response_lower:
            cited = True
        else:
            # Fallback: Key-term overlap check
            chunk_keywords = set(w.lower() for w in re.findall(r'\b\w+\b', chunk.text) if len(w) >= 4)
            resp_keywords = set(w.lower() for w in re.findall(r'\b\w+\b', response) if len(w) >= 4)
            if chunk_keywords and len(chunk_keywords.intersection(resp_keywords)) >= 2:
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
        llm_key: str = "mock",
        embedder_key: str = "mock",
        vector_store_key: str = "in_memory"
    ):
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


class DAQExplanationError(ValueError):
    """DAQ explanation inputs lack sufficient traceable computed evidence."""


class DAQExplanationOrchestrator:
    """Explain retrieved DAQ findings; never ask an LLM to perform signal math."""

    def __init__(self, llm_provider: Any, graph_driver: Neo4jSimulationDriver):
        self.llm = llm_provider
        self.graph_driver = graph_driver

    @staticmethod
    def _assert_traceable_evidence(findings: List[Finding]) -> None:
        """Gate generation on the required raw-data citation fields.

        This is the generation-side integrity rule: absent computed evidence,
        no LLM call is permitted, so it cannot fabricate missing numbers.
        """
        for finding in findings:
            evidence = finding.evidence
            required = {"recording_id", "source_path", "channel", "window_id", "sample_range"}
            missing = [field for field in required if field not in evidence]
            if missing:
                raise DAQExplanationError(
                    f"finding_missing_traceable_evidence:{finding.finding_id}:{','.join(sorted(missing))}"
                )
            sample_range = evidence["sample_range"]
            if not isinstance(sample_range, dict) or not {"sample_start", "sample_end"} <= set(sample_range):
                raise DAQExplanationError(
                    f"finding_missing_sample_range:{finding.finding_id}"
                )

    def explain(
        self,
        request: str,
        findings: List[Finding],
        conditions: Dict[str, Condition],
    ) -> Dict[str, Any]:
        """Build an evidence-only prompt, call the LLM, and return fixed citations."""
        if not findings:
            raise DAQExplanationError("no_retrieved_findings_to_explain")
        self._assert_traceable_evidence(findings)
        graph_context: list[GraphEdge] = []
        seen_edges: set[tuple[str, str, str, str]] = set()
        for finding in findings:
            recording_id = recording_node_id(finding.recording_id)
            window_id = window_node_id(finding.window_id or "")
            # A Recording can have tens of thousands of HAS_WINDOW edges. Only
            # retain its condition lineage; the cited window gets its own exact
            # HAS_WINDOW/EXHIBITS_PATTERN/SIMILAR_TO context below.
            relevant_edges = [
                edge
                for edge in self.graph_driver.get_neighbors(recording_id)
                if edge.type == CAPTURED_UNDER
            ]
            relevant_edges.extend(
                edge
                for edge in self.graph_driver.get_neighbors(window_id)
                if edge.type in {HAS_WINDOW, EXHIBITS_PATTERN, SIMILAR_TO}
            )
            for edge in relevant_edges:
                edge_key = (edge.source, edge.target, edge.type, repr(edge.properties))
                if edge_key not in seen_edges:
                    graph_context.append(edge)
                    seen_edges.add(edge_key)
        prompt = build_daq_explanation_prompt(request, findings, conditions, graph_context)
        # The prompt is evidence-only and contains an explicit no-computation instruction.
        assert "Do not calculate, estimate, derive, or invent statistics" in prompt
        response = self.llm.generate(prompt, system_prompt=DAQ_EXPLANATION_SYSTEM_PROMPT)
        return {
            "answer": response,
            "prompt": prompt,
            "findings": findings,
            "citations": [
                {"finding_id": finding.finding_id, **finding.evidence}
                for finding in findings
            ],
            "graph_context": graph_context,
        }


DAQ_EXPLANATION_SYSTEM_PROMPT = (
    "Explain supplied DAQ findings only. Never compute or infer numeric results; "
    "cite the supplied recording path, channel, and range."
)
