"""Generic graph store transaction operations.

Simulates Neo4j Cypher MERGE semantics in-memory for entity and relation nodes,
and provides 1-hop neighbor triplet string formatting for RAG prompt augmentation.
"""
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
        
        # Check if identical edge already exists
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
        """Query 1-hop connected Neo4j relationships formatted as triplet strings.
        
        Exact output string format: "<Entity> -[:RELATION_TYPE]-> <Entity>"
        """
        neighbors = []
        for edge in self.edges:
            src = edge["source_id"]
            tgt = edge["target_id"]
            rel = edge["type"]
            if src == entity_name:
                neighbors.append(f"{src} -[:{rel}]-> {tgt}")
            elif tgt == entity_name:
                neighbors.append(f"{src} -[:{rel}]-> {tgt}")
        return neighbors

# Global driver instance
neo4j = Neo4jSimulationDriver()

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
