"""Chunker module providing semantic character splitting and modality-specific overrides.

Ensures character-window chunking fallback while allowing code and custom modalities
to split on logical boundaries (e.g. double newlines for functions/classes).
"""
import uuid
from typing import List, Dict, Any, Callable, Union
from core.schema import UnifiedDocument, Chunk

CHUNK_STRATEGY_OVERRIDES: Dict[str, Callable] = {}

def register_chunk_strategy(modality: str):
    """Decorator to register a custom chunking strategy for a specific document modality."""
    def decorator(fn: Callable):
        CHUNK_STRATEGY_OVERRIDES[modality] = fn
        return fn
    return decorator

@register_chunk_strategy("code")
def chunk_code_strategy(doc_or_text: Union[UnifiedDocument, str], chunk_size: int = 500, overlap: int = 50) -> List[Chunk]:
    """Splits code files by logical double-newline markers (e.g. functions or classes) to keep code intact."""
    if isinstance(doc_or_text, UnifiedDocument):
        content = doc_or_text.raw_content or ""
        doc_id = doc_or_text.doc_id
        source_path = doc_or_text.source_path
        modality = doc_or_text.modality
        base_meta = doc_or_text.metadata or {}
    else:
        content = str(doc_or_text or "")
        doc_id = f"code_{uuid.uuid4().hex[:8]}"
        source_path = "code_snippet"
        modality = "code"
        base_meta = {}

    parts = content.split("\n\n")
    chunks = []
    index = 0
    for part in parts:
        stripped = part.strip()
        if not stripped:
            continue
        chunks.append(Chunk(
            chunk_id=f"{doc_id}_{index}",
            doc_id=doc_id,
            text=stripped,
            metadata={
                **base_meta,
                "chunk_index": index,
                "modality": modality,
                "strategy": "code_logical_split",
                "source_path": source_path
            }
        ))
        index += 1
    return chunks

def default_semantic_split(doc_or_text: Union[UnifiedDocument, str], chunk_size: int = 500, overlap: int = 50) -> List[Chunk]:
    """Sliding-window fallback character splitter for text-based content."""
    if isinstance(doc_or_text, UnifiedDocument):
        content = doc_or_text.raw_content or ""
        doc_id = doc_or_text.doc_id
        source_path = doc_or_text.source_path
        modality = doc_or_text.modality
        metadata = doc_or_text.metadata or {}
    else:
        content = str(doc_or_text or "")
        doc_id = f"doc_{uuid.uuid4().hex[:8]}"
        source_path = "unknown"
        modality = "text"
        metadata = {}

    chunks = []
    if not content.strip():
        return chunks
        
    start = 0
    index = 0
    
    while start < len(content):
        end = min(start + chunk_size, len(content))
        chunk_text = content[start:end]
        
        chunk_metadata = {
            "source_path": source_path,
            "modality": modality,
            "chunk_index": index,
            **metadata
        }
        
        chunk = Chunk(
            chunk_id=f"{doc_id}_{index}",
            doc_id=doc_id,
            text=chunk_text,
            metadata=chunk_metadata
        )
        chunks.append(chunk)
        
        index += 1
        if end == len(content):
            break
        start += (chunk_size - overlap)
        
    return chunks

def chunk_document(doc: UnifiedDocument, chunk_size: int = 500, overlap: int = 50) -> List[Chunk]:
    """Routes a UnifiedDocument by doc.modality to registered custom strategy or default sliding window."""
    if doc.modality in CHUNK_STRATEGY_OVERRIDES:
        strategy_fn = CHUNK_STRATEGY_OVERRIDES[doc.modality]
        try:
            return strategy_fn(doc, chunk_size=chunk_size, overlap=overlap)
        except TypeError:
            return strategy_fn(doc)
            
    return default_semantic_split(doc, chunk_size=chunk_size, overlap=overlap)
