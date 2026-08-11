import uuid
from typing import List, Dict, Any, Callable
from core.schema import UnifiedDocument, Chunk

CHUNK_STRATEGY_OVERRIDES: Dict[str, Callable] = {}

def register_chunk_strategy(modality: str):
    """Decorator to register a custom chunking strategy for a specific document modality."""
    def decorator(fn: Callable):
        CHUNK_STRATEGY_OVERRIDES[modality] = fn
        return fn
    return decorator

@register_chunk_strategy("code")
def chunk_code_strategy(doc: UnifiedDocument, chunk_size: int = 500, overlap: int = 50) -> List[Chunk]:
    """Splits code files by logical double-newline markers (e.g. functions or classes)."""
    parts = doc.raw_content.split("\n\n")
    chunks = []
    for i, part in enumerate(parts):
        if not part.strip():
            continue
        chunks.append(Chunk(
            chunk_id=f"{doc.doc_id}_{i}",
            doc_id=doc.doc_id,
            text=part.strip(),
            metadata={
                **doc.metadata,
                "chunk_index": i,
                "modality": doc.modality,
                "strategy": "code_logical_split",
                "source_path": doc.source_path
            }
        ))
    return chunks

def default_semantic_split(doc: UnifiedDocument, chunk_size: int = 500, overlap: int = 50) -> List[Chunk]:
    """Fallback character-count character splitter for text-based content."""
    content = doc.raw_content or ""
    metadata = doc.metadata or {}
    chunks = []
    
    if not content.strip():
        return chunks
        
    start = 0
    index = 0
    
    while start < len(content):
        end = min(start + chunk_size, len(content))
        chunk_text = content[start:end]
        
        chunk_metadata = {
            "source_path": doc.source_path,
            "modality": doc.modality,
            "chunk_index": index,
            **metadata
        }
        
        chunk = Chunk(
            chunk_id=f"{doc.doc_id}_{index}",
            doc_id=doc.doc_id,
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
    """Splits a UnifiedDocument's content into standard retrieval Chunk segments.
    
    Checks if a custom modality strategy is registered, fallback to character splitting.
    """
    if doc.modality in CHUNK_STRATEGY_OVERRIDES:
        strategy_fn = CHUNK_STRATEGY_OVERRIDES[doc.modality]
        try:
            return strategy_fn(doc, chunk_size=chunk_size, overlap=overlap)
        except TypeError:
            return strategy_fn(doc)
            
    return default_semantic_split(doc, chunk_size, overlap)

