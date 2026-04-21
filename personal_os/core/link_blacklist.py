"""
Link blacklist — thread-safe JSON persistence for ignored graph edges.

Stores pairs of vault-relative paths that the user has manually dismissed
from the graph view.  The backing file is ``ignored_links.json`` located
alongside the ChromaDB persistence directory.
"""

from __future__ import annotations

import uuid
from filelock import FileLock
import json
import logging
import os
import threading
from pathlib import Path
from typing import FrozenSet, List, Set

from personal_os.core.utils import atomic_json_write

logger = logging.getLogger("imbuto.blacklist")

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_LOCK = threading.Lock()
_blacklist: Set[FrozenSet[str]] = set()
_file_path: Path | None = None


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


def init(data_dir: Path) -> None:
    """Set the backing file path and load existing data.

    *data_dir* should be the project ``data/`` directory (same parent as
    ``chroma_db/``).
    """
    global _file_path
    _file_path = data_dir / "ignored_links.json"
    _load()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def is_blacklisted(pair: FrozenSet[str]) -> bool:
    """Return ``True`` if *pair* is on the blacklist."""
    with _LOCK:
        return pair in _blacklist


def add_pair(source: str, target: str) -> None:
    """Add a ``(source, target)`` pair to the blacklist and persist."""
    pair = frozenset({source, target})
    with _LOCK:
        _blacklist.add(pair)
        _save()
    logger.info("Blacklisted edge: %s ↔ %s", source, target)


def remove_pair(source: str, target: str) -> None:
    """Remove a ``(source, target)`` pair from the blacklist and persist."""
    pair = frozenset({source, target})
    with _LOCK:
        _blacklist.discard(pair)
        _save()
    logger.info("Un-blacklisted edge: %s ↔ %s", source, target)


def get_all() -> List[List[str]]:
    """Return all blacklisted pairs as sorted two-element lists."""
    return [sorted(p) for p in _blacklist]


# ---------------------------------------------------------------------------
# Internal I/O
# ---------------------------------------------------------------------------


def _load() -> None:
    """Read the JSON file into the in-memory set."""
    global _blacklist
    if _file_path is None or not _file_path.exists():
        _blacklist = set()
        return

    try:
        with open(_file_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        pairs = data.get("pairs", [])
        _blacklist = {frozenset(p) for p in pairs if isinstance(p, list) and len(p) == 2}
        logger.info("Loaded %d blacklisted edge(s) from %s", len(_blacklist), _file_path)
    except Exception as exc:
        logger.warning("Failed to load blacklist file %s: %s", _file_path, exc)
        _blacklist = set()


def _save() -> None:
    """Write the in-memory set to the JSON file atomically (caller must hold _LOCK)."""
    if _file_path is None:
        return
    try:
        _file_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"pairs": [sorted(p) for p in _blacklist]}
        atomic_json_write(str(_file_path), payload)
    except Exception as exc:
        logger.error("Failed to save blacklist file %s: %s", _file_path, exc)
