"""
Incremental sync-state tracker for the IMBUTO ingestion pipeline.

:class:`SyncTracker` persists per-file SHA-256 hashes and associated
``note_id`` values in a JSON registry, enabling efficient delta-sync:
only files whose content has actually changed are re-indexed.

Thread-safety is provided via :class:`threading.Lock`. Crash-safety
is provided via atomic temp-file + ``os.replace`` writes.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from personal_os.core.logger import get_logger
from personal_os.core.utils import compute_sha256
from personal_os.path_resolver import get_user_data_path

logger: logging.Logger = get_logger("imbuto.sync")


class SyncTracker:
    """JSON-backed incremental sync state with atomic persistence.

    Registry schema::

        {
            "files": {
                "/abs/path/to/note.md": {
                    "hash": "sha256hex...",
                    "note_id": "uuid4..."
                }
            }
        }

    Concurrency:
        All reads and writes to ``self._data`` and the underlying JSON
        file are protected by a ``threading.Lock``. This is safe for
        FastAPI's default thread-pool executor (sync callables dispatched
        to ``anyio`` worker threads).

    Crash-safety:
        ``_save()`` writes to a temporary file in the same directory,
        then calls ``os.replace()`` to atomically swap it with the
        target. If the process crashes mid-write, the previous state
        file remains intact.

    Args:
        state_path: Path to the JSON state file.
            Created automatically if absent.

    Example::

        tracker = SyncTracker()
        if compute_sha256(Path("note.md")) != tracker.get_file_state("note.md"):
            # file changed — re-index
    """

    def __init__(self, state_path: Optional[str] = None) -> None:
        if state_path is None:
            self._path: Path = get_user_data_path("data/config/sync_state.json")
        else:
            self._path: Path = Path(state_path).resolve()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock: threading.Lock = threading.Lock()
        self._data: Dict[str, Any] = self._load()

    # -- persistence -------------------------------------------------------

    def _load(self) -> Dict[str, Any]:
        """Load or initialise the sync state registry."""
        with self._lock:
            if not self._path.exists():
                logger.info("Sync state absent — initialising empty registry.")
                empty: Dict[str, Any] = {"files": {}}
                self._save_unlocked(empty)
                return empty

            try:
                with self._path.open("r", encoding="utf-8") as fh:
                    data: Dict[str, Any] = json.load(fh)
                logger.info(
                    "Sync state loaded — %d file(s) tracked.",
                    len(data.get("files", {})),
                )
                return data
            except (json.JSONDecodeError, OSError) as exc:
                logger.error(
                    "Corrupt sync state at %s — resetting. Error: %s",
                    self._path,
                    exc,
                )
                empty = {"files": {}}
                self._save_unlocked(empty)
                return empty

    def _save(self, data: Optional[Dict[str, Any]] = None) -> None:
        """Thread-safe, atomic persist of the registry to disk."""
        with self._lock:
            self._save_unlocked(data)

    def _save_unlocked(self, data: Optional[Dict[str, Any]] = None) -> None:
        """Persist the registry via atomic_json_write.

        MUST be called while ``self._lock`` is held.
        """
        payload: Dict[str, Any] = data if data is not None else self._data
        try:
            atomic_json_write(self._path, payload)
            logger.debug("Sync state saved atomically.")
        except OSError as exc:
            logger.error("Failed to save sync state: %s", exc)
            raise

    # -- public API --------------------------------------------------------

    def get_file_state(self, filepath: str) -> str:
        """Return the last known SHA-256 hash of *filepath*.

        Args:
            filepath: Absolute or relative path string used as the
                registry key.

        Returns:
            Hex-encoded SHA-256 hash, or an empty string if the file
            has never been tracked.
        """
        with self._lock:
            entry: Dict[str, str] = self._data.get("files", {}).get(filepath, {})
            return entry.get("hash", "")

    def update_file_state(
        self,
        filepath: str,
        file_hash: str,
        note_id: str,
    ) -> None:
        """Record the current hash and note_id for *filepath*.

        Args:
            filepath: Registry key (absolute path recommended).
            file_hash: SHA-256 hex digest of the file content.
            note_id: UUID4 identifier of the note derived from this file.
        """
        with self._lock:
            self._data.setdefault("files", {})[filepath] = {
                "hash": file_hash,
                "note_id": note_id,
            }
            self._save_unlocked()
        logger.debug("Updated state for %s: %s", filepath, file_hash)

    def get_last_sync(self) -> Optional[str]:
        """Return the ISO timestamp of the last successful synchronization."""
        with self._lock:
            return self._data.get("last_sync")

    def update_sync_time(self) -> None:
        """Record the current UTC time as the last sync timestamp."""
        import datetime
        with self._lock:
            self._data["last_sync"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            self._save_unlocked()
        logger.debug("Updated last_sync time.")


