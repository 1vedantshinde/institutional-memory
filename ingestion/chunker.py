"""Chunker module.

Splits format-agnostic UnifiedDocument structures into standard retrieval Chunk segments.
"""
from typing import List
from core.schema import UnifiedDocument, Chunk

def chunk_document(doc: UnifiedDocument, chunk_size: int = 1000, chunk_overlap: int = 200) -> List[Chunk]:
    """Splits a UnifiedDocument's content into overlapping text chunks.
    
    Args:
        doc: The UnifiedDocument container.
        chunk_size: Target size in characters for each chunk.
        chunk_overlap: Overlapping characters between consecutive chunks.
        
    Returns:
        A list of generated Chunk objects.
    """
    content = doc.raw_content or ""
    metadata = doc.metadata or {}
    chunks = []
    
    if not content.strip():
        # Avoid creating chunks for empty documents
        return chunks
        
    start = 0
    index = 0
    
    while start < len(content):
        end = min(start + chunk_size, len(content))
        chunk_text = content[start:end]
        
        # Merge general document metadata with specific chunk contexts
        chunk_metadata = {
            "source_path": doc.source_path,
            "modality": doc.modality,
            "index": index,
            **metadata
        }
        
        chunk = Chunk(
            chunk_id=f"{doc.doc_id}_ch_{index}",
            doc_id=doc.doc_id,
            text=chunk_text,
            metadata=chunk_metadata
        )
        chunks.append(chunk)
        
        index += 1
        # Advance starting point by size minus overlap
        if end == len(content):
            break
        start += (chunk_size - chunk_overlap)

        
    return chunks
