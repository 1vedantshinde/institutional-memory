"""Vector store implementations."""
from typing import List, Dict, Any, Optional
from core.registry import vector_store_registry, BaseVectorStore
from core.schema import Chunk

@vector_store_registry.register("in_memory")
class InMemoryVectorStore(BaseVectorStore):
    """An in-memory Vector Store simulation with cosine similarity matching.
    
    Acts as a mock representation before connecting to production databases
    like Qdrant or the native C++ SIMD engine.
    """
    
    def __init__(self):
        self.collection: List[Chunk] = []
        
    def insert_chunks(self, chunks: List[Chunk]) -> None:
        self.collection.extend(chunks)
        print(f"[InMemoryVectorStore] Inserted {len(chunks)} chunks. Total corpus size: {len(self.collection)}")
        
    def similarity_search(self, query_embedding: List[float], k: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Chunk]:
        """Brute-force scanned cosine similarity calculation with metadata filters.
        
        Assumes embeddings have been normalized.
        """
        results = []
        
        for chunk in self.collection:
            if chunk.embedding is None:
                continue
                
            # Filter verification if conditions are present
            if filters:
                matching = True
                for filter_key, filter_val in filters.items():
                    if chunk.metadata.get(filter_key) != filter_val:
                        matching = False
                        break
                if not matching:
                    continue
            
            # Simple dot product calculation
            score = sum(q * c for q, c in zip(query_embedding, chunk.embedding))
            results.append((score, chunk))
            
        # Sort by similarity score descending
        results.sort(key=lambda x: x[0], reverse=True)
        return [chunk for score, chunk in results[:k]]
