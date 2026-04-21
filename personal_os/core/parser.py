"""
Data ingestion module — Obsidian vault parser with **delta-sync**.

Reads Markdown files from a configured vault directory, splits them into
semantically meaningful chunks via :class:`MarkdownHeaderTextSplitter`, and
tracks file modification timestamps in a local JSON state file so that only
*new*, *modified*, or *deleted* files are processed on subsequent runs.
"""

from __future__ import annotations

import uuid
from filelock import FileLock
import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Set

from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter

from personal_os.config.settings import Settings
from personal_os.core.exceptions import (
    FileParsingError,
    SyncStateError,
    VaultNotFoundError,
)

logger: logging.Logger = logging.getLogger("imbuto.parser")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FileDelta:
    """Result of comparing current vault state against persisted sync state.

    Attributes:
        new_files: Paths that exist on disk but not in the state file.
        modified_files: Paths whose ``mtime_ns`` differs from the recorded
            value.
        deleted_files: Paths recorded in the state file but no longer
            present on disk.
    """

    new_files: FrozenSet[Path]
    modified_files: FrozenSet[Path]
    deleted_files: FrozenSet[Path]

    @property
    def has_changes(self) -> bool:
        """Return ``True`` if any category contains entries."""
        return bool(self.new_files or self.modified_files or self.deleted_files)


@dataclass
class ParseResult:
    """Container returned by :meth:`ObsidianParser.parse_changed`.

    Attributes:
        new_docs: Langchain ``Document`` objects produced from new or
            modified files.
        modified_files: Absolute paths of files that were re-processed.
        deleted_files: Absolute paths of files that were removed from the
            vault since the last run.
    """

    new_docs: List[Document] = field(default_factory=list)
    modified_files: List[str] = field(default_factory=list)
    deleted_files: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Sync state persistence
# ---------------------------------------------------------------------------

