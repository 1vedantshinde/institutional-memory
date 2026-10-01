"""Hybrid retrieval and reranking engine.

Combines vector similarity, Okapi BM25 keyword search, Reciprocal Rank Fusion (RRF)
with route-based weighting, CrossEncoder reranking (ms-marco-MiniLM-L-6-v2),
and PathRAG-style scored 1-hop Knowledge Graph augmentation.
"""
import math
import os
import re
from typing import List, Dict, Any, Optional
from core.schema import Chunk
from retrieval.vector_store import search


class BM25Index:
    """Okapi BM25 index calculation scanning the current vector store payloads."""

    def search(self, query: str, top_k: int = 8) -> List[Chunk]:
        from retrieval.vector_store import qdrant
        # Use list_all_points() so this works with both mock and real Qdrant
        points = qdrant.list_all_points()
        if not points:
            return []

        def tokenize(text: str) -> List[str]:
            return [w.lower() for w in text.split() if w.isalnum() or len(w) > 1]

        query_words = tokenize(query)
        doc_count = len(points)

        dfs = {}
        tfs = []
        doc_lengths = []

        for pt in points:
            text = pt["payload"].get("text", "")
            words = tokenize(text)
            doc_lengths.append(len(words))

            tf = {}
            for w in words:
                tf[w] = tf.get(w, 0) + 1

            tfs.append(tf)
            for w in set(words):
                dfs[w] = dfs.get(w, 0) + 1

        avg_doc_len = sum(doc_lengths) / max(doc_count, 1)

        k1 = 1.5
        b = 0.75
        scored_points = []

        for i, pt in enumerate(points):
            score = 0.0
            tf = tfs[i]
            doc_len = doc_lengths[i]

            for w in query_words:
                if w not in tf:
                    continue
                df = dfs.get(w, 0)
                idf = math.log((doc_count - df + 0.5) / (df + 0.5) + 1.0)
                tf_score = tf[w] * (k1 + 1) / (tf[w] + k1 * (1 - b + b * (doc_len / max(avg_doc_len, 1))))
                score += idf * tf_score

            scored_points.append((score, pt))

        scored_points.sort(key=lambda x: x[0], reverse=True)
        chunks = []
        for score, pt in scored_points[:top_k]:
            if score == 0.0 and query_words:
                continue
            payload = pt["payload"]
            meta = {k: v for k, v in payload.items() if k not in ["text", "doc_id"]}
            chunks.append(Chunk(
                chunk_id=pt["id"],
                doc_id=payload.get("doc_id", "Unknown"),
                text=payload.get("text", ""),
                embedding=pt["vector"],
                metadata=meta
            ))
        return chunks


bm25_index = BM25Index()


def reciprocal_rank_fusion(
    vector_hits: List[Chunk],
    keyword_hits: List[Chunk],
    k: int = 60,
    vector_weight: float = 1.0,
    keyword_weight: float = 1.0,
) -> List[Chunk]:
    """Combines semantic and term-based results using weighted Reciprocal Rank Fusion (RRF).

    Score = sum(weight / (k + rank)) across vector and keyword hit lists.
    Weights are supplied by the query router (B1) for route-aware blending.
    """
    scores: Dict[str, float] = {}
    chunk_map: Dict[str, Chunk] = {}

    for rank, chunk in enumerate(vector_hits):
        chunk_map[chunk.chunk_id] = chunk
        scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + vector_weight * (1.0 / (k + rank + 1))

    for rank, chunk in enumerate(keyword_hits):
        chunk_map[chunk.chunk_id] = chunk
        scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + keyword_weight * (1.0 / (k + rank + 1))

    sorted_ids = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [chunk_map[cid] for cid, _ in sorted_ids]


get_cross_encoder_rerank = None
if os.environ.get("USE_NEURAL_MODELS") == "1":
    try:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        from sentence_transformers import CrossEncoder
        _cross_encoder_cache = None
        def _get_rerank(query: str, chunks: List[Chunk]) -> List[Chunk]:
            global _cross_encoder_cache
            if not chunks:
                return []
            if _cross_encoder_cache is None:
                _cross_encoder_cache = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2", local_files_only=True)

            pairs = [[query, chunk.text] for chunk in chunks]
            scores = _cross_encoder_cache.predict(pairs).tolist()

            scored_chunks = sorted(zip(scores, chunks), key=lambda x: x[0], reverse=True)
            return [chunk for score, chunk in scored_chunks]
        get_cross_encoder_rerank = _get_rerank
    except (ImportError, Exception):
        get_cross_encoder_rerank = None


class MockCrossEncoder:
    """CrossEncoder reranking interface with fallback token-overlap scoring stub."""

    def rerank(self, query: str, chunks: List[Chunk]) -> List[Chunk]:
        if get_cross_encoder_rerank is not None:
            try:
                return get_cross_encoder_rerank(query, chunks)
            except Exception:
                pass

        if not chunks:
            return []

        def tokenize(text: str) -> set:
            return set(w.lower() for w in text.split() if w.isalnum())

        query_tokens = tokenize(query)
        scored_chunks = []
        for chunk in chunks:
            chunk_tokens = tokenize(chunk.text)
            overlap = len(query_tokens.intersection(chunk_tokens))
            p_score = overlap / max(len(query_tokens), 1)
            scored_chunks.append((p_score, chunk))

        scored_chunks.sort(key=lambda x: x[0], reverse=True)
        return [chunk for score, chunk in scored_chunks]


