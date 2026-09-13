"""Vector store registry and pluggable search interface.

Simulates Qdrant DB points storage using normalized vector dot-product cosine similarity.
Exposes InMemoryVectorStore implementing BaseVectorStore.
"""
from typing import List, Dict, Any, Optional
from core.registry import vector_store_registry, BaseVectorStore
from core.schema import Chunk
from retrieval.embedder import embed

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

# Global simulated Qdrant database instance
qdrant = QdrantMockClient()

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
    """Bridge Adapter wrapping QdrantMockClient for VectorStore registry operations."""
    
    def __init__(self, client: Optional[QdrantMockClient] = None):
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