class SyncState:
    """Manages a ``{file_path: mtime_ns}`` mapping persisted as JSON.

    Args:
        state_path: Absolute path to the JSON file used for persistence.
    """

    def __init__(self, state_path: Path) -> None:
        self._path: Path = state_path
        self._state: Dict[str, int] = {}
        self._load()

    # -- persistence -------------------------------------------------------

    def _load(self) -> None:
        """Load state from disk.  An absent file is treated as empty state."""
        if not self._path.exists():
            logger.debug("Sync state file not found at %s — starting fresh.", self._path)
            self._state = {}
            return

        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                raw: Any = json.load(fh)
            if not isinstance(raw, dict):
                raise ValueError("Root element is not a JSON object.")
            self._state = {str(k): int(v) for k, v in raw.items()}
            logger.info(
                "Loaded sync state with %d entries from %s.",
                len(self._state),
                self._path,
            )
        except (json.JSONDecodeError, ValueError, OSError) as exc:
            raise SyncStateError(
                f"Failed to load sync state from {self._path}.",
                detail=str(exc),
            ) from exc

    def save(self) -> None:
        """Persist the current state to disk atomically via os.replace."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_filepath: str = f"{self._path}.{uuid.uuid4().hex}.tmp"
        try:
            lock_path = str(self._path) + ".lock"
            with FileLock(lock_path):
                with open(tmp_filepath, "w", encoding="utf-8") as fh:
                    json.dump(self._state, fh, indent=2)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp_filepath, self._path)
            logger.debug("Sync state saved to %s.", self._path)
        except OSError as exc:
            raise SyncStateError(
                f"Failed to write sync state to {self._path}.",
                detail=str(exc),
            ) from exc
        finally:
            if os.path.exists(tmp_filepath):
                os.remove(tmp_filepath)

    # -- diff logic --------------------------------------------------------

    def compute_delta(self, current_files: Dict[str, int]) -> FileDelta:
        """Compare *current_files* against the persisted state.

        Args:
            current_files: Mapping of ``{absolute_path_str: mtime_ns}``
                representing the current vault snapshot.

        Returns:
            A :class:`FileDelta` with categorized path sets.
        """
        current_keys: Set[str] = set(current_files.keys())
        known_keys: Set[str] = set(self._state.keys())

        new: FrozenSet[Path] = frozenset(
            Path(p) for p in current_keys - known_keys
        )
        deleted: FrozenSet[Path] = frozenset(
            Path(p) for p in known_keys - current_keys
        )
        modified: FrozenSet[Path] = frozenset(
            Path(p)
            for p in current_keys & known_keys
            if current_files[p] != self._state[p]
        )

        logger.info(
            "Delta computed — new: %d, modified: %d, deleted: %d.",
            len(new),
            len(modified),
            len(deleted),
        )
        return FileDelta(
            new_files=new, modified_files=modified, deleted_files=deleted
        )

    def update(self, current_files: Dict[str, int]) -> None:
        """Replace the in-memory state with *current_files*.

        Call :meth:`save` afterwards to persist the change.
        """
        self._state = dict(current_files)


# ---------------------------------------------------------------------------
# Obsidian parser
# ---------------------------------------------------------------------------

class ObsidianParser:
    """Reads an Obsidian vault and produces Langchain ``Document`` chunks.

    The parser supports **delta-sync**: on each invocation of
    :meth:`parse_changed`, only files that are new, modified, or deleted
    since the previous run are processed.  File modification is detected
    via ``stat().st_mtime_ns``.

    Args:
        settings: Injected :class:`Settings` instance carrying all paths
            and tunables.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings: Settings = settings
        self._vault_path: Path = settings.resolved_vault_path
        self._sync_state_path: Path = settings.resolved_sync_state_path

        if not self._vault_path.exists() or not self._vault_path.is_dir():
            raise VaultNotFoundError(
                f"Vault directory does not exist: {self._vault_path}",
                detail=str(self._vault_path),
            )

        self._splitter: MarkdownHeaderTextSplitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=settings.chunk_headers,
            strip_headers=False,
        )

        logger.info("ObsidianParser initialised — vault: %s", self._vault_path)

    # -- scanning ----------------------------------------------------------

    def scan_vault(self) -> List[Path]:
        """Walk the vault directory and return all ``.md`` file paths.

        Returns:
            Sorted list of absolute :class:`Path` objects.
        """
        md_files: List[Path] = sorted(
            p
            for p in self._vault_path.rglob("*.md")
            if p.is_file()
        )
        logger.debug("Vault scan found %d Markdown files.", len(md_files))
        return md_files

    def _snapshot(self, files: List[Path]) -> Dict[str, int]:
        """Build a ``{path_str: mtime_ns}`` mapping for *files*."""
        return {str(f): f.stat().st_mtime_ns for f in files}

    # -- parsing -----------------------------------------------------------

    def parse_file(self, file_path: Path) -> List[Document]:
        """Read and split a single Markdown file into ``Document`` chunks.

        Args:
            file_path: Absolute path to the ``.md`` file.

        Returns:
            List of :class:`Document` objects enriched with metadata.

        Raises:
            FileParsingError: If the file cannot be read or split.
        """
        try:
            content: str = file_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise FileParsingError(
                f"Cannot read file: {file_path}",
                detail=str(exc),
            ) from exc

        try:
            raw_chunks = self._splitter.split_text(content)
        except Exception as exc:
            raise FileParsingError(
                f"Splitting failed for file: {file_path}",
                detail=str(exc),
            ) from exc

        documents: List[Document] = []
        for idx, chunk in enumerate(raw_chunks):
            metadata: Dict[str, Any] = dict(chunk.metadata)
            metadata["source_file"] = file_path.name
            metadata["file_path"] = str(file_path)
            metadata["folder"] = file_path.parent.name
            metadata["chunk_index"] = idx
            metadata["chunk_id"] = self._make_chunk_id(file_path, idx)

            documents.append(
                Document(page_content=chunk.page_content, metadata=metadata)
            )

        logger.debug(
            "Parsed %d chunks from %s.", len(documents), file_path.name
        )
        return documents

    # -- delta-sync entry point --------------------------------------------

    def parse_changed(self) -> ParseResult:
        """Perform an incremental (delta) parse of the vault.

        Workflow:
            1. Load persisted sync state.
            2. Scan vault and snapshot current ``mtime_ns`` values.
            3. Compute delta (new / modified / deleted).
            4. Parse only new + modified files.
            5. Update and persist sync state.

        Returns:
            A :class:`ParseResult` summarising what was processed.

        Raises:
            VaultNotFoundError: If the vault directory disappeared.
            SyncStateError: If state cannot be loaded or saved.
            FileParsingError: If any individual file fails (logged and
                skipped — does not abort the entire run).
        """
        sync: SyncState = SyncState(self._sync_state_path)
        all_files: List[Path] = self.scan_vault()
        current_snapshot: Dict[str, int] = self._snapshot(all_files)
        delta: FileDelta = sync.compute_delta(current_snapshot)

        result = ParseResult(
            modified_files=[str(p) for p in delta.modified_files],
            deleted_files=[str(p) for p in delta.deleted_files],
        )

        if not delta.has_changes:
            logger.info("No vault changes detected — nothing to process.")
            return result

        files_to_parse: List[Path] = sorted(
            delta.new_files | delta.modified_files
        )

        for file_path in files_to_parse:
            try:
                docs: List[Document] = self.parse_file(file_path)
                result.new_docs.extend(docs)
                logger.info(
                    "Processed %d chunks from %s.",
                    len(docs),
                    file_path.name,
                )
            except FileParsingError:
                logger.exception("Skipping file due to parsing error: %s", file_path)

        # Persist updated state only after successful processing.
        sync.update(current_snapshot)
        sync.save()

        logger.info(
            "Delta sync complete — %d new docs, %d modified files, "
            "%d deleted files.",
            len(result.new_docs),
            len(result.modified_files),
            len(result.deleted_files),
        )
        return result

    # -- async wrapper -----------------------------------------------------

    async def parse_changed_async(self) -> ParseResult:
        """Async-compatible wrapper for parse_changed."""
        import asyncio
        return await asyncio.to_thread(self.parse_changed)

    # -- utilities ---------------------------------------------------------

    @staticmethod
    def _make_chunk_id(file_path: Path, chunk_index: int) -> str:
        """Derive a deterministic chunk ID from file path and index.

        Args:
            file_path: Absolute path of the source file.
            chunk_index: Zero-based index of the chunk within the file.

        Returns:
            A hex-encoded SHA-256 digest (first 16 chars) used as a
            stable ChromaDB document ID.
        """
        raw: str = f"{file_path}::{chunk_index}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Semantic Markdown parser (V3 — header-aware chunking)
