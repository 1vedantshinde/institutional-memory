"""Core document and graph schema.

UnifiedDocument, Chunk, Node, and Edge are the stable contracts for the pipeline.
"""
from pydantic import BaseModel, Field, model_validator
from typing import Dict, Any, List, Optional
import uuid
import hashlib
from core.config import DOMAIN

def make_doc_id(modality: str, source_path: str) -> str:
    """Generates a stable, reproducible doc_id from modality and path."""
    hasher = hashlib.sha256()
    hasher.update(f"{modality}:{source_path}".encode("utf-8"))
    return hasher.hexdigest()

class UnifiedDocument(BaseModel):

    """Standard format for all ingested files in the pipeline.
    
    Whether it's PDF, CAD, Email, or Sensor log, the parser must return this
    representation to keep the downstream pipeline completely format-agnostic.
    """
    doc_id: str            # e.g. hash of (modality + filename) or uuid
    modality: str          # "text" | "code" | "audio" | "image" | "tabular" | ...
    source_path: str
    raw_content: str       # normalized text representation, regardless of original format
    metadata: Dict[str, Any] = Field(default_factory=dict)  # format-specific properties

class Chunk(BaseModel):
    """Standard unit of retrieval and embedding."""
    chunk_id: str
    doc_id: str
    text: str
    embedding: Optional[List[float]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)  # {page, timestamp, index, etc.}


class Node(BaseModel):
    """Graph Entity Node representation.
    
    Validated dynamically against the loaded DOMAIN configuration's entity types.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str  # e.g., "Pump-101"
    type: str  # Must match a type in DOMAIN.entity_types
    properties: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_type(self) -> 'Node':
        # Retrieve the current entity types from domain config
        valid_types = DOMAIN.entity_types
        if self.type not in valid_types:
            raise ValueError(
                f"Invalid entity type '{self.type}'. Must be one of configured entity types: {valid_types}"
            )
        return self

class Edge(BaseModel):
    """Graph Relationship representation.
    
    Validated dynamically against the loaded DOMAIN configuration's relation types.
    """
    source_id: str  # Identifier of source node
    target_id: str  # Identifier of target node
    type: str  # Must match a relation in DOMAIN.relation_types
    properties: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_type(self) -> 'Edge':
        # Retrieve current relation types from domain config
        valid_relations = DOMAIN.relation_types
        if self.type not in valid_relations:
            raise ValueError(
                f"Invalid relation type '{self.type}'. Must be one of configured relation types: {valid_relations}"
            )
        return self
