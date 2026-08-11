"""Embedding registry and pluggable models interface.

Enables swapping of embedding pipelines without touching downstream stages.
"""
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
    """Generates a stable, content-dependent vector for matching queries during simulation."""
    hasher = hashlib.md5(text.encode("utf-8"))
    seed_val = int(hasher.hexdigest(), 16) % (2**32)
    rng = random.Random(seed_val)
    vec = [rng.uniform(-1, 1) for _ in range(dimension)]
    magnitude = sum(x * x for x in vec) ** 0.5
    if magnitude == 0:
        return [0.0] * dimension
    return [x / magnitude for x in vec]

# Try lazy loading SentenceTransformer if package exists and explicitly enabled
get_sentence_transformer_embedding = None
import os
if os.environ.get("USE_NEURAL_MODELS") == "1":
    try:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        from sentence_transformers import SentenceTransformer
        _model_cache = {}
        def _get_emb(text: str, model_name: str = "all-MiniLM-L6-v2") -> List[float]:
            if model_name not in _model_cache:
                _model_cache[model_name] = SentenceTransformer(model_name, local_files_only=True)
            return _model_cache[model_name].encode(text).tolist()
        get_sentence_transformer_embedding = _get_emb
    except (ImportError, Exception):
        get_sentence_transformer_embedding = None

@register_embedder("default")
@register_embedder("sentence_transformer")
def embed_sentence_transformer(text: str) -> List[float]:
    """Retrieves standard sentence-transformer embedding vectors with hashing fallback."""
    if get_sentence_transformer_embedding is not None:
        try:
            return get_sentence_transformer_embedding(text)
        except Exception:
            pass
    # Deterministic simulation fallback
    return get_deterministic_vector(text)

@register_embedder("mock")
def embed_mock_random(text: str) -> List[float]:
    """Generates standard mock vectors."""
    return get_deterministic_vector(text)

def embed(text: str, model: str = "default") -> List[float]:
    """Pluggable procedural entrypoint to obtain embeddings for a query or passage."""
    model_key = model if model in EMBEDDER_REGISTRY else "default"
    return EMBEDDER_REGISTRY[model_key](text)

# Bridge adapter pattern to maintain compatibility with OO pipeline references
@embedder_registry.register("mock")
@embedder_registry.register("pluggable")
class PluggableEmbedder(BaseEmbedder):
    """OO Interface wrapping the pluggable functional embedder."""
    
    def __init__(self, model_key: str = "default"):
        self.model_key = model_key
        
    def embed_query(self, text: str) -> List[float]:
        return embed(text, model=self.model_key)
        
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [embed(t, model=self.model_key) for t in texts]
