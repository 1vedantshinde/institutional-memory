"""Ingestion pipeline orchestration module.

Coordinated pipeline showing how files (PDF, CAD, Email) convert into chunks,
get embedded, and stored, and how graph nodes/edges are dynamically validated.
"""
from typing import List, Dict, Any, Optional
from core.registry import get_parser, embedder_registry, vector_store_registry, graph_store_registry
from core.schema import UnifiedDocument, Chunk, Node, Edge
from ingestion.chunker import chunk_document

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
        for index, node_dict in enumerate(nodes_raw):
            try:
                node = Node(**node_dict)
                validated_nodes.append(node)
            except Exception as e:
                raise ValueError(
                    f"Ontology Validation Error at node index {index} (Data: {node_dict}): {str(e)}"
                )
                
        validated_edges = []
        for index, edge_dict in enumerate(edges_raw):
            try:
                edge = Edge(**edge_dict)
                validated_edges.append(edge)
            except Exception as e:
                raise ValueError(
                    f"Ontology Validation Error at edge index {index} (Data: {edge_dict}): {str(e)}"
                )
                
        # Insert validated nodes & edges into graph database
        self.graph_store.insert_nodes(validated_nodes)
        self.graph_store.insert_edges(validated_edges)
        print(f"[Pipeline] Successfully validated and loaded {len(validated_nodes)} Nodes & {len(validated_edges)} Edges.")
