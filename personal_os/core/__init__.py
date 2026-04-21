"""Core module — data ingestion, vector storage, LLM gateway, file management, and orchestrator."""

from personal_os.core.exceptions import (
    BudgetExceededError,
    EmbeddingError,
    FileParsingError,
    IndexingError,
    LLMProviderError,
    PersonalOSError,
    SyncStateError,
    VaultNotFoundError,
)
from personal_os.core.file_manager import FileManager
from personal_os.core.llm_gateway import LLMGateway
from personal_os.core.orchestrator import QueryOrchestrator
from personal_os.core.parser import ObsidianParser, ParseResult
from personal_os.core.vector_store import QueryResult, VectorStoreManager

__all__: list[str] = [
    # Ingestion
    "ObsidianParser",
    "ParseResult",
    # Vector store
    "VectorStoreManager",
    "QueryResult",
    # File management
    "FileManager",
    # LLM
    "LLMGateway",
    "QueryOrchestrator",
    # Exceptions
    "PersonalOSError",
    "VaultNotFoundError",
    "FileParsingError",
    "SyncStateError",
    "IndexingError",
    "EmbeddingError",
    "BudgetExceededError",
    "LLMProviderError",
]
