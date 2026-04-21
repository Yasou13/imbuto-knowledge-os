"""
Vector store module — ChromaDB persistence with **Singleton** lifecycle.

Provides :class:`VectorStoreManager`, a thread-safe Singleton that also
implements the context-manager protocol (``with`` statement) to guarantee
that resources are released even when exceptions occur.  All configuration
is injected via :class:`Settings`.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

import chromadb
from chromadb.api.models.Collection import Collection
from langchain_core.documents import Document
from sentence_transformers import SentenceTransformer

from personal_os.config.settings import Settings
from personal_os.core.exceptions import EmbeddingError, IndexingError
from personal_os.core.sync_tracker import SyncTracker
from personal_os.core.parser import SemanticMarkdownParser
from personal_os.core.utils import compute_sha256

logger: logging.Logger = logging.getLogger("imbuto.vector_store")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class QueryResult:
    """Single result returned by :meth:`VectorStoreManager.query`.

    Attributes:
        content: The original chunk text.
        metadata: Metadata dictionary stored alongside the chunk.
        distance: Similarity distance (lower is more similar for the
            default L2 metric).
    """

    content: str
    metadata: Dict[str, Any]
    distance: float


# ---------------------------------------------------------------------------
# Singleton + Context-Manager vector store
# ---------------------------------------------------------------------------

class VectorStoreManager:
    """Thread-safe Singleton managing a ChromaDB persistent collection.

    Usage::

        settings = Settings()
        with VectorStoreManager(settings) as vs:
            vs.index_documents(docs)
            results = vs.query("search term")

    The first instantiation loads the SentenceTransformer model and opens
    the ChromaDB client.  Subsequent calls with the same ``Settings``
    return the *same* instance (Singleton).  The context manager ensures
    that resources are cleaned up on exit.

    Args:
        settings: Injected :class:`Settings` instance.
    """

    _instance: Optional[VectorStoreManager] = None
    _lock: threading.Lock = threading.Lock()
    _initialized: bool = False

    # -- Singleton mechanics -----------------------------------------------

    def __new__(cls, settings: Settings) -> VectorStoreManager:  # noqa: D102
        with cls._lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                cls._instance = instance
            return cls._instance

    def __init__(self, settings: Settings) -> None:
        # Guard against re-initialisation on subsequent __init__ calls
        # that the Singleton __new__ triggers.
        if self._initialized:
            return
        self._settings: Settings = settings
        self._model: Optional[SentenceTransformer] = None
        self._client: Optional[chromadb.ClientAPI] = None
        self._collection: Optional[Collection] = None
        self._initialize()
        VectorStoreManager._initialized = True

    # -- context manager ---------------------------------------------------

    def __enter__(self) -> VectorStoreManager:
        """Return *self* — resources are already acquired in ``__init__``."""
        logger.debug("VectorStoreManager context entered.")
        return self

    def __exit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[BaseException],
        exc_tb: Optional[Any],
    ) -> None:
        """Release internal references (ChromaDB client, model)."""
        logger.debug("VectorStoreManager context exiting.")
        self.close()

    # -- lifecycle ---------------------------------------------------------

    def _initialize(self) -> None:
        """Load the embedding model and connect to ChromaDB."""
        self._load_model()
        self._connect_db()

    def _load_model(self) -> None:
        """Instantiate the SentenceTransformer embedding model.

        Raises:
            EmbeddingError: If the model cannot be loaded.
        """
        model_name: str = self._settings.embedding_model_name
        logger.info("Loading SentenceTransformer model: %s …", model_name)
        try:
            self._model = SentenceTransformer(model_name)
            logger.info("Model '%s' loaded successfully.", model_name)
        except Exception as exc:
            raise EmbeddingError(
                f"Failed to load embedding model '{model_name}'.",
                detail=str(exc),
            ) from exc

    def _connect_db(self) -> None:
        """Open (or create) the ChromaDB persistent client and collection.

        Raises:
            IndexingError: If the database connection fails.
        """
        persist_dir: str = str(self._settings.resolved_chroma_persist_dir)
        collection_name: str = self._settings.chroma_collection_name
        try:
            self._client = chromadb.PersistentClient(path=persist_dir)
            self._collection = self._client.get_or_create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"},
            )
            logger.info(
                "ChromaDB connected — collection '%s' at %s (count: %d).",
                collection_name,
                persist_dir,
                self._collection.count(),
            )
        except Exception as exc:
            raise IndexingError(
                f"Failed to connect to ChromaDB at '{persist_dir}'.",
                detail=str(exc),
            ) from exc

    def close(self) -> None:
        """Release singleton resources so a fresh instance can be created."""
        with self._lock:
            if self._client is not None:
                try:
                    self._client.clear_system_cache()
                    logger.info("ChromaDB system cache cleared (WAL flushed).")
                except Exception as exc:
                    logger.warning("Failed to clear ChromaDB system cache: %s", exc)
            
            self._model = None
            self._client = None
            self._collection = None
            VectorStoreManager._instance = None
            VectorStoreManager._initialized = False
            logger.info("VectorStoreManager resources released.")

    # -- embedding helper --------------------------------------------------

    def _embed(self, texts: Sequence[str]) -> List[List[float]]:
        """Encode *texts* into dense vectors.

        Args:
            texts: Sequence of plain-text strings.

        Returns:
            List of float vectors.

        Raises:
            EmbeddingError: If encoding fails.
        """
        if self._model is None:
            raise EmbeddingError("Embedding model is not loaded.")
        try:
            embeddings = self._model.encode(
                list(texts), show_progress_bar=False
            )
            return [vec.tolist() for vec in embeddings]
        except Exception as exc:
            raise EmbeddingError(
                "Failed to encode texts.",
                detail=str(exc),
            ) from exc

    # -- indexing ----------------------------------------------------------

    def index_documents(self, documents: List[Document]) -> int:
        """Embed and upsert *documents* into the ChromaDB collection.

        Each document **must** carry ``chunk_id`` in its metadata (produced
        by :class:`ObsidianParser`).  Documents are processed in batches of
        256 to respect ChromaDB's recommended payload size.

        Args:
            documents: Langchain ``Document`` objects to index.

        Returns:
            Number of documents successfully upserted.

        Raises:
            IndexingError: If the upsert operation fails.
        """
        if not documents:
            logger.info("index_documents called with empty list — skipping.")
            return 0

        if self._collection is None:
            raise IndexingError("ChromaDB collection is not available.")

        batch_size: int = 256
        total_upserted: int = 0

        try:
            for start in range(0, len(documents), batch_size):
                batch: List[Document] = documents[start : start + batch_size]
                ids: List[str] = [
                    doc.metadata["chunk_id"] for doc in batch
                ]
                contents: List[str] = [doc.page_content for doc in batch]
                metadatas: List[Dict[str, Any]] = [
                    self._sanitize_metadata(doc.metadata) for doc in batch
                ]
                embeddings: List[List[float]] = self._embed(contents)

                self._collection.upsert(
                    ids=ids,
                    documents=contents,
                    metadatas=metadatas,
                    embeddings=embeddings,
                )
                total_upserted += len(batch)
                logger.debug(
                    "Upserted batch %d–%d (%d docs).",
                    start,
                    start + len(batch),
                    len(batch),
                )

            logger.info(
                "Indexed %d documents into collection '%s'.",
                total_upserted,
                self._settings.chroma_collection_name,
            )
            return total_upserted

        except (EmbeddingError, IndexingError):
            raise
        except Exception as exc:
            raise IndexingError(
                "Unexpected error during document indexing.",
                detail=str(exc),
            ) from exc

    # -- deletion ----------------------------------------------------------

    def delete_by_source(self, file_paths: List[str]) -> int:
        """Remove all chunks whose ``file_path`` metadata matches any of
        the given *file_paths*.

        Args:
            file_paths: Absolute file path strings of deleted / modified
                source files.

        Returns:
            Number of file paths processed.

        Raises:
            IndexingError: If the delete operation fails.
        """
        if not file_paths or self._collection is None:
            return 0

        try:
            for fp in file_paths:
                self._collection.delete(
                    where={"file_path": {"$eq": fp}}
                )
                logger.debug("Deleted chunks for source: %s", fp)

            logger.info(
                "Deleted chunks for %d source file(s).", len(file_paths)
            )
            return len(file_paths)

        except Exception as exc:
            raise IndexingError(
                "Failed to delete documents by source.",
                detail=str(exc),
            ) from exc

    # -- querying ----------------------------------------------------------

    def query(
        self,
        text: str,
        n_results: int = 5,
        workspace_id: Optional[str] = None,
    ) -> List[QueryResult]:
        """Embed *text* and retrieve the closest chunks.

        Args:
            text: Natural-language query string.
            n_results: Maximum number of results to return.
            workspace_id: If provided, restrict results to chunks
                belonging to this workspace.

        Returns:
            List of :class:`QueryResult` sorted by ascending distance.

        Raises:
            IndexingError: If the query operation fails.
            EmbeddingError: If query embedding fails.
        """
        if self._collection is None:
            raise IndexingError("ChromaDB collection is not available.")

        try:
            query_embedding: List[List[float]] = self._embed([text])

            query_kwargs: Dict[str, Any] = {
                "query_embeddings": query_embedding,
                "n_results": min(n_results, self._collection.count() or 1),
                "include": ["documents", "metadatas", "distances"],
            }
            if workspace_id is not None:
                query_kwargs["where"] = {"workspace_id": {"$eq": workspace_id}}

            raw: Dict[str, Any] = self._collection.query(**query_kwargs)
        except (EmbeddingError, IndexingError):
            raise
        except Exception as exc:
            raise IndexingError(
                "Query execution failed.",
                detail=str(exc),
            ) from exc

        results: List[QueryResult] = []
        documents: List[Optional[str]] = (raw.get("documents") or [[]])[0]
        metadatas: List[Optional[Dict[str, Any]]] = (
            raw.get("metadatas") or [[]]
        )[0]
        distances: List[float] = (raw.get("distances") or [[]])[0]

        for doc, meta, dist in zip(documents, metadatas, distances):
            results.append(
                QueryResult(
                    content=doc or "",
                    metadata=meta or {},
                    distance=dist,
                )
            )

        logger.info(
            "Query returned %d result(s) for: '%.60s…'",
            len(results),
            text,
        )
        return results

    # -- incremental sync --------------------------------------------------

    def incremental_sync(self, vault_path: str) -> int:
        """Perform hash-based incremental sync of the vault.

        Walks all ``.md`` files under *vault_path*, compares SHA-256
        hashes against the ``SyncTracker`` registry, and only re-indexes
        files whose content has changed.

        Args:
            vault_path: Absolute or relative path to the vault directory.

        Returns:
            Total number of chunks upserted across all changed files.

        Raises:
            IndexingError: If ChromaDB operations fail.
        """
        import hashlib
        from pathlib import Path

        if self._collection is None:
            raise IndexingError("ChromaDB collection is not available.")

        tracker = SyncTracker(str(self._settings.resolved_sync_state_path))
        parser = SemanticMarkdownParser()
        vault = Path(vault_path).resolve()

        if not vault.exists():
            logger.warning("Vault path does not exist: %s", vault)
            return 0

        md_files = sorted(vault.rglob("*.md"))
        logger.info(
            "Incremental sync: found %d .md file(s) in %s.",
            len(md_files),
            vault,
        )

        total_upserted: int = 0

        for md_path in md_files:
            filepath: str = str(md_path)

            # Calculate current hash.
            current_hash: str = compute_sha256(md_path)
            stored_hash: str = tracker.get_file_state(filepath)

            if current_hash == stored_hash:
                logger.debug("Skipping unchanged file: %s", filepath)
                continue

            logger.info("Processing changed file: %s", md_path.name)

            # 1 — Delete stale chunks for this file.
            try:
                self._collection.delete(
                    where={"source_file": {"$eq": md_path.name}}
                )
                logger.debug(
                    "Deleted stale chunks for: %s", md_path.name
                )
            except Exception as exc:
                logger.warning(
                    "Could not delete old chunks for %s (may be first index): %s",
                    md_path.name,
                    exc,
                )

            # 2 — Parse file into semantic chunks.
            try:
                chunks = parser.parse_file(filepath)
            except Exception as exc:
                logger.error(
                    "Failed to parse %s — skipping. %s", filepath, exc
                )
                continue

            if not chunks:
                logger.debug("No chunks produced for %s.", filepath)
                continue

            # 3 — Embed and upsert into ChromaDB.
            try:
                # Ensure every chunk carries a workspace_id for scoped queries.
                for c in chunks:
                    meta = c.get("metadata", {})
                    if not meta.get("workspace_id"):
                        meta["workspace_id"] = "ws-default"

                contents = [c["page_content"] for c in chunks]
                metadatas = [
                    self._sanitize_metadata(c["metadata"]) for c in chunks
                ]
                # Generate deterministic IDs from note_id + chunk index.
                note_id: str = (
                    chunks[0].get("metadata", {}).get("note_id", "unknown")
                )
                ids = [
                    hashlib.sha256(
                        f"{note_id}::{i}".encode("utf-8")
                    ).hexdigest()[:16]
                    for i in range(len(chunks))
                ]
                embeddings = self._embed(contents)

                self._collection.upsert(
                    ids=ids,
                    documents=contents,
                    metadatas=metadatas,
                    embeddings=embeddings,
                )
                total_upserted += len(chunks)
                logger.info(
                    "Upserted %d chunk(s) for %s.",
                    len(chunks),
                    md_path.name,
                )
            except (EmbeddingError, IndexingError):
                raise
            except Exception as exc:
                logger.error(
                    "Failed to index chunks for %s: %s", filepath, exc
                )
                continue

            # 4 — Update sync state.
            tracker.update_file_state(filepath, current_hash, note_id)

        # 5 — Mark the sync time globally
        tracker.update_sync_time()

        logger.info(
            "Incremental sync complete — %d chunk(s) upserted.",
            total_upserted,
        )
        return total_upserted

    # -- stats -------------------------------------------------------------

    def get_collection_stats(self) -> Dict[str, Any]:
        """Return basic statistics about the active collection.

        Returns:
            Dictionary with ``count`` and ``collection_name`` keys.
        """
        if self._collection is None:
            return {"count": 0, "collection_name": None}

        count: int = self._collection.count()
        return {
            "count": count,
            "collection_name": self._settings.chroma_collection_name,
        }

    # -- similarity computation ---------------------------------------------

    def compute_similarities(
        self,
        rel_paths: List[str],
        vault_root: str,
        structural_pairs: set,
        file_contents: dict
    ) -> None:
        """Background task to precompute semantic similarities and populate cache."""
        try:
            import numpy as np
            from personal_os.core import graph_cache
            from pathlib import Path
            
            if self._collection is None or len(rel_paths) < 2:
                return
            
            doc_vectors = {}
            for rel in rel_paths:
                abs_path = str((Path(vault_root) / rel).resolve())
                try:
                    result = self._collection.get(
                        where={"file_path": {"$eq": abs_path}},
                        include=["embeddings"]
                    )
                    embeddings = result.get("embeddings")
                    if embeddings and len(embeddings) > 0:
                        arr = np.array(embeddings, dtype=np.float32)
                        mean_vec = arr.mean(axis=0)
                        norm = np.linalg.norm(mean_vec)
                        if norm > 0:
                            doc_vectors[rel] = mean_vec / norm
                except Exception:
                    continue
            
            indexed_paths = list(doc_vectors.keys())
            if len(indexed_paths) < 2:
                logger.info(f"Skipping semantic edge calculation: insufficient nodes (found {len(indexed_paths)}). At least 2 documents are required to form relationships.")
                return
            for i in range(len(indexed_paths)):
                for j in range(i + 1, len(indexed_paths)):
                    pa, pb = indexed_paths[i], indexed_paths[j]
                    pair = frozenset({pa, pb})
                    if pair in structural_pairs:
                        continue
                    if graph_cache.get_cached_similarity(pair) is None:
                        sim = float(np.dot(doc_vectors[pa], doc_vectors[pb]))
                        graph_cache.set_cached_similarity(pair, sim)
            logger.info("Background similarity computation complete.")
        except Exception as exc:
            logger.error(f"Failed background similarity computation: {exc}")

    # -- internal helpers --------------------------------------------------

    @staticmethod
    def _sanitize_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Ensure all metadata values are ChromaDB-compatible scalar types.

        ChromaDB only supports ``str | int | float | bool`` as metadata
        values.  This method stringifies anything else.

        Args:
            metadata: Raw metadata dictionary.

        Returns:
            Sanitized copy safe for ChromaDB upsert.
        """
        clean: Dict[str, Any] = {}
        for key, value in metadata.items():
            if isinstance(value, (str, int, float, bool)):
                clean[key] = value
            else:
                clean[key] = str(value)
        return clean
