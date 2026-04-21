"""
File manager — safe I/O operations for the Obsidian vault.

Provides :class:`FileManager`, a thin wrapper around ``pathlib`` that
enforces vault-boundary checks, handles encoding, and translates OS
errors into domain-specific exceptions.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List

from personal_os.config.settings import Settings
from personal_os.core.exceptions import FileParsingError, VaultNotFoundError

logger: logging.Logger = logging.getLogger("imbuto.file_manager")


class FileManager:
    """Manages Markdown file I/O within the configured vault directory.

    All paths are validated to stay within the vault boundary to prevent
    path-traversal attacks.

    Args:
        settings: Injected :class:`Settings` instance.
    """

    def __init__(self, settings: Settings) -> None:
        self._vault_path: Path = settings.resolved_vault_path

        if not self._vault_path.exists():
            self._vault_path.mkdir(parents=True, exist_ok=True)
            logger.info("Created vault directory: %s", self._vault_path)

        if not self._vault_path.is_dir():
            raise VaultNotFoundError(
                f"Vault path is not a directory: {self._vault_path}",
                detail=str(self._vault_path),
            )

        logger.info("FileManager initialised — vault: %s", self._vault_path)

    # -- listing -----------------------------------------------------------

    def list_files(self) -> List[Path]:
        """Return all ``.md`` files in the vault, sorted alphabetically.

        Returns:
            List of absolute :class:`Path` objects.
        """
        files: List[Path] = sorted(
            p for p in self._vault_path.rglob("*.md") if p.is_file()
        )
        logger.debug("Listed %d Markdown files.", len(files))
        return files

    def list_relative(self) -> List[str]:
        """Return vault-relative path strings for all ``.md`` files.

        Returns:
            Sorted list of relative path strings (e.g. ``"notes/foo.md"``).
        """
        return [
            str(p.relative_to(self._vault_path)) for p in self.list_files()
        ]

    # -- reading -----------------------------------------------------------

    def read_file(self, relative_path: str) -> str:
        """Read and return the contents of a Markdown file.

        Args:
            relative_path: Path relative to the vault root.

        Returns:
            File contents as a string.

        Raises:
            FileParsingError: If the file does not exist, is outside the
                vault boundary, or cannot be read.
        """
        abs_path: Path = self._resolve_safe(relative_path)

        if not abs_path.exists():
            raise FileParsingError(
                f"File not found: {relative_path}",
                detail=str(abs_path),
            )

        try:
            content: str = abs_path.read_text(encoding="utf-8")
            logger.debug("Read %d chars from %s.", len(content), relative_path)
            return content
        except OSError as exc:
            raise FileParsingError(
                f"Cannot read file: {relative_path}",
                detail=str(exc),
            ) from exc

    # -- writing -----------------------------------------------------------

    def write_file(self, relative_path: str, content: str) -> Path:
        """Write *content* to a Markdown file, creating parent dirs as needed.

        Args:
            relative_path: Path relative to the vault root.  Must end
                with ``.md``.
            content: Full file content to write.

        Returns:
            Absolute :class:`Path` of the written file.

        Raises:
            FileParsingError: If the path escapes the vault boundary or
                the write fails.
            ValueError: If *relative_path* does not end with ``.md``.
        """
        if not relative_path.strip().endswith(".md"):
            raise ValueError(
                f"Only .md files are supported, got: '{relative_path}'"
            )

        abs_path: Path = self._resolve_safe(relative_path)

        try:
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            abs_path.write_text(content, encoding="utf-8")
            logger.info("Wrote %d chars to %s.", len(content), relative_path)
            return abs_path
        except OSError as exc:
            raise FileParsingError(
                f"Cannot write file: {relative_path}",
                detail=str(exc),
            ) from exc

    # -- deletion ----------------------------------------------------------

    def delete_file(self, relative_path: str) -> None:
        """Delete a Markdown file from the vault.

        Args:
            relative_path: Path relative to the vault root.

        Raises:
            FileParsingError: If the file does not exist or cannot be deleted.
        """
        abs_path: Path = self._resolve_safe(relative_path)

        if not abs_path.exists():
            raise FileParsingError(
                f"File not found: {relative_path}",
                detail=str(abs_path),
            )

        try:
            abs_path.unlink()
            logger.info("Deleted %s.", relative_path)
        except OSError as exc:
            raise FileParsingError(
                f"Cannot delete file: {relative_path}",
                detail=str(exc),
            ) from exc

    # -- path safety -------------------------------------------------------

    def _resolve_safe(self, relative_path: str) -> Path:
        """Resolve *relative_path* against the vault and validate boundary.

        Args:
            relative_path: User-supplied vault-relative path string.

        Returns:
            Resolved absolute :class:`Path`.

        Raises:
            FileParsingError: If the resolved path escapes the vault root
                (path-traversal attempt).
        """
        resolved: Path = (self._vault_path / relative_path).resolve()
        try:
            resolved.relative_to(self._vault_path.resolve())
        except ValueError as exc:
            raise FileParsingError(
                f"Path traversal blocked: '{relative_path}' escapes vault.",
                detail=str(exc),
            ) from exc
        return resolved

    @property
    def vault_path(self) -> Path:
        """Return the absolute vault directory path."""
        return self._vault_path
