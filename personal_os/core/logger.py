"""
Structured logging for the IMBUTO ingestion pipeline.

Configures dual-output logging (file + stdout) and provides
:func:`log_ingestion_event` for safely serializing dictionary
payloads (raw input, validation errors, LLM output, etc.).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict

from personal_os.path_resolver import get_user_data_path

# ---------------------------------------------------------------------------
# Log directory & file
# ---------------------------------------------------------------------------

_LOG_DIR: Path = get_user_data_path("data/logs")
_LOG_FILE: Path = _LOG_DIR / "imbuto_ingestion.log"

_LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


def _ensure_log_dir() -> None:
    """Create the ``logs/`` directory at the project root if absent."""
    _LOG_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Logger factory
# ---------------------------------------------------------------------------

def get_logger(name: str = "imbuto.ingestion") -> logging.Logger:
    """Return a configured logger with file and stdout handlers.

    Args:
        name: Logger name (dot-separated hierarchy).

    Returns:
        A :class:`logging.Logger` instance writing to both
        ``logs/imbuto_ingestion.log`` and ``sys.stdout``.
    """
    _ensure_log_dir()

    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter(_LOG_FORMAT)

    # File handler.
    fh = logging.FileHandler(_LOG_FILE, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    # Stdout handler.
    sh = logging.StreamHandler()
    sh.setLevel(logging.INFO)
    sh.setFormatter(formatter)
    logger.addHandler(sh)

    return logger


# ---------------------------------------------------------------------------
# Structured event logger
# ---------------------------------------------------------------------------

def log_ingestion_event(event_type: str, details: Dict[str, Any]) -> None:
    """Serialize and log a structured ingestion event.

    Safely converts *details* to JSON, falling back to ``repr()`` for
    non-serializable values, ensuring the pipeline never crashes on a
    logging call.

    Args:
        event_type: Short label such as ``"raw_input"``,
            ``"validation_error"``, ``"llm_output"``,
            ``"confidence_score"``.
        details: Arbitrary dictionary payload to record.

    Example::

        log_ingestion_event("llm_output", {
            "model": "groq/llama-3.3-70b-versatile",
            "tokens": 312,
            "confidence": 0.91,
        })
    """
    logger = get_logger()

    try:
        payload: str = json.dumps(details, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        payload = repr(details)

    logger.info("[%s] %s", event_type, payload)
