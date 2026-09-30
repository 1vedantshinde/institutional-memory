"""In-memory Neo4j-style graph storage with typed neighbor edges."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class GraphEdge:
    """A typed directed edge returned by provenance-neighbor queries."""

    source: str
    target: str
    type: str
    properties: dict[str, Any] = field(default_factory=dict)


class Neo4jSimulationDriver:
    """Simulate Neo4j ``MERGE`` semantics for nodes and typed relationships."""

    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: list[GraphEdge] = []
        # Hash indexes: MERGE dedupe and neighbor lookup were linear scans of
        # ``edges``, making graph builds O(n²) (≈200 s for ~24k windows).
        self._edge_keys: set[tuple[str, str, str, str]] = set()
        self._adjacent: dict[str, list[GraphEdge]] = {}

    @staticmethod
    def _edge_key(edge: GraphEdge) -> tuple[str, str, str, str]:
        # Same identity as GraphEdge equality, including properties
        return (edge.source, edge.target, edge.type, json.dumps(edge.properties, sort_keys=True, default=str))

    def merge_node(self, label: str, key: str, value: str, props: dict[str, Any]) -> None:
        """MERGE a node identity and update its properties without duplication."""
        node_id = str(value)
        if node_id in self.nodes:
            self.nodes[node_id]["properties"].update(props)
        else:
            self.nodes[node_id] = {
                "label": label,
                "key": key,
                "value": value,
                "properties": dict(props),
            }

    def merge_edge(
        self,
        source: Any,
        target: Any,
        type: str,
        properties: dict[str, Any] | None = None,
    ) -> None:
        """MERGE a directed typed edge without creating duplicates."""
        candidate = GraphEdge(
            self._node_id(source), self._node_id(target), type, dict(properties or {})
        )
        key = self._edge_key(candidate)
        if key not in self._edge_keys:
            self._edge_keys.add(key)
            self.edges.append(candidate)
            self._adjacent.setdefault(candidate.source, []).append(candidate)
            if candidate.target != candidate.source:
                self._adjacent.setdefault(candidate.target, []).append(candidate)

    @staticmethod
    def _node_id(node: Any) -> str:
        if hasattr(node, "id"):
            return str(node.id)
        if hasattr(node, "name"):
            return str(node.name)
        return str(node)

    def get_neighbors(self, node_id: str) -> list[GraphEdge]:
        """Return one-hop incoming/outgoing edges as correctly typed objects."""
        return list(self._adjacent.get(node_id, []))

    def get_neighbor_triplets(self, node_id: str) -> list[str]:
        """Compatibility formatter for legacy prompt rendering code."""
        return [
            f"{edge.source} -[:{edge.type}]-> {edge.target}"
            for edge in self.get_neighbors(node_id)
        ]


neo4j = Neo4jSimulationDriver()


def write_entity(entity: Any) -> None:
    """Generic merge node transaction wrapper retained for legacy callers."""
    props = getattr(entity, "attrs", getattr(entity, "properties", {}))
    label = getattr(entity, "type", "Entity")
    name = getattr(entity, "name", getattr(entity, "id", str(entity)))
    neo4j.merge_node(label=label, key="name", value=name, props=props)


def write_relation(source_entity: Any, target_entity: Any, relation_type: str) -> None:
    """Generic merge relationship transaction wrapper retained for legacy callers."""
    neo4j.merge_edge(source_entity, target_entity, type=relation_type)


def link_chunk_to_entities(chunk: Any, entities: list[Any]) -> None:
    """Legacy chunk relationship helper retained without altering DAQ ontology."""
    chunk_id = chunk.chunk_id if hasattr(chunk, "chunk_id") else str(chunk)
    for entity in entities:
        entity_id = getattr(entity, "id", getattr(entity, "name", str(entity)))
        neo4j.merge_edge(chunk_id, entity_id, type="MENTIONED_IN")
