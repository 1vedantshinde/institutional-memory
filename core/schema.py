"""Core document and graph schema.

UnifiedDocument, Chunk, Node, and Edge are the stable contracts for the pipeline.
"""
import uuid
import hashlib
from typing import Dict, Any, List, Literal, Optional
from pydantic import BaseModel, Field, model_validator

def _get_domain():
    """Lazy accessor function for DOMAIN to avoid circular import errors."""
    from core.config import DOMAIN
    return DOMAIN

def make_doc_id(modality: str, source_path: str) -> str:
    """Generates a stable, reproducible doc_id from modality and path using SHA-256."""
    hasher = hashlib.sha256()
    hasher.update(f"{modality}:{source_path}".encode("utf-8"))
    return hasher.hexdigest()

class UnifiedDocument(BaseModel):
    """Standard format for all ingested files in the pipeline."""
    doc_id: str
    modality: str
    source_path: str
    raw_content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)

class Chunk(BaseModel):
    """Standard unit of retrieval and embedding."""
    chunk_id: str
    doc_id: str
    text: str
    embedding: Optional[List[float]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Recording(BaseModel):
    """Metadata and quality status for one source DAQ CSV recording."""

    recording_id: str
    condition_id: str
    source_path: str
    checksum: str
    schema_status: Literal["canonical", "quarantined"]
    row_count: Optional[int] = None
    channel_names: List[str] = Field(default_factory=list)
    quality_issues: List[str] = Field(default_factory=list)


class Condition(BaseModel):
    """The S/F/D experimental setting under which recordings were captured."""

    condition_id: str
    S: float
    F: float
    D: float
    source_folder: str


class SignalWindow(BaseModel):
    """One channel-specific, sample-indexed window from a DAQ recording."""

    window_id: str
    recording_id: str
    channel: str
    sample_start: int
    sample_end: int
    time_start: Optional[float] = None
    time_end: Optional[float] = None
    feature_vector: Optional[List[float]] = None


class Finding(BaseModel):
    """A traceable analytics result, never a raw-model assertion."""

    finding_id: str
    recording_id: str
    window_id: Optional[str] = None
    finding_type: Literal["anomaly", "condition_deviation", "quality_flag"]
    score: float
    evidence: Dict[str, Any]
    model_version: str

class Node(BaseModel):
    """Graph Entity Node representation.
    
    Validated dynamically against the loaded DOMAIN configuration's entity types.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    type: str
    properties: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_type(self) -> 'Node':
        domain = _get_domain()
        valid_types = domain.entity_types
        if self.type not in valid_types:
            raise ValueError(
                f"Invalid entity type '{self.type}'. Must be one of configured entity types: {valid_types}"
            )
        return self

class Edge(BaseModel):
    """Graph Relationship representation.
    
    Validated dynamically against the loaded DOMAIN configuration's relation types.
    """
    source_id: str = ""
    target_id: str = ""
    source: Optional[str] = None
    target: Optional[str] = None
    type: str
    properties: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_type(self) -> 'Edge':
        if not self.source_id and self.source:
            self.source_id = self.source
        elif not self.source and self.source_id:
            self.source = self.source_id
            
        if not self.target_id and self.target:
            self.target_id = self.target
        elif not self.target and self.target_id:
            self.target = self.target_id

        domain = _get_domain()
        valid_relations = domain.relation_types
        if self.type not in valid_relations:
            raise ValueError(
                f"Invalid relation type '{self.type}'. Must be one of configured relation types: {valid_relations}"
            )
        return self
