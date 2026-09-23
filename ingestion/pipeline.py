"""Ingestion pipeline orchestration module.

Coordinated pipeline showing how files (PDF, CAD, Email) convert into chunks,
get embedded, and stored, and how graph nodes/edges are dynamically validated.
"""
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, List, Dict, Any, Optional
from core.registry import get_parser, embedder_registry, vector_store_registry, graph_store_registry
from core.schema import Recording, UnifiedDocument, Chunk, Node, Edge
from ingestion.chunker import chunk_document
from ingestion.manifest import discover_manifest
from ingestion.parsers.csv_daq_parser import (
    DEFAULT_QUARANTINE_LOG,
    NumericArrayLoadError,
    load_full_numeric_array,
    profile_file,
    write_quarantine_log,
)


WindowingHandler = Callable[[Recording, list[list[float]]], Any]


@dataclass(frozen=True)
class DAQIngestionSummary:
    """First-class accounting of a DAQ ingestion run."""

    discovered: int
    canonical: int
    quarantined: int
    quarantined_by_reason: dict[str, int]

    def as_dict(self) -> dict[str, Any]:
        return {
            "discovered": self.discovered,
            "canonical": self.canonical,
            "quarantined": self.quarantined,
            "quarantined_by_reason": dict(self.quarantined_by_reason),
        }


@dataclass
class DAQIngestionRun:
    """Records, windowing handoffs, and the integrity summary from one run."""

    summary: DAQIngestionSummary
    recordings: list[Recording]
    windowing_outputs: list[Any] = field(default_factory=list)


def _quarantine_reasons(recording: Recording) -> list[str]:
    """Exclude non-failure audit markers from the run-level rejection totals."""
    return [issue for issue in recording.quality_issues if issue != "null_bytes_removed"]


def _quarantine_after_full_load(
    recording: Recording, reason: str, quarantine_log_path: str
) -> None:
    """Convert a profile-pass into a quarantine if full numeric loading fails."""
    recording.schema_status = "quarantined"
    recording.row_count = None
    recording.channel_names = []
    recording.quality_issues.append(reason)
    write_quarantine_log(
        recording.source_path, recording.quality_issues, quarantine_log_path
    )


def ingest_daq_dataset(
    dataset_root: str,
    *,
    config_path: str = "config/domain.yaml",
    quarantine_log_path: str = str(DEFAULT_QUARANTINE_LOG),
    windowing_handler: Optional[WindowingHandler] = None,
    validate_full_numeric: bool = True,
    manifest: Optional[list[dict[str, Any]]] = None,
) -> DAQIngestionRun:
    """Run manifest → profile → optional full numeric load → windowing handoff.

    ``validate_full_numeric=False`` is intended for a fast, run-level profile:
    it avoids reading every canonical source twice. Full numeric validation is
    still required before any analysis/windowing and remains enabled by default.
    ``windowing_handler`` is the integration boundary for the future
    ``signal/windowing.py`` implementation.  It is called only after a complete
    numeric load succeeds; a missing handler still performs the full quality
    load but deliberately performs no feature or window computation.
    """
    # Supplying a previously discovered manifest lets API-level caching check
    # for source changes without walking the same 822-file tree a second time.
    manifest = manifest if manifest is not None else discover_manifest(dataset_root, config_path=config_path)
    recordings: list[Recording] = []
    windowing_outputs: list[Any] = []
    quarantined_by_reason: Counter[str] = Counter()

    for entry in manifest:
        recording = profile_file(
            entry["source_path"],
            condition_id=entry["condition_id"],
            quarantine_log_path=quarantine_log_path,
        )
        recordings.append(recording)

        if recording.schema_status == "quarantined":
            quarantined_by_reason.update(_quarantine_reasons(recording))
            continue

        if not validate_full_numeric:
            continue

        try:
            numeric_array = load_full_numeric_array(recording)
        except NumericArrayLoadError as exc:
            _quarantine_after_full_load(recording, str(exc), quarantine_log_path)
            quarantined_by_reason.update([str(exc)])
            continue

        if windowing_handler is not None:
            windowing_outputs.append(windowing_handler(recording, numeric_array))

    canonical_count = sum(
        recording.schema_status == "canonical" for recording in recordings
    )
    summary = DAQIngestionSummary(
        discovered=len(manifest),
        canonical=canonical_count,
        quarantined=len(manifest) - canonical_count,
        quarantined_by_reason=dict(sorted(quarantined_by_reason.items())),
    )
    return DAQIngestionRun(
        summary=summary,
        recordings=recordings,
        windowing_outputs=windowing_outputs,
    )

