"""Neo4j-style graph storage with typed neighbor edges.

The in-memory simulation is the default and is what the DAQ provenance graph
uses. A real Neo4j backend is used for the module-level ``neo4j`` driver when
NEO4J_URI is set and the ``neo4j`` package is installed. Both expose the same
merge_node(), merge_edge(), get_neighbors(), get_neighbor_triplets(), nodes
and query() interface.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class GraphEdge:
    """A typed directed edge returned by provenance-neighbor queries."""

    source: str
    target: str
    type: str
    properties: dict[str, Any] = field(default_factory=dict)


def _node_id(node: Any) -> str:
    if hasattr(node, "id"):
        return str(node.id)
    if hasattr(node, "name"):
        return str(node.name)
    return str(node)


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
        candidate = GraphEdge(_node_id(source), _node_id(target), type, dict(properties or {}))
        key = self._edge_key(candidate)
        if key not in self._edge_keys:
            self._edge_keys.add(key)
            self.edges.append(candidate)
            self._adjacent.setdefault(candidate.source, []).append(candidate)
            if candidate.target != candidate.source:
                self._adjacent.setdefault(candidate.target, []).append(candidate)

    # Kept for callers that used the old static helper
    _node_id = staticmethod(_node_id)

    def get_neighbors(self, node_id: str) -> list[GraphEdge]:
        """Return one-hop incoming/outgoing edges as correctly typed objects."""
        return list(self._adjacent.get(node_id, []))

    def get_neighbor_triplets(self, node_id: str) -> list[str]:
        """``"<source> -[:TYPE]-> <target>"`` strings for prompt rendering."""
        return [f"{edge.source} -[:{edge.type}]-> {edge.target}" for edge in self.get_neighbors(node_id)]

    def query(self, query_str: str, params: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
        """Raw Cypher is not supported by the simulation; returns no rows."""
        return []


class Neo4jRealDriver:
    """Real Neo4j backend — needs NEO4J_URI (and NEO4J_USER / NEO4J_PASSWORD)
    plus the official ``neo4j`` package. Same interface as the simulation."""

    def __init__(self) -> None:
        from neo4j import GraphDatabase

        uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        user = os.getenv("NEO4J_USER", "neo4j")
        password = os.getenv("NEO4J_PASSWORD", "testpassword")
        self._driver = GraphDatabase.driver(uri, auth=(user, password))

    def merge_node(self, label: str, key: str, value: str, props: dict[str, Any]) -> None:
        query = f"MERGE (n:`{label}` {{{key}: $value}}) SET n += $props"
        with self._driver.session() as session:
            session.run(query, value=value, props=props)

    def merge_edge(
        self,
        source: Any,
        target: Any,
        type: str,
        properties: dict[str, Any] | None = None,
    ) -> None:
        query = (
            "MATCH (a {name: $source_id}), (b {name: $target_id}) "
            f"MERGE (a)-[r:`{type}`]->(b) SET r += $props"
        )
        with self._driver.session() as session:
            session.run(query, source_id=_node_id(source), target_id=_node_id(target), props=dict(properties or {}))

    def get_neighbors(self, node_id: str) -> list[GraphEdge]:
        query = (
            "MATCH (a {name: $name})-[r]-(b) "
            "RETURN startNode(r).name AS src, type(r) AS rel, endNode(r).name AS tgt, properties(r) AS props"
        )
        with self._driver.session() as session:
            return [
                GraphEdge(row["src"], row["tgt"], row["rel"], dict(row["props"] or {}))
                for row in session.run(query, name=node_id)
            ]

    def get_neighbor_triplets(self, node_id: str) -> list[str]:
        return [f"{edge.source} -[:{edge.type}]-> {edge.target}" for edge in self.get_neighbors(node_id)]

    @property
    def nodes(self) -> dict[str, Any]:
        """Compatibility shim for code that iterates ``neo4j.nodes`` (e.g. entity mention matching).

        Each access is a live round-trip; if that gets slow as the graph grows,
        match candidates in Cypher (``WHERE a.name IN $candidates``) instead.
        """
        with self._driver.session() as session:
            result = session.run("MATCH (n) RETURN n.name AS name")
            return {row["name"]: {} for row in result if row["name"]}

    def query(self, query_str: str, params: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
        with self._driver.session() as session:
            return [dict(record) for record in session.run(query_str, params or {})]


def _build_neo4j_driver() -> Neo4jSimulationDriver | Neo4jRealDriver:
    """Real Neo4j when NEO4J_URI is set and reachable, otherwise the simulation."""
    neo4j_uri = os.getenv("NEO4J_URI")
    if neo4j_uri:
        try:
            driver = Neo4jRealDriver()
            print(f"[GraphStore] Connected to real Neo4j at {neo4j_uri}")
            return driver
        except Exception as e:
            print(f"[GraphStore] Warning: real Neo4j unavailable ({e}), falling back to simulation.")
    return Neo4jSimulationDriver()


# Global driver for the document/knowledge graph. The DAQ provenance graph
# builds its own Neo4jSimulationDriver per analysis (see api/main.py).
neo4j = _build_neo4j_driver()


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
