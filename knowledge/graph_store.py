"""Generic graph store transaction operations.

Backed by real Neo4j when NEO4J_URI is set and the neo4j driver is installed,
falling back to an in-memory simulation otherwise. Both drivers expose the same
merge_node(), merge_edge(), get_neighbors(), nodes, and query() interface so
nothing else in the codebase needs to know which is active.
"""
import os
from typing import Any, List, Dict, Optional


class Neo4jSimulationDriver:
    """Driver simulating Neo4j Cypher MERGE semantics for entity and relationship nodes."""

    def __init__(self):
        self.nodes: Dict[str, Dict[str, Any]] = {}
        self.edges: List[Dict[str, Any]] = []

    def merge_node(self, label: str, key: str, value: str, props: dict) -> None:
        """Mimics MERGE (n:Label {key: value}) SET n += props, preventing node duplication."""
        node_key = str(value)
        if node_key in self.nodes:
            self.nodes[node_key]["properties"].update(props)
        else:
            self.nodes[node_key] = {
                "label": label,
                "key": key,
                "value": value,
                "properties": dict(props)
            }
        print(f"[Neo4j] MERGE (n:{label} {{{key}: '{value}'}}) SET n += {props}")

    def merge_edge(self, source: Any, target: Any, type: str) -> None:
        """Mimics MERGE (source)-[:TYPE]->(target), preventing duplicate edges."""
        source_id = source.id if hasattr(source, "id") else (source.name if hasattr(source, "name") else str(source))
        target_id = target.id if hasattr(target, "id") else (target.name if hasattr(target, "name") else str(target))

        for edge in self.edges:
            if edge["source_id"] == source_id and edge["target_id"] == target_id and edge["type"] == type:
                return

        self.edges.append({
            "source_id": source_id,
            "target_id": target_id,
            "type": type
        })
        print(f"[Neo4j] MERGE ({source_id}) -[:{type}]-> ({target_id})")

    def get_neighbors(self, entity_name: str) -> List[str]:
        """Query 1-hop connected relationships formatted as triplet strings."""
        neighbors = []
        for edge in self.edges:
            src = edge["source_id"]
            tgt = edge["target_id"]
            rel = edge["type"]
            if src == entity_name or tgt == entity_name:
                neighbors.append(f"{src} -[:{rel}]-> {tgt}")
        return neighbors

    def query(self, query_str: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """No-op stub for raw Cypher queries on the simulation driver."""
        return []


class Neo4jRealDriver:
    """Real Neo4j-backed driver — requires NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD env vars
    and the official 'neo4j' Python driver (pip install neo4j).

    Exposes the exact same interface as Neo4jSimulationDriver so all callers are unaffected.
    """

    def __init__(self):
        from neo4j import GraphDatabase
        uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        user = os.getenv("NEO4J_USER", "neo4j")
        password = os.getenv("NEO4J_PASSWORD", "testpassword")
        self._driver = GraphDatabase.driver(uri, auth=(user, password))

    def merge_node(self, label: str, key: str, value: str, props: dict) -> None:
        query = f"MERGE (n:`{label}` {{{key}: $value}}) SET n += $props"
        with self._driver.session() as session:
            session.run(query, value=value, props=props)
        print(f"[Neo4j] MERGE (n:{label} {{{key}: '{value}'}}) SET n += {props}")

    def merge_edge(self, source: Any, target: Any, type: str) -> None:
        source_id = getattr(source, "id", getattr(source, "name", str(source)))
        target_id = getattr(target, "id", getattr(target, "name", str(target)))
        query = (
            "MATCH (a {name: $source_id}), (b {name: $target_id}) "
            f"MERGE (a)-[:`{type}`]->(b)"
        )
        with self._driver.session() as session:
            session.run(query, source_id=source_id, target_id=target_id)
        print(f"[Neo4j] MERGE ({source_id}) -[:{type}]-> ({target_id})")

    def get_neighbors(self, entity_name: str) -> List[str]:
        query = (
            "MATCH (a {name: $name})-[r]-(b) "
            "RETURN a.name AS src, type(r) AS rel, b.name AS tgt"
        )
        with self._driver.session() as session:
            result = session.run(query, name=entity_name)
            return [f"{row['src']} -[:{row['rel']}]-> {row['tgt']}" for row in result]

    @property
    def nodes(self) -> Dict[str, Any]:
        """Compatibility shim for code that iterates neo4j.nodes.keys() (e.g. extract_entity_mentions).

        NOTE: Each access does a live DB round-trip. If query latency degrades as the graph grows,
        refactor extract_entity_mentions() to do a single Cypher query with WHERE a.name IN $candidates
        instead of pulling every node into Python for string-matching.
        """
        with self._driver.session() as session:
            result = session.run("MATCH (n) RETURN n.name AS name")
            return {row["name"]: {} for row in result if row["name"]}

    def query(self, query_str: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        with self._driver.session() as session:
            result = session.run(query_str, params or {})
            return [dict(record) for record in result]


def _build_neo4j_driver():
    """Instantiates real Neo4j driver if NEO4J_URI is set and neo4j package is installed,
    otherwise falls back to the in-memory simulation driver."""
    neo4j_uri = os.getenv("NEO4J_URI")
    if neo4j_uri:
        try:
            driver = Neo4jRealDriver()
            print(f"[GraphStore] Connected to real Neo4j at {neo4j_uri}")
            return driver
        except Exception as e:
            print(f"[GraphStore] Warning: real Neo4j unavailable ({e}), falling back to simulation.")
    return Neo4jSimulationDriver()


# Global driver instance — auto-selects real vs. simulation
neo4j = _build_neo4j_driver()


def write_entity(entity: Any) -> None:
    """Generic merge node transaction wrapper."""
    props = getattr(entity, "attrs", getattr(entity, "properties", {}))
    label = getattr(entity, "type", "Entity")
    name = getattr(entity, "name", getattr(entity, "id", str(entity)))
    neo4j.merge_node(
        label=label,
        key="name",
        value=name,
        props=props
    )

def write_relation(source_entity: Any, target_entity: Any, relation_type: str) -> None:
    """Generic merge relationship transaction wrapper."""
    neo4j.merge_edge(source_entity, target_entity, type=relation_type)

def link_chunk_to_entities(chunk: Any, entities: List[Any]) -> None:
    """Generic link to connect chunks to their extracted entities."""
    chunk_id = chunk.chunk_id if hasattr(chunk, "chunk_id") else str(chunk)
    for e in entities:
        e_id = getattr(e, "id", getattr(e, "name", str(e)))
        neo4j.merge_edge(chunk_id, e_id, type="MENTIONED_IN")
