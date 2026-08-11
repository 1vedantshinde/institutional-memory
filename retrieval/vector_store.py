"""Vector store registry and pluggable search interface.

Allows switching databases (e.g. Qdrant / C++ engine) cleanly.
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
            # Cosine similarity dot product calculation
            score = sum(q * v for q, v in zip(query_vector, vec))
            results.append((score, point))
            
        results.sort(key=lambda x: x[0], reverse=True)
        return [point for score, point in results[:limit]]

# Global simulated Qdrant database instance
qdrant = QdrantMockClient()

def upsert_chunk(chunk: Chunk) -> None:
    """Procedural vector helper merging and storing vectors inside Qdrant."""
    vec = embed(chunk.text)
    chunk.embedding = vec
    
    # Store complete attributes inside payload
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
        # Extract payload and construct schema Chunk
        meta = {k: v for k, v in payload.items() if k not in ["text", "doc_id"]}
        chunks.append(Chunk(
            chunk_id=pt["id"],
            doc_id=payload.get("doc_id", "Unknown"),
            text=payload.get("text", ""),
            embedding=pt["vector"],
            metadata=meta
        ))
    return chunks

# OO Adapter class mapping
@vector_store_registry.register("in_memory")
class InMemoryVectorStore(BaseVectorStore):
    """Bridge Adapter that lets the IngestionPipeline store chunks inside Qdrant."""
    
    def insert_chunks(self, chunks: List[Chunk]) -> None:
        """Saves chunks in Qdrant."""
        for chunk in chunks:
            upsert_chunk(chunk)
            
    def similarity_search(
        self, 
        query_embedding: List[float], 
        k: int = 5, 
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Chunk]:
        """Performs cosine lookups complying with active filters."""
        points = qdrant.search(query_embedding, limit=k)
        chunks = []
        for pt in points:
            payload = pt["payload"]
            
            # Metadata filter validation
            if filters:
                matching = True
                for filter_key, filter_val in filters.items():
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
                metadata={k: v for k, v in payload.items() if k not in ["text", "doc_id"]}
            ))
        return chunks
