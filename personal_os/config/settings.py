"""
Application-wide configuration via Pydantic BaseSettings.

All tunable parameters (paths, model names, log levels) are centralized here
and injected into domain classes — nothing is hardcoded at the call site.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings
from personal_os.path_resolver import get_resource_path, get_user_data_path, get_user_config_path


def _default_base_dir() -> Path:
    """Resolve the user-data base directory.

    When frozen this returns ``~/.imbuto`` so that every relative path
    resolved against *base_dir* lands in persistent, writable storage
    rather than inside the read-only ``sys._MEIPASS`` bundle.
    """
    return get_user_data_path("")


class Settings(BaseSettings):
    """Central, injectable configuration for the Personal IMBUTO OS.

    Attributes:
        base_dir: Root directory of the project. Every relative path is
            resolved against this.
        vault_path: Absolute or relative path to the Obsidian vault
            containing Markdown files.
        chroma_persist_dir: Directory where ChromaDB stores its persistent
            data.
        chroma_collection_name: Name of the ChromaDB collection used for
            knowledge storage.
        embedding_model_name: HuggingFace / SentenceTransformers model
            identifier used for vector embeddings.
        sync_state_path: Path to the JSON file that tracks file
            modification timestamps for delta-sync.
        chunk_headers: Markdown header levels to split on, expressed as
            ``(marker, label)`` pairs.
        log_level: Python logging level string (DEBUG, INFO, WARNING,
            ERROR, CRITICAL).
        anthropic_api_key: Anthropic API key (``PKO_ANTHROPIC_API_KEY``).
        gemini_api_key: Google AI Studio API key (``PKO_GEMINI_API_KEY``).
        openai_api_key: OpenAI API key (``PKO_OPENAI_API_KEY``).
        deepseek_api_key: DeepSeek API key (``PKO_DEEPSEEK_API_KEY``).
        cohere_api_key: Cohere API key (``PKO_COHERE_API_KEY``).
        groq_api_key: Groq API key (``PKO_GROQ_API_KEY``).
        available_models: List of LiteLLM model identifiers the user
            can select from the UI.
        default_model: LiteLLM model identifier used by default.
        fallback_model: LiteLLM model identifier used when daily budget
            is exceeded.
        daily_budget_usd: Maximum daily spend (USD) before fallback.
        budget_state_path: Path to the JSON file tracking cumulative
            daily LLM costs.
    """

    base_dir: Path = Field(default_factory=_default_base_dir)

    vault_path: Path = Field(default_factory=lambda: get_user_data_path("data/vault"))
    chroma_persist_dir: Path = Field(default_factory=lambda: get_user_data_path("data/chroma_db"))
    chroma_collection_name: str = Field(default="knowledge_base")
    embedding_model_name: str = Field(default="paraphrase-multilingual-mpnet-base-v2")
    sync_state_path: Path = Field(default_factory=lambda: get_user_data_path("data/.sync_state.json"))

    chunk_headers: List[Tuple[str, str]] = Field(
        default=[("#", "H1"), ("##", "H2"), ("###", "H3")]
    )

    log_level: str = Field(default="INFO")

    # -- LLM Gateway -------------------------------------------------------

    anthropic_api_key: str = Field(default="")
    gemini_api_key: str = Field(default="")
    openai_api_key: str = Field(default="")
    deepseek_api_key: str = Field(default="")
    cohere_api_key: str = Field(default="")
    groq_api_key: str = Field(default="")

    available_models: List[str] = Field(
        default=[
            "groq/llama-3.3-70b-versatile",
            "groq/llama-3.1-8b-instant",
            "gemini/gemini-1.5-flash-latest",
            "anthropic/claude-3-5-sonnet-20240620",
            "openai/gpt-4o",
            "deepseek/deepseek-coder",
            "cohere/command-r-plus",
        ]
    )
    default_model: str = Field(default="groq/llama-3.3-70b-versatile")
    fallback_model: str = Field(default="groq/llama-3.1-8b-instant")
    daily_budget_usd: float = Field(default=0.50)
    budget_state_path: Path = Field(default_factory=lambda: get_user_data_path("data/.budget_state.json"))

    # -- validators --------------------------------------------------------

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = value.upper()
        if upper not in allowed:
            raise ValueError(
                f"log_level must be one of {allowed}, got '{value}'"
            )
        return upper

    # -- helpers -----------------------------------------------------------

    @property
    def resolved_vault_path(self) -> Path:
        """Return an absolute vault path, resolved against *base_dir*."""
        if self.vault_path.is_absolute():
            return self.vault_path
        return (self.base_dir / self.vault_path).resolve()

    @property
    def resolved_chroma_persist_dir(self) -> Path:
        """Return an absolute ChromaDB persistence path."""
        if self.chroma_persist_dir.is_absolute():
            return self.chroma_persist_dir
        return (self.base_dir / self.chroma_persist_dir).resolve()

    @property
    def resolved_sync_state_path(self) -> Path:
        """Return an absolute sync-state JSON path."""
        if self.sync_state_path.is_absolute():
            return self.sync_state_path
        return (self.base_dir / self.sync_state_path).resolve()

    @property
    def resolved_budget_state_path(self) -> Path:
        """Return an absolute budget-state JSON path."""
        if self.budget_state_path.is_absolute():
            return self.budget_state_path
        return (self.base_dir / self.budget_state_path).resolve()

    class Config:
        env_prefix: str = "PKO_"
        env_file: str = str(get_user_config_path(".env"))
        env_file_encoding: str = "utf-8"
        case_sensitive: bool = False
        extra: str = "ignore"
