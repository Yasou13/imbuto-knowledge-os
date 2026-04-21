"""
Query orchestrator — ties vector retrieval to LLM generation.

:class:`QueryOrchestrator` receives user questions, retrieves the most
relevant knowledge chunks from :class:`VectorStoreManager`, constructs a
strict RAG prompt, and delegates answer generation to :class:`LLMGateway`.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, NamedTuple, Optional

from personal_os.config.settings import Settings
from personal_os.core.exceptions import IndexingError, LLMProviderError
from personal_os.core.llm_gateway import LLMGateway
from personal_os.core.schemas import ContextSource
from personal_os.core.vector_store import QueryResult, VectorStoreManager

logger: logging.Logger = logging.getLogger("imbuto.orchestrator")

# ---------------------------------------------------------------------------
# RAG system prompt template
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT: str = (
    "You are a precise knowledge assistant. Answer the user's question "
    "using the contexts provided below.\n"
    "Prioritize the PRIMARY CONTEXT for specific questions about the open file, "
    "but use SECONDARY CONTEXT for broader connections.\n"
    "If the contexts do not contain enough information to answer, say so explicitly — "
    "do NOT make up facts.\n\n"
    "### Rules\n"
    "- Cite the source file name when referencing information.\n"
    "- Be concise and factual.\n"
    "- If multiple sources conflict, note the discrepancy.\n"
    "- Note that `[... omitted ...]` markers imply that irrelevant chunks of the original context were discarded to save tokens.\n"
)

_CHUNK_TEMPLATE: str = (
    "[Source: {source}]\n{content}\n"
)

# ---------------------------------------------------------------------------
# Model limit registry
# ---------------------------------------------------------------------------

MODEL_CONTEXT_LIMITS: dict[str, int] = {
    "openai/gpt-4o": 128000,
    "openai/gpt-4-turbo": 128000,
    "openai/gpt-3.5-turbo": 16385,
    "anthropic/claude-3-5-sonnet-20240620": 200000,
    "anthropic/claude-3-haiku-20240307": 200000,
    "gemini/gemini-1.5-flash": 1000000,
    "gemini/gemini-1.5-pro": 2000000,
    "groq/llama3-8b-8192": 8192,
    "ollama/llama3": 8192,
}


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


class AskResult(NamedTuple):
    """Structured return value from :meth:`QueryOrchestrator.ask`."""

    answer: str
    sources: List[ContextSource]


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class QueryOrchestrator:
    """End-to-end RAG query pipeline.

    Composes :class:`VectorStoreManager` (retrieval) with
    :class:`LLMGateway` (generation) behind a single ``ask()`` method.

    Args:
        settings: Injected application configuration.
        vector_store: An initialised (and entered) vector store manager.
        llm_gateway: An initialised LLM gateway instance.

    Example::

        settings = Settings()
        with VectorStoreManager(settings) as vs:
            gateway = LLMGateway(settings)
            orchestrator = QueryOrchestrator(settings, vs, gateway)
            result = orchestrator.ask("What is delta-sync?")
            logger.debug(result.answer, result.sources)
    """

    def __init__(
        self,
        settings: Settings,
        vector_store: VectorStoreManager,
        llm_gateway: LLMGateway,
    ) -> None:
        self._settings: Settings = settings
        self._vector_store: VectorStoreManager = vector_store
        self._llm: LLMGateway = llm_gateway

        logger.info("QueryOrchestrator initialised.")

    # -- public API --------------------------------------------------------

    def ask(
        self,
        query: str,
        model_name: str,
        n_results: Optional[int] = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
        workspace_id: Optional[str] = None,
        current_file_context: Optional[str] = None,
        cursor_position: int = 0,
    ) -> AskResult:
        """Answer a natural-language *query* using the RAG pipeline.

        Workflow:
            1. Retrieve the top-*n_results* chunks from the vector store.
            2. Assemble a RAG prompt with the retrieved context.
            3. Send the prompt to the LLM via the gateway.

        Args:
            query: The user's question in plain text.
            n_results: Number of context chunks to retrieve.
            temperature: LLM sampling temperature.
            max_tokens: Maximum tokens in the LLM response.
            workspace_id: If provided, restrict retrieval to chunks
                belonging to this workspace. Falls back to a global
                search when ``None``.

        Returns:
            :class:`AskResult` containing the LLM answer and the
            retrieved :class:`QueryResult` sources.

        Raises:
            IndexingError: If the vector store query fails.
            LLMProviderError: If the LLM call fails after fallback.
        """
        logger.info("Processing query: '%.80s…'", query)

        # Dynamic budget
        if n_results is None:
            max_context = MODEL_CONTEXT_LIMITS.get(model_name, 8192)
            reserve_tokens = 4000  # Sys prompt + direct context + max_tokens
            safe_budget_tokens = max(0, max_context - reserve_tokens)
            avg_chunk_tokens = 250
            dynamic_n = safe_budget_tokens // avg_chunk_tokens
            n_results = max(3, min(50, dynamic_n))
            logger.info("Dynamic n_results computed for model '%s': %d", model_name, n_results)

        # 1 — Retrieve
        results: List[QueryResult] = self._retrieve(query, n_results, workspace_id)

        if not results:
            logger.warning("No relevant context found for query.")
            return AskResult(
                answer=(
                    "I could not find any relevant information in the knowledge "
                    "base to answer your question."
                ),
                sources=[],
            )

        # 2 — Build prompt
        prompt: str = self._build_prompt(query, results, current_file_context, cursor_position)

        # 3 — Generate
        answer: str = self._generate(prompt, model_name, temperature, max_tokens)

        # 4 — Map raw QueryResults → ContextSource for the API layer
        sources: List[ContextSource] = self._map_sources(results)

        logger.info(
            "Query answered successfully (%d context chunks, %d char response).",
            len(results),
            len(answer),
        )
        return AskResult(answer=answer, sources=sources)

    # -- internals ---------------------------------------------------------

    def _retrieve(
        self,
        query: str,
        n_results: int,
        workspace_id: Optional[str] = None,
    ) -> List[QueryResult]:
        """Query the vector store for relevant chunks.

        Args:
            query: Search query.
            n_results: Maximum number of results.
            workspace_id: Optional workspace scope for filtering.

        Returns:
            List of :class:`QueryResult` objects, possibly empty.

        Raises:
            IndexingError: Propagated from the vector store.
        """
        try:
            results: List[QueryResult] = self._vector_store.query(
                text=query, n_results=n_results, workspace_id=workspace_id
            )
            logger.debug("Retrieved %d chunks for query.", len(results))
            return results
        except IndexingError:
            logger.exception("Vector store retrieval failed.")
            raise

    def _build_prompt(
        self, question: str, results: List[QueryResult], current_file_context: Optional[str] = None, cursor_position: int = 0
    ) -> str:
        """Assemble the user-facing RAG prompt with injected context.

        Args:
            question: The original user question.
            results: Retrieved context chunks.
            current_file_context: Content of the active file to serve as PRIMARY CONTEXT.

        Returns:
            Formatted prompt string ready for LLM consumption.
        """
        context_parts: List[str] = []
        for r in results:
            source: str = r.metadata.get("source_file", "unknown")
            context_parts.append(
                _CHUNK_TEMPLATE.format(source=source, content=r.content)
            )

        secondary_block = "\n".join(context_parts)
        
        prompt_parts = []
        prompt_parts.append("SYSTEM INSTRUCTION: You are an assistant for a IMBUTO OS. The user is currently editing a file. Prioritize the DIRECT CONTEXT for file-specific questions, but use SUPPORTING CONTEXT for broader knowledge connections.")

        if current_file_context:
            prompt_parts.append("\n--- DIRECT CONTEXT (ACTIVE FILE) ---")
            
            safe_primary = self._build_dynamic_file_context(current_file_context, cursor_position)
            prompt_parts.append(safe_primary)
            
            prompt_parts.append("\n--- SUPPORTING CONTEXT (VAULT MEMORY) ---")
        else:
            prompt_parts.append("\n--- SUPPORTING CONTEXT (VAULT MEMORY) ---")
            
        prompt_parts.append(secondary_block)
        prompt_parts.append("--- CONTEXT END ---\n")
        prompt_parts.append(f"Question: {question}")
        
        prompt: str = "\n".join(prompt_parts)

        logger.debug(
            "RAG prompt built — %d context chunks, %d chars total.",
            len(results),
            len(prompt),
        )
        return prompt

    @staticmethod
    def _build_dynamic_file_context(content: str, cursor_pos: int, max_chars: int = 16000) -> str:
        if len(content) <= max_chars:
            return content

        chunks = []
        start = 0
        blocks = content.split("\n\n")
        
        for block in blocks:
            end = start + len(block)
            chunks.append({"start": start, "end": end, "text": block, "selected": False})
            start = end + 2  # account for \n\n
            
        if not chunks:
            return content[:max_chars]

        cursor_idx = 0
        for i, c in enumerate(chunks):
            if c["start"] <= cursor_pos <= c["end"]:
                cursor_idx = i
                break

        chunks[0]["selected"] = True
        char_count = len(chunks[0]["text"])

        neighborhood = [cursor_idx - 1, cursor_idx, cursor_idx + 1]
        for idx in neighborhood:
            if 0 <= idx < len(chunks) and not chunks[idx]["selected"]:
                text_len = len(chunks[idx]["text"])
                if char_count + text_len <= max_chars:
                    chunks[idx]["selected"] = True
                    char_count += text_len

        unselected_indices = [i for i, c in enumerate(chunks) if not c["selected"]]
        if unselected_indices and char_count < max_chars:
            step = max(1, len(unselected_indices) // ((max_chars - char_count) // 1000 + 1))
            for i in range(0, len(unselected_indices), step):
                idx = unselected_indices[i]
                text_len = len(chunks[idx]["text"])
                if char_count + text_len <= max_chars:
                    chunks[idx]["selected"] = True
                    char_count += text_len

        result = []
        last_selected_idx = -1
        for i, c in enumerate(chunks):
            if c["selected"]:
                if last_selected_idx != -1 and i > last_selected_idx + 1:
                    result.append("[... omitted ...]")
                result.append(c["text"])
                last_selected_idx = i

        return "\n\n".join(result)

    @staticmethod
    def _map_sources(results: List[QueryResult]) -> List[ContextSource]:
        """Convert raw vector results into frontend-ready ContextSource models."""
        sources: List[ContextSource] = []
        for r in results:
            file_path = r.metadata.get(
                "file_path", r.metadata.get("source_file", "unknown")
            )
            file_name = (
                Path(file_path).name if file_path != "unknown" else "unknown"
            )
            # Normalise cosine distance (0-2) to a 0-1 similarity score
            similarity = max(0.0, 1.0 - (r.distance / 2.0))

            sources.append(ContextSource(
                file=file_name,
                source_file=str(file_path),
                content=r.content,
                chunk=r.content[:300],
                score=round(similarity, 4),
                distance=r.distance,
            ))
        return sources

    def _generate(
        self,
        prompt: str,
        model_name: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        """Send the assembled prompt to the LLM gateway.

        Args:
            prompt: Full RAG prompt.
            model_name: LiteLLM model identifier.
            temperature: Sampling temperature.
            max_tokens: Max response length.

        Returns:
            The model's answer string.

        Raises:
            LLMProviderError: Propagated from the gateway.
        """
        try:
            return self._llm.generate_answer(
                prompt=prompt,
                model_name=model_name,
                system_prompt=_SYSTEM_PROMPT,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except LLMProviderError:
            logger.exception("LLM generation failed.")
            raise