# ---------------------------------------------------------------------------

import re

import yaml


class SemanticMarkdownParser:
    """Header-aware Markdown parser for the IMBUTO V3 pipeline.

    Unlike :class:`ObsidianParser` (which uses Langchain's
    ``MarkdownHeaderTextSplitter``), this parser splits on **any** Markdown
    header and preserves the heading hierarchy in each chunk's metadata.
    It also extracts YAML frontmatter and backfills ``note_id`` /
    ``workspace_id`` for legacy notes missing those fields.

    Example::

        parser = SemanticMarkdownParser()
        chunks = parser.parse_file("data/vault/my-note.md")
    """

    MAX_CHUNK_CHARS = 6000

    _FRONTMATTER_RE = re.compile(
        r"\A---\s*\n(.*?)\n---\s*\n",
        re.DOTALL,
    )

    def _split_oversized(self, text: str) -> List[str]:
        """Forcefully fracture oversized blocks into sequential slices.
        Uses the `regex` module's grapheme cluster matching (\\X) to protect against
        fracturing complex multi-byte Unicode sequences (e.g., emojis or language ligatures).
        """
        import regex

        chunks: List[str] = []
        current_chunk: List[str] = []
        current_len: int = 0

        # \\X strictly matches one extended grapheme cluster
        for grapheme in regex.findall(r"\X", text):
            g_len = len(grapheme)
            if current_len + g_len > self.MAX_CHUNK_CHARS:
                if current_chunk:
                    chunks.append("".join(current_chunk))
                    current_chunk = [grapheme]
                    current_len = g_len
                else:
                    chunks.append(grapheme)
                    current_chunk = []
                    current_len = 0
            else:
                current_chunk.append(grapheme)
                current_len += g_len

        if current_chunk:
            chunks.append("".join(current_chunk))

        return chunks
    _HEADING_RE = re.compile(r"(?m)^(#{1,6}\s+.*)$")

    def parse_file(self, filepath: str) -> List[Dict[str, Any]]:
        """Read a Markdown file and split it into semantic chunks.

        Each chunk corresponds to a header section.  Text before the first
        header is assigned heading ``"(preamble)"``.

        Args:
            filepath: Absolute or relative path to a ``.md`` file.

        Returns:
            List of dictionaries, each with ``page_content`` and
            ``metadata`` keys::

                {
                    "page_content": "...",
                    "metadata": {
                        "note_id": "uuid4...",
                        "workspace_id": "ws-default",
                        "heading": "## Section Title",
                        "source_file": "my-note.md",
                    }
                }

        Raises:
            FileNotFoundError: If *filepath* does not exist.
            FileParsingError: On I/O or YAML parse failures.
        """
        path = Path(filepath).resolve()
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        try:
            raw_text: str = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise FileParsingError(
                f"Cannot read {path}: {exc}",
                detail=str(exc),
            ) from exc

        # -- Extract frontmatter -------------------------------------------
        frontmatter: Dict[str, Any] = {}
        body: str = raw_text

        fm_match = self._FRONTMATTER_RE.match(raw_text)
        if fm_match:
            try:
                frontmatter = yaml.safe_load(fm_match.group(1)) or {}
            except yaml.YAMLError as exc:
                logger.warning(
                    "Malformed YAML frontmatter in %s — skipping. %s",
                    path,
                    exc,
                )
                frontmatter = {}
            body = raw_text[fm_match.end():]

        # Backfill legacy notes missing stable IDs.
        note_id: str = frontmatter.get("note_id", str(uuid.uuid4()))
        workspace_id: str = frontmatter.get("workspace_id", "ws-default")
        source_file: str = path.name

        # -- Semantic splitting on headers ---------------------------------
        chunks: List[Dict[str, Any]] = []
        sections: List[str] = self._HEADING_RE.split(body)

        def _append_chunks(content_text: str, current_heading: str) -> None:
            if len(content_text) > self.MAX_CHUNK_CHARS:
                for slice_content in self._split_oversized(content_text):
                    chunks.append({
                        "page_content": slice_content,
                        "metadata": {
                            "note_id": note_id,
                            "workspace_id": workspace_id,
                            "heading": current_heading,
                            "source_file": source_file,
                        },
                    })
            else:
                chunks.append({
                    "page_content": content_text,
                    "metadata": {
                        "note_id": note_id,
                        "workspace_id": workspace_id,
                        "heading": current_heading,
                        "source_file": source_file,
                    },
                })

        # sections alternates: [pre-header text, header, body, header, body, ...]
        if not sections or not sections[0].strip():
            # No preamble text before first header.
            idx = 1 if len(sections) > 1 else 0
        else:
            # Preamble exists — emit it as a chunk.
            preamble: str = sections[0].strip()
            if preamble:
                _append_chunks(preamble, "(preamble)")
            idx = 1

        # Process header + body pairs.
        while idx < len(sections) - 1:
            heading: str = sections[idx].strip()
            content: str = sections[idx + 1].strip()
            if content:
                _append_chunks(content, heading)
            idx += 2

        # Edge case: file has no headers at all — treat entire body as one chunk.
        if not chunks and body.strip():
            _append_chunks(body.strip(), "(full-document)")

        logger.debug(
            "SemanticMarkdownParser: %s → %d chunk(s).",
            source_file,
            len(chunks),
        )
        return chunks

    # -- async wrapper -----------------------------------------------------

    async def parse_file_async(self, filepath: str) -> List[Dict[str, Any]]:
        """Async-compatible wrapper for parse_file."""
        import asyncio
        return await asyncio.to_thread(self.parse_file, filepath)

