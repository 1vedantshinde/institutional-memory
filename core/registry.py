"""Plugin registration mechanism.

Enables decoupling core pipeline orchestration from domain-specific or
technology-specific implementations (e.g., Qdrant vs custom C++ retrieval,
or PDF vs CAD parsers).
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Callable, Type, List, TypeVar, Generic, Optional
from core.schema import UnifiedDocument, Chunk, Node, Edge

T = TypeVar('T')

class Registry(Generic[T]):
    """Generic registry class for components."""
    
    def __init__(self, name: str):
        self.name = name
        self._items: Dict[str, T] = {}
        
    def register(self, name: str) -> Callable[[T], T]:
        """Decorator to register a component under a specified name."""
        def decorator(item: T) -> T:
            self._items[name.lower()] = item
            return item
        return decorator
        
    def get(self, name: str) -> T:
        """Retrieve a registered component by its key."""
        key = name.lower()
        if key not in self._items:
            raise KeyError(
                f"'{name}' is not registered in the {self.name} registry. "
                f"Registered implementations: {self.list_registered()}"
            )
        return self._items[key]
        
    def list_registered(self) -> List[str]:
        """List all registered component names."""
        return list(self._items.keys())


# --- Base Interfaces for Plugins ---

class BaseParser(ABC):
    """Abstract base class that all ingestion parsers must implement."""
    
    @abstractmethod
    def parse(self, filename: str, content_bytes: bytes, metadata: Optional[Dict[str, Any]] = None) -> UnifiedDocument:
        """Parse raw content bytes into a standard UnifiedDocument.
        
        Args:
            filename: The name or path of the document (e.g., 'document.pdf').
            content_bytes: The raw content of the document.
            metadata: Optional dictionary containing additional source metadata.
            
        Returns:
            A UnifiedDocument containing extracted text content.
        """
        pass


class BaseEmbedder(ABC):
    """Abstract base class that all text embedder models must implement."""
    
    @abstractmethod
    def embed_query(self, text: str) -> List[float]:
        """Convert a query string into a dense vector embedding."""
        pass
        
    @abstractmethod
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Convert a list of text strings into corresponding dense vector embeddings."""
        pass


class BaseVectorStore(ABC):
    """Abstract base class that all Vector databases must implement."""
    
    @abstractmethod
    def insert_chunks(self, chunks: List[Chunk]) -> None:
        """Insert a list of document Chunk schemas (with embeddings) into the vector store."""
        pass
        
    @abstractmethod
    def similarity_search(self, query_embedding: List[float], k: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Chunk]:
        """Query similar chunks from the vector store using cosine or dot-product similarity.
        
        Args:
            query_embedding: The dense query vector.
            k: The number of neighbors to retrieve.
            filters: Key-value metadata filtering conditions.
            
        Returns:
            A list of matching Chunk objects.
        """
        pass


class BaseGraphStore(ABC):
    """Abstract base class that all Graph databases (e.g. Neo4j) must implement."""
    
    @abstractmethod
    def insert_nodes(self, nodes: List[Node]) -> None:
        """Insert a list of validated Node entities into the graph."""
        pass
        
    @abstractmethod
    def insert_edges(self, edges: List[Edge]) -> None:
        """Insert a list of validated Edge relationships into the graph."""
        pass
        
    @abstractmethod
    def query(self, query_str: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Execute a graph query (e.g. Cypher statement)."""
        pass


class BaseLLM(ABC):
    """Abstract base class that all LLM backends must implement."""
    
    @abstractmethod
    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Generate text response using the selected LLM.
        
        Args:
            prompt: User question or constructed context prompt.
            system_prompt: System guidelines/domain instructions.
            
        Returns:
            The generated response string.
        """
        pass


class UnsupportedFormatError(Exception):
    """Raised when no parser exists for a specific file format."""
    pass

# Global registry mappings
PARSER_REGISTRY: Dict[str, Type[BaseParser]] = {}

def register_parser(*extensions: str) -> Callable[[Type[BaseParser]], Type[BaseParser]]:
    """Decorator to register a parser class for one or more file extensions."""
    def decorator(cls: Type[BaseParser]) -> Type[BaseParser]:
        for ext in extensions:
            PARSER_REGISTRY[ext.lower()] = cls
        return cls
    return decorator

def get_parser(file_path: str) -> BaseParser:
    """Retrieves an instantiated parser registered for the given file's extension."""
    ext = file_path.split(".")[-1].lower()
    if ext not in PARSER_REGISTRY:
        raise UnsupportedFormatError(
            f"No parser registered for .{ext}. Registered parsers: {list(PARSER_REGISTRY.keys())}"
        )
    return PARSER_REGISTRY[ext]()

embedder_registry: Registry[Type[BaseEmbedder]] = Registry("Embedder")
vector_store_registry: Registry[Type[BaseVectorStore]] = Registry("VectorStore")
graph_store_registry: Registry[Type[BaseGraphStore]] = Registry("GraphStore")
llm_registry: Registry[Type[BaseLLM]] = Registry("LLM")



# --- Out-of-the-Box Mock / In-Memory Implementations for Testing ---

@graph_store_registry.register("in_memory")
class InMemoryGraphStore(BaseGraphStore):
    """A light in-memory Graph Store for testing ontology validation."""
    
    def __init__(self):
        self.nodes: Dict[str, Node] = {}
        self.edges: List[Edge] = []
        
    def insert_nodes(self, nodes: List[Node]) -> None:
        for node in nodes:
            # Automatic validation triggers during model construction
            self.nodes[node.id] = node
        print(f"[InMemoryGraphStore] Inserted {len(nodes)} nodes successfully.")
        
    def insert_edges(self, edges: List[Edge]) -> None:
        for edge in edges:
            self.edges.append(edge)
        print(f"[InMemoryGraphStore] Inserted {len(edges)} edges successfully.")
        
    def query(self, query_str: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        print(f"[InMemoryGraphStore] Query: {query_str} with {params}")
        return []


@llm_registry.register("mock")
class MockLLM(BaseLLM):
    """Mock LLM returning standard generated answers."""
    
    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        return f"[Mock LLM Response] Answer to query based on prompt size {len(prompt)}"
