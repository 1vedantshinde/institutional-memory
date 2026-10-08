"""Multi-Hop Knowledge Graph Traversal Engine (Step 3).

Expands outward from Step 1's extracted entities across the unified ontology relations:
People <-> Emails <-> CNC Components <-> Documentation <-> Processes <-> Sessions <-> Sensor Data <-> Events

Replaces the single-path router with multi-hop guided traversal with strict hop and size caps.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Union
from pydantic import BaseModel, Field

from core.schema import Chunk, Edge, Node
from knowledge.graph_store import GraphEdge, neo4j
from knowledge.provenance import Provenance, make_provenance
from retrieval.query_understanding import ExtractedEntity, QueryIntent, QueryUnderstandingResult


class GraphPath(BaseModel):
    """A linear multi-hop traversal trail through the knowledge graph."""

    nodes: List[str]
    edges: List[str]
    formatted: str
    hop_count: int

    def to_text(self) -> str:
        return self.formatted

    def __str__(self) -> str:
        return self.formatted


class Subgraph(BaseModel):
    """Subgraph extracted by multi-hop expansion around seed entities."""

    seed_node_ids: List[str] = Field(default_factory=list)
    nodes: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    edges: List[Dict[str, Any]] = Field(default_factory=list)
    paths: List[GraphPath] = Field(default_factory=list)
    triplets: List[str] = Field(default_factory=list)
    entities_by_type: Dict[str, List[str]] = Field(default_factory=dict)
    max_hops_reached: int = 0
    is_capped: bool = False
    provenance: Provenance = Field(
        default_factory=lambda: make_provenance("derived", extraction_method="graph_traversal")
    )

    def get_nodes_of_type(self, entity_type: str) -> List[str]:
        return self.entities_by_type.get(entity_type, [])

    def summary_lines(self) -> List[str]:
        """Human-readable formatted lines of traversal paths and triplets."""
        lines = []
        if self.paths:
            for p in self.paths:
                lines.append(f"Path ({p.hop_count} hops): {p.formatted}")
        else:
            for t in self.triplets:
                lines.append(f"Triplet: {t}")
        return lines


def _normalize_seed_id(seed: Union[Node, ExtractedEntity, str, Any]) -> str:
    """Extract string node identifier from diverse input types."""
    if isinstance(seed, str):
        return seed.strip()
    if hasattr(seed, "canonical_id") and seed.canonical_id:
        return str(seed.canonical_id).strip()
    if hasattr(seed, "id") and seed.id:
        return str(seed.id).strip()
    if hasattr(seed, "name") and seed.name:
        return str(seed.name).strip()
    return str(seed).strip()


def _infer_node_type(node_id: str, node_data: Optional[Dict[str, Any]] = None) -> str:
    """Infer the entity type from the node label or prefix convention."""
    if node_data and "label" in node_data and node_data["label"]:
        return str(node_data["label"])
    
    # Infer from prefix
    prefix = node_id.split(":")[0].lower() if ":" in node_id else ""
    prefix_map = {
        "component": "Component",
        "session": "Session",
        "condition": "Condition",
        "recording": "Recording",
        "window": "SignalWindow",
        "finding": "Finding",
        "event": "Event",
        "channel": "Channel",
        "fault": "Fault",
        "process": "Process",
        "parameter": "Parameter",
        "procedure": "Procedure",
        "concept": "Concept",
        "doc": "Document",
        "document": "Document",
        "person": "Person",
        "org": "Organization",
        "email": "Email",
        "thread": "EmailThread",
    }
    return prefix_map.get(prefix, "Entity")


def traverse(
    seed_entities: List[Union[Node, ExtractedEntity, str, Any]],
    max_hops: int = 2,
    max_nodes: int = 50,
    max_edges: int = 100,
    allowed_relations: Optional[Set[str]] = None,
    target_entity_types: Optional[Set[str]] = None,
    graph_driver: Optional[Any] = None,
    query_intent: Optional[Union[QueryIntent, str]] = None,
) -> Subgraph:
    """Traverse the knowledge graph outward from seed entities up to max_hops.

    Args:
        seed_entities: Starting nodes (e.g. [Component("Spindle")], ["session:42"], extracted entities).
        max_hops: Maximum BFS depth (default: 2).
        max_nodes: Maximum number of nodes to include in the resulting subgraph.
        max_edges: Maximum number of edges to collect.
        allowed_relations: Optional set of allowed relation types (e.g., {'MENTIONS', 'DOCUMENTS'}).
        target_entity_types: Optional set of entity types to focus traversal towards.
        graph_driver: Graph store driver (defaults to global neo4j).
        query_intent: Intent from Step 1 used to bias traversal priorities.

    Returns:
        Subgraph containing visited nodes, edges, multi-hop paths, and triplets.
    """
    driver = graph_driver or neo4j
    subgraph_nodes: Dict[str, Dict[str, Any]] = {}
    subgraph_edges: List[Dict[str, Any]] = []
    seen_edge_keys: Set[Tuple[str, str, str]] = set()
    triplets: List[str] = []
    seen_triplets: Set[str] = set()
    paths: List[GraphPath] = []
    entities_by_type: Dict[str, List[str]] = {}
    is_capped = False

    # 1. Normalize seed IDs
    seed_ids: List[str] = []
    for s in seed_entities:
        sid = _normalize_seed_id(s)
        if sid and sid not in seed_ids:
            seed_ids.append(sid)

    if not seed_ids:
        return Subgraph(
            seed_node_ids=[],
            provenance=make_provenance("derived", extraction_method="graph_traversal", confidence=1.0),
        )

    # 2. Initialize Seed Nodes in Subgraph
    # Frontier maps node_id -> list of partial paths leading to this node
    # Each path is a list of tuples: [(node_id_0), (edge_type_1, node_id_1), ...]
    current_frontier: Dict[str, List[List[Union[str, Tuple[str, str]]]]] = {}

    for sid in seed_ids:
        node_info = driver.get_node(sid) if hasattr(driver, "get_node") else None
        node_type = _infer_node_type(sid, node_info)
        subgraph_nodes[sid] = node_info or {"label": node_type, "value": sid, "properties": {}}
        entities_by_type.setdefault(node_type, []).append(sid)
        current_frontier[sid] = [[sid]]

    # 3. BFS Traversal Level by Level
    visited_nodes: Set[str] = set(seed_ids)
    actual_max_hops = 0

    for hop in range(1, max_hops + 1):
        if not current_frontier:
            break
        actual_max_hops = hop
        next_frontier: Dict[str, List[List[Union[str, Tuple[str, str]]]]] = {}

        for current_node, current_paths in current_frontier.items():
            if len(subgraph_nodes) >= max_nodes or len(subgraph_edges) >= max_edges:
                is_capped = True
                break

            # Fetch neighbor edges for current node
            neighbors: List[GraphEdge] = driver.get_neighbors(current_node)

            for edge in neighbors:
                if len(subgraph_edges) >= max_edges:
                    is_capped = True
                    break

                # Relation filter
                if allowed_relations and edge.type not in allowed_relations:
                    continue

                # Determine direction and neighbor node
                src, tgt, rel_type = edge.source, edge.target, edge.type
                neighbor_id = tgt if src == current_node else src

                # Formulate triplet
                triplet_str = f"{src} -[:{rel_type}]-> {tgt}"
                if triplet_str not in seen_triplets:
                    seen_triplets.add(triplet_str)
                    triplets.append(triplet_str)

                # Record edge
                edge_key = (src, tgt, rel_type)
                if edge_key not in seen_edge_keys:
                    seen_edge_keys.add(edge_key)
                    subgraph_edges.append({
                        "source": src,
                        "target": tgt,
                        "type": rel_type,
                        "properties": dict(edge.properties),
                    })

                # Register neighbor node in subgraph if new
                if neighbor_id not in subgraph_nodes:
                    if len(subgraph_nodes) >= max_nodes:
                        is_capped = True
                        break
                    n_info = driver.get_node(neighbor_id) if hasattr(driver, "get_node") else None
                    n_type = _infer_node_type(neighbor_id, n_info)
                    subgraph_nodes[neighbor_id] = n_info or {"label": n_type, "value": neighbor_id, "properties": {}}
                    entities_by_type.setdefault(n_type, []).append(neighbor_id)

                # Construct and extend traversal paths
                for p in current_paths:
                    # Check if neighbor already in path to avoid cycles
                    path_node_ids = [p[0]] + [step[1] for step in p[1:] if isinstance(step, tuple)]
                    if neighbor_id in path_node_ids:
                        continue

                    new_path = list(p) + [(rel_type, neighbor_id)]
                    next_frontier.setdefault(neighbor_id, []).append(new_path)

                    # Build GraphPath
                    full_nodes = [str(new_path[0])] + [step[1] for step in new_path[1:]]
                    full_edges = [step[0] for step in new_path[1:]]
                    formatted_steps = [str(full_nodes[0])] + [f"-[:{r}]-> {n}" for r, n in new_path[1:]]

                    paths.append(
                        GraphPath(
                            nodes=full_nodes,
                            edges=full_edges,
                            formatted=" ".join(formatted_steps),
                            hop_count=len(full_edges),
                        )
                    )

            if is_capped:
                break

        current_frontier = next_frontier
        visited_nodes.update(next_frontier.keys())
        if is_capped:
            break

    return Subgraph(
        seed_node_ids=seed_ids,
        nodes=subgraph_nodes,
        edges=subgraph_edges,
        paths=paths,
        triplets=triplets,
        entities_by_type=entities_by_type,
        max_hops_reached=actual_max_hops,
        is_capped=is_capped,
        provenance=make_provenance("derived", extraction_method="graph_traversal", confidence=1.0),
    )


def traverse_from_query(
    query_understanding: Union[str, QueryUnderstandingResult],
    max_hops: int = 2,
    max_nodes: int = 50,
    max_edges: int = 100,
    graph_driver: Optional[Any] = None,
) -> Subgraph:
    """Convenience traversal wrapper starting directly from Step 1's QueryUnderstandingResult or raw query."""
    if isinstance(query_understanding, str):
        qu_res = understand_query(query_understanding)
    else:
        qu_res = query_understanding

    return traverse(
        seed_entities=qu_res.seed_node_ids,
        max_hops=max_hops,
        max_nodes=max_nodes,
        max_edges=max_edges,
        graph_driver=graph_driver,
        query_intent=qu_res.intent,
    )


def subgraph_to_context_chunks(subgraph: Subgraph, max_chunks: int = 10) -> List[Chunk]:
    """Convert subgraph paths and triplets into standard Chunks for LLM prompt augmentation."""
    chunks: List[Chunk] = []

    # 1. Format multi-hop paths first
    for idx, path in enumerate(subgraph.paths[:max_chunks]):
        chunks.append(
            Chunk(
                chunk_id=f"graph_path_{idx}",
                doc_id="knowledge_graph",
                text=f"Graph Path ({path.hop_count} hops): {path.formatted}",
                metadata={
                    "modality": "graph",
                    "hop_count": path.hop_count,
                    "seed_nodes": subgraph.seed_node_ids,
                },
            )
        )

    # 2. Fall back to triplets if paths are empty but triplets exist
    if not chunks and subgraph.triplets:
        for idx, triplet in enumerate(subgraph.triplets[:max_chunks]):
            chunks.append(
                Chunk(
                    chunk_id=f"graph_triplet_{idx}",
                    doc_id="knowledge_graph",
                    text=f"Graph Context: {triplet}",
                    metadata={"modality": "graph"},
                )
            )

    return chunks