class IngestionPipeline:
    """Format-agnostic pipeline managing the ingestion flow:
    1. Parse source data bytes using the registered parser to produce a UnifiedDocument.
    2. Segment the document into standardized Chunk layers.
    3. Generate text embeddings using the registered Embedder.
    4. Store chunks in the active Vector Store.
    5. Validate and save extracted graph structure entities (Nodes, Edges) to the Graph DB.
    """
    
    def __init__(
        self, 
        embedder_key: str = "mock", 
        vector_store_key: str = "in_memory", 
        graph_store_key: str = "in_memory"
    ):
        # Resolve implementations from registration tables
        self.embedder = self._instantiate(embedder_registry.get(embedder_key))
        self.vector_store = self._instantiate(vector_store_registry.get(vector_store_key))
        self.graph_store = self._instantiate(graph_store_registry.get(graph_store_key))
        
    def _instantiate(self, cls_or_instance: Any) -> Any:
        """Helper to instantiate registered class references if not already objects."""
        if isinstance(cls_or_instance, type):
            return cls_or_instance()
        return cls_or_instance

    def ingest_file(
        self, 
        filename: str, 
        content_bytes: bytes, 
        parser_type: Optional[str] = None, 
        metadata: Optional[Dict[str, Any]] = None
    ) -> List[Chunk]:
        """Ingests raw file bytes, parses, chunks, embeds, and saves them."""
        # 1. Fetch parser plugin using filename extension, fallback to parser_type
        try:
            parser = get_parser(filename)
        except Exception:
            if parser_type:
                parser = get_parser(f"dummy.{parser_type}")
            else:
                raise
        
        # 2. Parse file into standard UnifiedDocument format
        doc: UnifiedDocument = parser.parse(filename, content_bytes, metadata)
        print(f"[Pipeline] Finished parsing '{filename}' as {doc.modality}")
        
        # 3. Create content Chunks
        chunks = chunk_document(doc)
        if not chunks:
            print(f"[Pipeline] Document '{filename}' generated no chunks (empty content).")
            return []
            
        print(f"[Pipeline] Generated {len(chunks)} chunks from '{filename}'")
        
        # 4. Generate embeddings
        chunk_texts = [chunk.text for chunk in chunks]
        embeddings = self.embedder.embed_documents(chunk_texts)
        
        # 5. Map vectors and insert to store
        for chunk, emb in zip(chunks, embeddings):
            chunk.embedding = emb
            
        self.vector_store.insert_chunks(chunks)
        return chunks


    def ingest_graph_elements(
        self, 
        nodes_raw: List[Dict[str, Any]], 
        edges_raw: List[Dict[str, Any]]
    ) -> None:
        """Validates and stores list of raw nodes and edges.
        
        Will raise validation errors if type matches do not conform to active
        entity_types or relation_types specified in config/domain.yaml.
        """
        validated_nodes = []
        for index, node_item in enumerate(nodes_raw):
            try:
                if isinstance(node_item, Node):
                    node = node_item
                else:
                    node = Node(**node_item)
                validated_nodes.append(node)
            except Exception as e:
                raise ValueError(
                    f"Ontology Validation Error at node index {index} (Data: {node_item}): {str(e)}"
                )
                
        validated_edges = []
        for index, edge_item in enumerate(edges_raw):
            try:
                if isinstance(edge_item, Edge):
                    edge = edge_item
                else:
                    edge = Edge(**edge_item)
                validated_edges.append(edge)
            except Exception as e:
                raise ValueError(
                    f"Ontology Validation Error at edge index {index} (Data: {edge_item}): {str(e)}"
                )
                
        # Insert validated nodes & edges into graph database
        self.graph_store.insert_nodes(validated_nodes)
        self.graph_store.insert_edges(validated_edges)
        print(f"[Pipeline] Successfully validated and loaded {len(validated_nodes)} Nodes & {len(validated_edges)} Edges.")
