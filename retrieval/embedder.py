"""Embedding registry and pluggable models interface.

Provides MD5-seeded deterministic vector embeddings for reproducible testing without GPU/network dependencies,
and dynamically gates neural models (SentenceTransformers) behind the USE_NEURAL_MODELS environment variable.
"""
import os
import random
import hashlib
from typing import List, Dict, Callable
from core.registry import embedder_registry, BaseEmbedder

# Global embedding models registry table
EMBEDDER_REGISTRY: Dict[str, Callable[[str], List[float]]] = {}

def register_embedder(name: str):
    """Decorator to register a custom embedding strategy/model."""
    def decorator(fn: Callable[[str], List[float]]):
        EMBEDDER_REGISTRY[name] = fn
        return fn
    return decorator

def get_deterministic_vector(text: str, dimension: int = 1536) -> List[float]:
    """Generates a stable, content-dependent, normalized vector for matching queries during simulation."""
    hasher = hashlib.md5(text.encode("utf-8"))
    seed_val = int(hasher.hexdigest(), 16) % (2**32)
    rng = random.Random(seed_val)
    vec = [rng.uniform(-1, 1) for _ in range(dimension)]
    magnitude = sum(x * x for x in vec) ** 0.5
    if magnitude == 0:
        return [0.0] * dimension
    return [x / magnitude for x in vec]

_neural_model_instance = None

def get_neural_embedding(text: str, model_name: str = "all-MiniLM-L6-v2") -> List[float]:
    """Lazy-loads SentenceTransformer model if USE_NEURAL_MODELS==1 environment variable is enabled."""
    global _neural_model_instance
    if os.getenv("USE_NEURAL_MODELS") == "1":
        try:
            if _neural_model_instance is None:
                os.environ["HF_HUB_OFFLINE"] = "1"
                os.environ["TRANSFORMERS_OFFLINE"] = "1"
                from sentence_transformers import SentenceTransformer
                _neural_model_instance = SentenceTransformer(model_name, local_files_only=True)
            return _neural_model_instance.encode(text).tolist()
        except Exception:
            pass
    return get_deterministic_vector(text)

@register_embedder("default")
@register_embedder("sentence_transformer")
def embed_sentence_transformer(text: str) -> List[float]:
    """Retrieves standard sentence-transformer embedding vectors with hashing fallback."""
    return get_neural_embedding(text)

@register_embedder("mock")
@register_embedder("deterministic")
def embed_mock_deterministic(text: str) -> List[float]:
    """Generates standard MD5-seeded deterministic mock vectors."""
    return get_deterministic_vector(text)

def embed(text: str, model: str = "default") -> List[float]:
    """Pluggable procedural entrypoint to obtain embeddings for a query or passage."""
    model_key = model if model in EMBEDDER_REGISTRY else "default"
    return EMBEDDER_REGISTRY[model_key](text)

# Bridge adapter pattern to maintain compatibility with OO pipeline references
@embedder_registry.register("mock")
@embedder_registry.register("pluggable")
@embedder_registry.register("deterministic")
class PluggableEmbedder(BaseEmbedder):
    """OO Interface wrapping the pluggable functional embedder."""
    
    def __init__(self, model_key: str = "default"):
        self.model_key = model_key
        
    def embed_query(self, text: str) -> List[float]:
        return embed(text, model=self.model_key)
        
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [embed(t, model=self.model_key) for t in texts]