cross_encoder = MockCrossEncoder()


def hybrid_retrieve(query: str, top_k: int = 8) -> List[Chunk]:
    """Fuses vector scan outputs and BM25 token keywords with route-aware weights, then reranks candidates."""
    from retrieval.router import classify_query, route_weights
    route = classify_query(query)
    weights = route_weights(route)

    vector_hits = search(query, top_k=top_k)
    keyword_hits = bm25_index.search(query, top_k=top_k)
    fused = reciprocal_rank_fusion(
        vector_hits,
        keyword_hits,
        vector_weight=weights["vector_weight"],
        keyword_weight=weights["bm25_weight"],
    )
    reranked = cross_encoder.rerank(query, fused)
    return reranked[:top_k]


# DAQ retrieval is intentionally separate from the legacy document-RAG helpers
# above: it fuses exact experimental metadata and numeric feature proximity.
from dataclasses import dataclass
from typing import Mapping, Sequence

from knowledge.graph_store import GraphEdge, Neo4jSimulationDriver
from knowledge.ontology import recording_node_id, window_node_id
from retrieval.feature_store import FeatureSimilarityHit, FeatureStore
from retrieval.metadata_index import IndexedWindow, MetadataIndex


@dataclass(frozen=True)
class DAQRetrievalResult:
    """A feature match with structured metadata and typed provenance context."""

    window: IndexedWindow
    similarity_score: float
    graph_context: list[GraphEdge]


class DAQRetriever:
    """Fuse exact metadata → feature similarity → provenance graph context."""

    def __init__(
        self,
        metadata_index: MetadataIndex,
        feature_store: FeatureStore,
        graph_driver: Neo4jSimulationDriver,
    ) -> None:
        self.metadata_index = metadata_index
        self.feature_store = feature_store
        self.graph_driver = graph_driver

    def query(
        self,
        query_vector: Sequence[float],
        *,
        filters: Mapping[str, object] | None = None,
        top_k: int = 5,
        metric: str = "cosine",
    ) -> list[DAQRetrievalResult]:
        """Narrow candidates exactly, then rank numeric evidence and graph-link it."""
        candidates = self.metadata_index.filter(**dict(filters or {}))
        candidate_ids = {candidate.window.window_id for candidate in candidates}
        hits = self.feature_store.similarity_search(
            query_vector,
            top_k=top_k,
            candidate_window_ids=candidate_ids,
            metric=metric,
        )
        return [self._result_for_hit(hit) for hit in hits]

    def _result_for_hit(self, hit: FeatureSimilarityHit) -> DAQRetrievalResult:
        indexed = self.metadata_index.get(hit.window.window_id)
        graph_context = self.graph_driver.get_neighbors(
            recording_node_id(indexed.recording.recording_id)
        ) + self.graph_driver.get_neighbors(window_node_id(indexed.window.window_id))
        return DAQRetrievalResult(
            window=indexed,
            similarity_score=hit.score,
            graph_context=graph_context,
        )

def extract_entity_mentions(query: str) -> List[str]:
    """Locates Knowledge Graph nodes in user query using case/whitespace/punctuation normalized matches."""
    from knowledge.graph_store import neo4j
    from knowledge.ner import extract_equipment_tags_regex, resolve_entity_id

    mentions = set()
    query_lower = query.lower()
    query_norm = re.sub(r'[\s_\-]+', '', query_lower)

    # 1. Normalized string matches against active graph nodes
    for name in neo4j.nodes.keys():
        name_lower = name.lower()
        name_norm = re.sub(r'[\s_\-]+', '', name_lower)
        if name_lower in query_lower or (len(name_norm) >= 3 and name_norm in query_norm):
            mentions.add(name)

    # 2. Regex tag extraction + RAKG alias resolution
    extracted_tags = extract_equipment_tags_regex(query)
    for tag in extracted_tags:
        canonical_id = resolve_entity_id(tag)
        if canonical_id in neo4j.nodes:
            mentions.add(canonical_id)
        else:
            canonical_norm = re.sub(r'[\s_\-]+', '', canonical_id.lower())
            for name in neo4j.nodes.keys():
                name_norm = re.sub(r'[\s_\-]+', '', name.lower())
                if name_norm == canonical_norm:
                    mentions.add(name)

    return list(mentions)


def graph_augment(query: str, retrieved_chunks: List[Chunk], max_triplets: int = 5) -> List[Chunk]:
    """Retrieves 1-hop triplet neighbors for entity mentions, scores them by query-token overlap,
    and appends only the most relevant max_triplets as extra context (PathRAG-style pruning)."""
    entities = extract_entity_mentions(query)

    from knowledge.graph_store import neo4j
    augmented = list(retrieved_chunks)

    all_triplets = []
    for e in entities:
        all_triplets.extend(neo4j.get_neighbor_triplets(e))

    if not all_triplets:
        return augmented

    # Score triplets by token overlap with the query, keep only the most relevant
    query_tokens = set(query.lower().split())

    def score_triplet(triplet: str) -> int:
        return len(query_tokens.intersection(set(triplet.lower().split())))

    pruned = sorted(all_triplets, key=score_triplet, reverse=True)[:max_triplets]

    for idx, triplet in enumerate(pruned):
        augmented.append(Chunk(
            chunk_id=f"graph_aug_{idx}",
            doc_id="knowledge_graph",
            text=f"Graph Context: {triplet}",
            metadata={"modality": "graph"}
        ))
    return augmented
