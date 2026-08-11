"""LLM generation, grounding, citation, and confidence orchestration."""
from typing import List, Dict, Any, Optional
from core.registry import llm_registry, vector_store_registry, embedder_registry
from core.schema import Chunk
from llm.prompt_builder import build_system_prompt, build_user_prompt

class RAGOrchestrator:
    """Orchestrator coupling retrieval queries with dynamic generation.
    
    1. Computes Query Embedding.
    2. Executes similarity lookup on the registered Vector Store.
    3. Formats custom system prompts and document contexts with glossary mappings.
    4. Submits prompt payload to the active registered LLM.
    5. Formulates citation groundings to return to the caller.
    """
    
    def __init__(
        self, 
        llm_key: str = "mock", 
        embedder_key: str = "mock", 
        vector_store_key: str = "in_memory"
    ):
        # Instantiate objects from registries, handling class vs instance references
        self.llm = self._instantiate(llm_registry.get(llm_key))
        self.embedder = self._instantiate(embedder_registry.get(embedder_key))
        self.vector_store = self._instantiate(vector_store_registry.get(vector_store_key))
        
    def _instantiate(self, cls_or_instance: Any) -> Any:
        if isinstance(cls_or_instance, type):
            return cls_or_instance()
        return cls_or_instance
        
    def query(self, user_query: str, limit: int = 3, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Runs the semantic retrieval loop, prompts LLM, formats citations, and returns response."""
        # 1. Generate query embedding
        query_vector = self.embedder.embed_query(user_query)
        
        # 2. Retrieve matched passages
        chunks: List[Chunk] = self.vector_store.similarity_search(query_vector, k=limit, filters=filters)
        
        # 3. Assemble domain prompt templates
        system_prompt = build_system_prompt()
        user_prompt = build_user_prompt(user_query, chunks)
        
        # 4. Generate answer through the LLM plugin
        response_text = self.llm.generate(user_prompt, system_prompt=system_prompt)
        
        # 5. Build citations
        citations = []
        for chunk in chunks:
            citations.append({
                "doc_id": chunk.doc_id,
                "chunk_index": chunk.metadata.get("chunk_index", 0),
                "source_path": chunk.metadata.get("source_path", "Unknown"),
                "modality": chunk.metadata.get("modality", "Unknown"),
                "snippet": chunk.text[:150] + "..." if len(chunk.text) > 150 else chunk.text
            })
            
        return {
            "query": user_query,
            "answer": response_text,
            "system_prompt": system_prompt,
            "citations": citations
        }
