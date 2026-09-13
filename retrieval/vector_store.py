"""Vector store registry and pluggable search interface.

Backed by real Qdrant when QDRANT_URL is set and qdrant-client is installed,
falling back to an in-memory mock otherwise. The mock and real client expose
the exact same upsert()/search()/list_all_points() interface so nothing else
in the codebase needs to know which one is active.
"""
import os
from typing import List, Dict, Any, Optional
from core.registry import vector_store_registry, BaseVectorStore
from core.schema import Chunk
from retrieval.embedder import embed

EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1536"))  # 1536 for mock, 384 for all-MiniLM-L6-v2
COLLECTION_NAME = "chunks"


class QdrantMockClient:
    """A local mock representation simulating Qdrant DB points storage."""

    def __init__(self):
        self.points: Dict[str, Dict[str, Any]] = {}

    def upsert(self, id: str, vector: List[float], payload: Dict[str, Any]) -> None:
        self.points[id] = {
            "id": id,
            "vector": vector,
            "payload": payload
        }
        print(f"[Qdrant] UPSERT points ID={id}")

    def search(self, query_vector: List[float], limit: int = 8) -> List[Dict[str, Any]]:
        results = []
        for point_id, point in self.points.items():
            vec = point["vector"]
            # Cosine similarity dot product calculation on normalized vectors
            score = sum(q * v for q, v in zip(query_vector, vec))
            results.append((score, point))

        results.sort(key=lambda x: x[0], reverse=True)
        return [point for score, point in results[:limit]]

    def list_all_points(self) -> List[Dict[str, Any]]:
        """Returns all stored points — used by BM25Index to build its corpus."""
        return list(self.points.values())


class QdrantRealClient:
    """Thin wrapper matching the QdrantMockClient interface, backed by real Qdrant.

    Drop-in replacement: set QDRANT_URL (e.g. http://localhost:6333) to activate.
    EMBEDDING_DIM must match your active embedder (1536 mock, 384 all-MiniLM-L6-v2).
    """

    def __init__(self, url: Optional[str] = None):
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams
        self._client = QdrantClient(url=url or os.getenv("QDRANT_URL", "http://localhost:6333"))
        existing = [c.name for c in self._client.get_collections().collections]
        if COLLECTION_NAME not in existing:
            self._client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
            )

    def upsert(self, id: str, vector: List[float], payload: Dict[str, Any]) -> None:
        from qdrant_client.models import PointStruct
        import uuid
        # Qdrant point IDs must be uint64 or UUID — hash the string chunk_id to a stable UUID
        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, id))
        self._client.upsert(
            collection_name=COLLECTION_NAME,
            points=[PointStruct(id=point_id, vector=vector, payload={**payload, "_chunk_id": id})],
        )
        print(f"[Qdrant] UPSERT points ID={id}")

    def search(self, query_vector: List[float], limit: int = 8) -> List[Dict[str, Any]]:
        result = self._client.query_points(
            collection_name=COLLECTION_NAME,
            query=query_vector,
            limit=limit,
            with_payload=True,
            with_vectors=True,
        )
        points = []
        for pt in result.points:
            points.append({
                "id": pt.payload.get("_chunk_id", str(pt.id)),
                "vector": pt.vector,
                "payload": pt.payload,
            })
        return points

    def list_all_points(self) -> List[Dict[str, Any]]:
        """Scrolls all stored points — used by BM25Index to build its corpus."""
        results, _ = self._client.scroll(
            collection_name=COLLECTION_NAME,
            limit=10000,
            with_payload=True,
            with_vectors=True,
        )
        return [
            {
                "id": pt.payload.get("_chunk_id", str(pt.id)),
                "vector": pt.vector,
                "payload": pt.payload,
            }
            for pt in results
        ]


def _build_qdrant_client():
    """Instantiates real Qdrant if QDRANT_URL is set and qdrant-client is installed,
    otherwise falls back to the in-memory mock."""
    qdrant_url = os.getenv("QDRANT_URL")
    if qdrant_url:
        try:
            client = QdrantRealClient(url=qdrant_url)
            print(f"[VectorStore] Connected to real Qdrant at {qdrant_url}")
            return client
        except Exception as e:
            print(f"[VectorStore] Warning: real Qdrant unavailable ({e}), falling back to mock.")
    return QdrantMockClient()


# Global simulated/real Qdrant database instance
qdrant = _build_qdrant_client()


def upsert_chunk(chunk: Chunk) -> None:
    """Procedural vector helper storing vectors inside Qdrant."""
    if not chunk.embedding:
        vec = embed(chunk.text)
        chunk.embedding = vec
    else:
        vec = chunk.embedding

    payload_to_store = {
        **chunk.metadata,
        "text": chunk.text,
        "doc_id": chunk.doc_id
    }
    qdrant.upsert(id=chunk.chunk_id, vector=vec, payload=payload_to_store)

def search(query_text: str, top_k: int = 8) -> List[Chunk]:
    """Procedural lookup helper scanning Qdrant similarity match outputs."""
    q_vec = embed(query_text)
    points = qdrant.search(q_vec, limit=top_k)

    chunks = []
    for pt in points:
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

@vector_store_registry.register("in_memory")
@vector_store_registry.register("qdrant_mock")
class InMemoryVectorStore(BaseVectorStore):
    """Bridge Adapter wrapping QdrantMockClient/QdrantRealClient for VectorStore registry operations."""

    def __init__(self, client=None):
        self.client = client or qdrant

    def insert_chunks(self, chunks: List[Chunk]) -> None:
        """Saves chunks into the vector store."""
        for chunk in chunks:
            if not chunk.embedding:
                chunk.embedding = embed(chunk.text)
            payload_to_store = {
                **chunk.metadata,
                "text": chunk.text,
                "doc_id": chunk.doc_id
            }
            self.client.upsert(id=chunk.chunk_id, vector=chunk.embedding, payload=payload_to_store)

    def similarity_search(
        self,
        query_vector: List[float],
        top_k: int = 8,
        metadata_filter: Optional[Dict[str, Any]] = None,
        k: Optional[int] = None,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Chunk]:
        """Performs cosine lookups using query vector and filters."""
        limit_val = k if k is not None else top_k
        active_filters = filters if filters is not None else metadata_filter

        # Search wider than the requested limit so post-search filtering doesn't starve results
        search_limit = limit_val * 5 if active_filters else limit_val
        points = self.client.search(query_vector, limit=search_limit)
        chunks = []
        for pt in points:
            payload = pt["payload"]

            # Metadata filter validation
            if active_filters:
                matching = True
                for filter_key, filter_val in active_filters.items():
                    if payload.get(filter_key) != filter_val:
                        matching = False
                        break
                if not matching:
                    continue

            chunks.append(Chunk(
                chunk_id=pt["id"],
                doc_id=payload.get("doc_id", "Unknown"),
                text=payload.get("text", ""),
                embedding=pt["vector"],
                metadata={k_meta: v_meta for k_meta, v_meta in payload.items() if k_meta not in ["text", "doc_id"]}
            ))
            if len(chunks) >= limit_val:
                break
        return chunks
