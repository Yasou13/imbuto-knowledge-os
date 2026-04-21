"""
Pydantic schemas for the IMBUTO ingestion pipeline.

:class:`IMBUTONoteSchema` validates and normalizes every note before it enters
the vector store, enforcing type safety, tag conventions, and confidence
score bounds at the data layer.
"""

from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel, Field


class IMBUTONoteSchema(BaseModel):
    """Validated representation of a single IMBUTO knowledge note.

    Attributes:
        title: Auto-generated note title.
        flag: Categorical label for routing and filtering.
        tags: Lowercase, hyphen-separated classification tags
            (e.g. ``["rag-pipeline", "vector-db"]``).
        confidence_score: LLM self-assessed confidence in the
            extraction quality, constrained to ``[0.0, 1.0]``.
        summary: A concise, maximum two-sentence summary of the note.
        normalized_content: The final Markdown output ready for
            embedding and storage.
    """

    title: str = Field(
        ...,
        description="Auto-generated title for the note.",
    )
    flag: Literal[
        "backend",
        "frontend",
        "research",
        "prompt",
        "idea",
        "meeting",
        "architecture",
    ] = Field(
        ...,
        description="Categorical label for routing and filtering.",
    )
    tags: List[str] = Field(
        default_factory=list,
        description="Lowercase, hyphen-separated classification tags.",
    )
    confidence_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="LLM confidence in extraction quality (0.0–1.0).",
    )
    summary: str = Field(
        ...,
        max_length=300,
        description="Maximum two-sentence summary of the note.",
    )
    normalized_content: str = Field(
        ...,
        description="Final Markdown output for embedding and storage.",
    )


class ContextSource(BaseModel):
    """Single retrieved source chunk returned by the RAG pipeline.

    Used by both :class:`QueryOrchestrator` and the ``/api/query`` endpoint
    to represent a context document with similarity scoring.
    """

    file: str = ""
    content: str = ""
    chunk: str = ""
    source_file: str = ""
    score: float = 0.0
    distance: float = 0.0

