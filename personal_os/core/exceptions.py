"""
Custom exception hierarchy for the Personal IMBUTO OS.

Every domain-specific failure is represented by a dedicated exception class
inheriting from :class:`PersonalOSError`, enabling fine-grained ``try/except``
handling without ever catching overly broad built-in types.
"""

from __future__ import annotations


class PersonalOSError(Exception):
    """Base exception for all Personal IMBUTO OS errors.

    Args:
        message: Human-readable error description.
        detail: Optional machine-readable context (paths, codes, etc.).
    """

    def __init__(self, message: str, detail: str | None = None) -> None:
        self.detail: str | None = detail
        super().__init__(message)


class VaultNotFoundError(PersonalOSError):
    """Raised when the configured vault directory does not exist or is
    inaccessible."""


class FileParsingError(PersonalOSError):
    """Raised when a Markdown file cannot be read or split into chunks."""


class SyncStateError(PersonalOSError):
    """Raised when the delta-sync state file is corrupt, unreadable, or
    cannot be written."""


class IndexingError(PersonalOSError):
    """Raised when a ChromaDB upsert, delete, or batch operation fails."""


class EmbeddingError(PersonalOSError):
    """Raised when the SentenceTransformer model fails to load or encode."""


class BudgetExceededError(PersonalOSError):
    """Raised when the daily LLM spending budget has been exhausted and no
    fallback model is available."""


class LLMProviderError(PersonalOSError):
    """Raised when the LLM provider returns an unrecoverable error
    (authentication failure, rate limit, network timeout, etc.)."""
