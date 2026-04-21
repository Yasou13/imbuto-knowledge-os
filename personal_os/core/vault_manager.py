"""
Git-backed vault persistence for the IMBUTO ingestion pipeline.

:class:`VaultManager` writes validated notes as YAML-frontmatter Markdown
files into the vault directory and auto-commits every save to a local Git
repository for full version history.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import yaml
from git import InvalidGitRepositoryError, Repo

from personal_os.core.logger import get_logger, log_ingestion_event

logger: logging.Logger = get_logger("imbuto.vault")


class VaultManager:
    """Git-backed Markdown persistence layer.

    Initialises (or opens) a Git repository inside the vault directory
    and provides methods to format, save, and auto-commit knowledge notes.

    Args:
        vault_path: Relative or absolute path to the vault directory.
            Created automatically if absent.

    Example::

        vm = VaultManager("data/vault")
        path = vm.save_note(parsed_data)
    """

    def __init__(self, vault_path: str = "data/vault") -> None:
        self._vault: Path = Path(vault_path).resolve()
        self._vault.mkdir(parents=True, exist_ok=True)

        # Initialise or open the Git repository.
        try:
            self._repo: Repo = Repo(self._vault)
            logger.info("Opened existing Git repo at %s", self._vault)
        except InvalidGitRepositoryError:
            self._repo = Repo.init(self._vault)
            logger.info("Initialised new Git repo at %s", self._vault)

    # -- filename generation -----------------------------------------------

    @staticmethod
    def _generate_filename(title: str) -> str:
        """Convert *title* to a safe, lowercase, hyphen-separated filename.

        Non-alphanumeric characters (except hyphens) are stripped.
        Consecutive hyphens are collapsed, and the result is capped at
        80 characters to avoid filesystem limits.

        Args:
            title: The note title string.

        Returns:
            A ``.md`` filename, e.g. ``"my-research-note.md"``.
        """
        slug: str = title.lower().strip()
        slug = re.sub(r"[^a-z0-9\s-]", "", slug)
        slug = re.sub(r"[\s_]+", "-", slug)
        slug = re.sub(r"-{2,}", "-", slug)
        slug = slug.strip("-")[:80]
        return f"{slug or 'untitled'}.md"

    # -- markdown formatting -----------------------------------------------

    def format_to_markdown(
        self,
        parsed_data: Dict[str, Any],
        workspace_id: str = "ws-default",
    ) -> str:
        """Build a YAML-frontmatter Markdown document from *parsed_data*.

        Frontmatter keys: ``note_id`` (UUID4), ``workspace_id``, ``title``,
        ``flag``, ``tags``, ``confidence_score``, ``summary``, ``date``
        (UTC ISO-8601).

        Args:
            parsed_data: Validated note dictionary (from
                :meth:`IMBUTONoteSchema.model_dump`).
            workspace_id: Logical workspace identifier.

        Returns:
            Complete Markdown string with ``---`` delimiters.
        """
        note_id: str = str(uuid.uuid4())

        frontmatter: Dict[str, Any] = {
            "note_id": note_id,
            "workspace_id": workspace_id,
            "title": parsed_data["title"],
            "flag": parsed_data["flag"],
            "tags": parsed_data.get("tags", []),
            "confidence_score": parsed_data["confidence_score"],
            "summary": parsed_data["summary"],
            "date": datetime.now(timezone.utc).isoformat(),
        }

        fm_block: str = yaml.dump(
            frontmatter,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        ).strip()

        body: str = parsed_data.get("normalized_content", "")

        return f"---\n{fm_block}\n---\n\n{body}\n"

    # -- save & commit -----------------------------------------------------

    def save_note(
        self,
        parsed_data: Dict[str, Any],
        workspace_id: str = "ws-default",
    ) -> str:
        """Write a validated note to disk and auto-commit to Git.

        Args:
            parsed_data: Validated note dictionary.
            workspace_id: Logical workspace identifier injected into
                frontmatter.

        Returns:
            Absolute path of the saved ``.md`` file.

        Raises:
            OSError: On file-system write failures.
            Exception: On Git staging / commit failures (logged, not
                swallowed).
        """
        filename: str = self._generate_filename(parsed_data.get("title", ""))

        # Resolve physical save path from workspace config.
        save_dir: Path = self._vault
        try:
            from personal_os.core.workspace import WorkspaceManager
            ws_config = WorkspaceManager().get_workspace(workspace_id)
            ws_paths = ws_config.get("paths", [])
            if ws_paths:
                save_dir = Path(ws_paths[0]).resolve()
                save_dir.mkdir(parents=True, exist_ok=True)
        except (KeyError, Exception) as exc:
            logger.warning(
                "Could not resolve workspace '%s' — falling back to default vault. %s",
                workspace_id,
                exc,
            )

        file_path: Path = save_dir / filename
        content: str = self.format_to_markdown(parsed_data, workspace_id)

        # Write to disk.
        try:
            file_path.write_text(content, encoding="utf-8")
            logger.info("Note saved: %s", file_path)
        except OSError as exc:
            log_ingestion_event("FILE_WRITE_ERROR", {
                "filename": filename,
                "error": str(exc),
            })
            raise

        # Stage & commit (guard against empty staging area).
        try:
            self._repo.index.add([str(file_path)])

            # Check if there are actually staged changes to commit.
            has_changes: bool = False
            try:
                has_changes = bool(
                    self._repo.index.diff("HEAD")
                    or self._repo.untracked_files
                )
            except Exception:
                # First commit — no HEAD exists yet, so diff fails.
                has_changes = True

            if has_changes:
                self._repo.index.commit(f"Auto-save: {filename}")
                logger.info("Git commit: Auto-save: %s", filename)
                log_ingestion_event("GIT_COMMIT", {
                    "filename": filename,
                    "path": str(file_path),
                })
            else:
                logger.info("No changes to commit for %s", filename)

        except Exception as exc:
            log_ingestion_event("GIT_ERROR", {
                "filename": filename,
                "error_type": type(exc).__name__,
                "error": str(exc),
            })
            logger.error("Git commit failed for %s: %s", filename, exc)
            raise

        return str(file_path)
