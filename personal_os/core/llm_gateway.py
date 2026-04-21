"""
LLM Gateway — unified multi-model API access with spend tracking.

Uses :mod:`litellm` for provider-agnostic LLM calls.  Daily cumulative cost
is persisted in a local JSON file.  Model selection is fully dynamic —
the caller passes the chosen ``model_name`` on every request.
"""

from __future__ import annotations

import uuid
import json
import threading
import logging
import os
from datetime import date
from pathlib import Path
from typing import Any, Dict, Optional

import litellm
from litellm import ModelResponse, completion
from litellm.exceptions import (
    APIConnectionError as LiteLLMConnectionError,
    APIError as LiteLLMAPIError,
    AuthenticationError as LiteLLMAuthError,
    RateLimitError as LiteLLMRateLimitError,
)

from personal_os.config.settings import Settings
from personal_os.core.exceptions import (
    LLMProviderError,
)
from personal_os.core.utils import atomic_json_write

logger: logging.Logger = logging.getLogger("imbuto.llm_gateway")

# Suppress litellm's own verbose logging by default.
litellm.suppress_debug_info = True


# ---------------------------------------------------------------------------
# Budget state persistence
# ---------------------------------------------------------------------------

class _BudgetState:
    """Tracks cumulative daily LLM spend in a JSON file.

    JSON schema::

        {
            "date": "YYYY-MM-DD",
            "total_cost_usd": 0.0012
        }

    If the stored date differs from today the counter resets automatically.

    Args:
        state_path: Absolute path to the ``.budget_state.json`` file.
    """

    def __init__(self, state_path: Path) -> None:
        self._path: Path = state_path
        self._lock: threading.Lock = threading.Lock()
        self._date: str = date.today().isoformat()
        self._total_cost: float = 0.0
        self._load()

    # -- persistence -------------------------------------------------------

    def _load(self) -> None:
        """Load state from disk; reset if the date has changed."""
        if not self._path.exists():
            logger.debug("Budget state file absent — starting at $0.00.")
            return

        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                raw: Dict[str, Any] = json.load(fh)

            stored_date: str = raw.get("date", "")
            if stored_date != self._date:
                logger.info(
                    "Budget date rolled over (%s → %s). Resetting cost.",
                    stored_date,
                    self._date,
                )
                self._total_cost = 0.0
            else:
                self._total_cost = float(raw.get("total_cost_usd", 0.0))
                logger.info(
                    "Budget state loaded — $%.4f spent today.",
                    self._total_cost,
                )
        except (json.JSONDecodeError, ValueError, OSError) as exc:
            logger.warning(
                "Corrupt budget state at %s — resetting. Error: %s",
                self._path,
                exc,
            )
            self._total_cost = 0.0

    def _save(self) -> None:
        """Persist the current state to disk atomically using atomic_json_write."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            atomic_json_write(self._path, {"date": self._date, "total_cost_usd": self._total_cost})
            logger.debug("Budget state saved — $%.4f.", self._total_cost)
        except OSError as exc:
            logger.error("Failed to save budget state: %s", exc)

    # -- public API --------------------------------------------------------

    @property
    def total_cost(self) -> float:
        """Current cumulative daily spend in USD."""
        with self._lock:
            return self._total_cost

    def add_cost(self, cost: float) -> None:
        """Record an additional *cost* (USD) and persist the update.

        Args:
            cost: Non-negative dollar amount to add.
        """
        if cost < 0:
            logger.warning("Ignoring negative cost: %.6f", cost)
            return
        with self._lock:
            self._total_cost += cost
            self._save()
            logger.debug(
                "Added $%.6f — daily total now $%.4f.", cost, self._total_cost
            )


# ---------------------------------------------------------------------------
# LLM Gateway
# ---------------------------------------------------------------------------

class LLMGateway:
    """Unified LLM interface with dynamic model routing.

    The caller selects the model on each request via the ``model_name``
    argument.  Daily spend is tracked but does **not** trigger automatic
    fallback — that logic lives in the UI layer.

    Args:
        settings: Injected :class:`Settings` instance carrying API keys
            and budget thresholds.

    Example::

        settings = Settings()
        gateway = LLMGateway(settings)
        answer = gateway.generate_answer("Explain RAG.", model_name="openai/gpt-4o")
    """

    def __init__(self, settings: Settings) -> None:
        self._settings: Settings = settings
        self._budget: _BudgetState = _BudgetState(
            settings.resolved_budget_state_path
        )

        # Push API keys into the environment so litellm picks them up.
        if settings.anthropic_api_key:
            os.environ["ANTHROPIC_API_KEY"] = settings.anthropic_api_key
        if settings.gemini_api_key:
            os.environ["GEMINI_API_KEY"] = settings.gemini_api_key
        if settings.openai_api_key:
            os.environ["OPENAI_API_KEY"] = settings.openai_api_key
        if settings.deepseek_api_key:
            os.environ["DEEPSEEK_API_KEY"] = settings.deepseek_api_key
        if settings.cohere_api_key:
            os.environ["COHERE_API_KEY"] = settings.cohere_api_key
        if settings.groq_api_key:
            os.environ["GROQ_API_KEY"] = settings.groq_api_key

        logger.info(
            "LLMGateway initialised — budget: $%.2f, available: %s.",
            settings.daily_budget_usd,
            settings.available_models,
        )
        logger.info(
            "Active providers in os.environ: %s",
            [k for k in os.environ if "API_KEY" in k],
        )

    # -- generation --------------------------------------------------------

    def generate_answer(
        self,
        prompt: str,
        model_name: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> str:
        """Send a prompt to the specified LLM and return the response text.

        Args:
            prompt: The user / human message content.
            model_name: LiteLLM model identifier (e.g. ``openai/gpt-4o``).
            system_prompt: Optional system-level instruction prepended to
                the conversation.
            temperature: Sampling temperature (0.0–1.0).
            max_tokens: Maximum tokens in the completion.

        Returns:
            The assistant's reply as a plain string.

        Raises:
            LLMProviderError: On authentication, connection, rate-limit, or
                any other unrecoverable API failure.
        """
        model: str = model_name

        messages: list[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        logger.info("Calling model '%s' (temp=%.1f, max_tokens=%d).", model, temperature, max_tokens)

        try:
            response: ModelResponse = completion(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except (LiteLLMAuthError,) as exc:
            raise LLMProviderError(
                f"Authentication failed for model '{model}'.",
                detail=str(exc),
            ) from exc
        except (LiteLLMRateLimitError,) as exc:
            raise LLMProviderError(
                f"Rate limit hit for model '{model}'.",
                detail=str(exc),
            ) from exc
        except (LiteLLMConnectionError,) as exc:
            raise LLMProviderError(
                f"Connection error for model '{model}'.",
                detail=str(exc),
            ) from exc
        except (LiteLLMAPIError, Exception) as exc:
            raise LLMProviderError(
                f"LLM API call failed for model '{model}'.",
                detail=str(exc),
            ) from exc

        # -- extract answer ------------------------------------------------
        answer: str = response.choices[0].message.content or ""

        # -- track cost ----------------------------------------------------
        response_cost: float = self._extract_cost(response, model)
        if response_cost > 0:
            self._budget.add_cost(response_cost)

        logger.info(
            "Model '%s' responded (%d chars). Cost: $%.6f. "
            "Daily total: $%.4f / $%.2f.",
            model,
            len(answer),
            response_cost,
            self._budget.total_cost,
            self._settings.daily_budget_usd,
        )

        return answer

    # -- cost extraction ---------------------------------------------------

    @staticmethod
    def _extract_cost(response: ModelResponse, model: str) -> float:
        """Attempt to extract per-request cost from the LiteLLM response.

        LiteLLM stores cost information in ``response._hidden_params``
        when available.  Falls back to ``litellm.completion_cost()`` if
        the hidden attribute is absent.

        Args:
            response: The raw :class:`ModelResponse`.
            model: The model identifier used for the request.

        Returns:
            Estimated cost in USD, or ``0.0`` if cost cannot be determined.
        """
        # Method 1: hidden params (most reliable when present).
        hidden: Dict[str, Any] = getattr(response, "_hidden_params", {}) or {}
        cost: Optional[float] = hidden.get("response_cost")
        if cost is not None and cost > 0:
            return float(cost)

        # Method 2: litellm helper.
        try:
            computed: float = litellm.completion_cost(
                completion_response=response, model=model
            )
            if computed > 0:
                return computed
        except Exception:
            logger.debug(
                "litellm.completion_cost() failed for model '%s'.", model
            )

        return 0.0

    # -- diagnostics -------------------------------------------------------

    def get_budget_status(self) -> Dict[str, Any]:
        """Return a snapshot of today's budget consumption.

        Returns:
            Dictionary with ``spent_usd``, ``budget_usd``, and
            ``remaining_usd`` keys.
        """
        spent: float = self._budget.total_cost
        budget: float = self._settings.daily_budget_usd
        return {
            "spent_usd": round(spent, 6),
            "budget_usd": budget,
            "remaining_usd": round(max(budget - spent, 0.0), 6),
        }
