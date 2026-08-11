"""Generic graph store transaction operations.

Backs generic and parameter-based graph writes without hardcoded ontologies.
"""
from typing import Any, List

class Neo4jSimulationDriver:
    """Driver simulating Neo4j Cypher merges for entity and relation nodes."""
    
    def __init__(self):
        self.nodes = {}
        self.edges = []
        
    def merge_node(self, label: str, key: str, value: str, props: dict) -> None:
        self.nodes[value] = {
            "label": label,
            "key": key,
            "value": value,
            "properties": props
        }
        print(f"[Neo4j] MERGE (n:{label} {{{key}: '{value}'}}) SET n += {props}")
        
    def merge_edge(self, source: Any, target: Any, type: str) -> None:
        source_id = source.id if hasattr(source, "id") else (source.name if hasattr(source, "name") else str(source))
        target_id = target.id if hasattr(target, "id") else (target.name if hasattr(target, "name") else str(target))
        
        self.edges.append({
            "source_id": source_id,
            "target_id": target_id,
            "type": type
        })
        print(f"[Neo4j] MERGE ({source_id}) -[:{type}]-> ({target_id})")

# Global driver instance
neo4j = Neo4jSimulationDriver()

def write_entity(entity: Any) -> None:
    """Generic merge node transaction wrapper."""
    # Handle various possible attribute name mappings (attrs or properties)
    props = getattr(entity, "attrs", getattr(entity, "properties", {}))
    neo4j.merge_node(
        label=entity.type,
        key="name",
        value=entity.name,
        props=props
    )

def write_relation(source_entity: Any, target_entity: Any, relation_type: str) -> None:
    """Generic merge relationship transaction wrapper."""
    neo4j.merge_edge(source_entity, target_entity, type=relation_type)

def link_chunk_to_entities(chunk: Any, entities: List[Any]) -> None:
    """Generic link to connect chunks to their extracted entities."""
    for e in entities:
        neo4j.merge_edge(chunk.chunk_id, e.id, type="MENTIONED_IN")
