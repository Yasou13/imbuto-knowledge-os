"""
Logical workspace management for the IMBUTO Knowledge OS.

:class:`WorkspaceManager` maintains a JSON registry of workspaces,
each mapping a stable ID to a name and a set of vault paths. This
enables multi-vault routing without coupling storage paths to the UI.
"""

from __future__ import annotations

import uuid
from filelock import FileLock
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from personal_os.core.logger import get_logger
from personal_os.path_resolver import get_user_data_path
from personal_os.core.utils import atomic_json_write

logger: logging.Logger = get_logger("imbuto.workspace")

# ---------------------------------------------------------------------------
# Default schema & Helpers
# ---------------------------------------------------------------------------

def cleanup_orphaned_tmp_files(vault_path: Path) -> None:
    """Garbage collect stranded *.tmp files older than 5 minutes to prevent inode exhaustion."""
    try:
        current_time = time.time()
        deleted_count = 0
        threshold_seconds = 300  # 5 minutes
        
        for tmp_file in vault_path.rglob("*.tmp"):
            if not tmp_file.is_file():
                continue
            
            mtime = tmp_file.stat().st_mtime
            if current_time - mtime > threshold_seconds:
                try:
                    tmp_file.unlink()
                    deleted_count += 1
                except OSError as exc:
                    logger.debug("Failed to delete orphaned tmp file %s: %s", tmp_file, exc)
                    
        if deleted_count > 0:
            logger.info("Garbage collection cleaned up %d orphaned temporary files.", deleted_count)
    except Exception as exc:
        logger.error("Garbage collection routine failed: %s", exc)

_DEFAULT_REGISTRY: Dict[str, Any] = {
    "workspaces": [
        {
            "workspace_id": "ws-default",
            "name": "Default Vault",
            "paths": [str(get_user_data_path("data/vault/default"))],
            "global_fallback": True,
        }
    ]
}


class WorkspaceManager:
    """JSON-backed workspace registry.

    Manages ``data/config/workspaces.json``, creating it with a default
    schema on first run.

    Args:
        config_dir: Directory containing the registry file.
            Created automatically if absent.

    Example::

        wm = WorkspaceManager()
        ws = wm.get_workspace("ws-default")
    """

    def __init__(self, config_dir: Optional[str] = None) -> None:
        if config_dir is None:
            config_dir = str(get_user_data_path("data/config"))
        self._config_dir: Path = Path(config_dir).resolve()
        self._config_dir.mkdir(parents=True, exist_ok=True)
        self._registry_path: Path = self._config_dir / "workspaces.json"
        self._data: Dict[str, Any] = self._load()

    # -- persistence -------------------------------------------------------

    def _load(self) -> Dict[str, Any]:
        """Load or initialise the workspace registry."""
        if not self._registry_path.exists():
            logger.info(
                "Workspace registry absent — creating default at %s",
                self._registry_path,
            )
            self._save(_DEFAULT_REGISTRY)
            return json.loads(json.dumps(_DEFAULT_REGISTRY))

        try:
            with self._registry_path.open("r", encoding="utf-8") as fh:
                data: Dict[str, Any] = json.load(fh)
            logger.info(
                "Loaded %d workspace(s) from registry.",
                len(data.get("workspaces", [])),
            )
            return data
        except (json.JSONDecodeError, OSError) as exc:
            logger.error(
                "Corrupt workspace registry at %s — resetting. Error: %s",
                self._registry_path,
                exc,
            )
            self._save(_DEFAULT_REGISTRY)
            return json.loads(json.dumps(_DEFAULT_REGISTRY))

    def _save(self, data: Optional[Dict[str, Any]] = None) -> None:
        """Persist the registry to disk atomically via os.replace."""
        payload: Dict[str, Any] = data if data is not None else self._data
        try:
            atomic_json_write(str(self._registry_path), payload)
            logger.debug("Workspace registry saved.")
        except OSError as exc:
            logger.error("Failed to save workspace registry: %s", exc)
            raise

    # -- public API --------------------------------------------------------

    def get_workspace(self, workspace_id: str) -> Dict[str, Any]:
        """Return the workspace dict matching *workspace_id*.

        Args:
            workspace_id: Stable workspace identifier (e.g. ``ws-default``).

        Returns:
            Workspace dictionary with ``workspace_id``, ``name``, ``paths``,
            and ``global_fallback`` keys.

        Raises:
            KeyError: If no workspace matches the given ID.
        """
        for ws in self._data.get("workspaces", []):
            if ws.get("workspace_id") == workspace_id:
                return ws
        raise KeyError(f"Workspace '{workspace_id}' not found in registry.")

    def list_workspaces(self) -> List[Dict[str, Any]]:
        """Return all registered workspaces.

        Returns:
            List of workspace dictionaries.
        """
        return list(self._data.get("workspaces", []))

    def add_workspace(
        self,
        workspace_id: str,
        name: str,
        paths: List[str],
    ) -> None:
        """Register a new workspace.

        Args:
            workspace_id: Stable identifier (e.g. ``ws-research``).
            name: Human-readable workspace name.
            paths: List of vault directory paths associated with this
                workspace.

        Raises:
            ValueError: If a workspace with the same ID already exists.
        """
        for ws in self._data.get("workspaces", []):
            if ws.get("workspace_id") == workspace_id:
                raise ValueError(
                    f"Workspace '{workspace_id}' already exists."
                )

        new_ws: Dict[str, Any] = {
            "workspace_id": workspace_id,
            "name": name,
            "paths": paths,
            "global_fallback": False,
        }
        self._data.setdefault("workspaces", []).append(new_ws)
        self._save()
        logger.info("Added workspace '%s' (%s).", workspace_id, name)
