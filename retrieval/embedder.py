"""Default Embedder implementations."""
import random
from typing import List
from core.registry import embedder_registry, BaseEmbedder

@embedder_registry.register("mock")
class MockEmbedder(BaseEmbedder):
    """A standard mock embedder producing randomized float vectors of size 1536.
    
    Useful for testing retrieval architectures, pipelines, and the custom C++ similarity core.
    """
    
    def __init__(self, dimension: int = 1536):
        self.dimension = dimension
        
    def embed_query(self, text: str) -> List[float]:
        # Generate random values and normalize
        vec = [random.uniform(-1, 1) for _ in range(self.dimension)]
        magnitude = sum(x * x for x in vec) ** 0.5
        if magnitude == 0:
            return [0.0] * self.dimension
        return [x / magnitude for x in vec]
        
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [self.embed_query(t) for t in texts]
