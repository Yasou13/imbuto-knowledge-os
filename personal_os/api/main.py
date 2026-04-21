"""
IMBUTO OS — FastAPI REST API.

Exposes the headless core engine (VectorStore, LLMGateway, QueryOrchestrator,
FileManager, WorkspaceManager) over HTTP so a decoupled React frontend can
consume it.
"""

from __future__ import annotations

import logging
import os
import re
from urllib.parse import unquote
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Dict, FrozenSet, List, Optional, Set


from fastapi import FastAPI, HTTPException, Query, BackgroundTasks, Depends, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from personal_os.config.settings import Settings
from personal_os.core.file_manager import FileManager
from personal_os.core.llm_gateway import LLMGateway
from personal_os.core.orchestrator import QueryOrchestrator
from personal_os.core.schemas import ContextSource
from personal_os.core.vector_store import VectorStoreManager
from personal_os.core.workspace import WorkspaceManager
from personal_os.core import graph_cache
from personal_os.core import link_blacklist
from personal_os.core.utils import compute_sha256

logger: logging.Logger = logging.getLogger("imbuto.api")


_active_syncs: Set[str] = set()

# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------


class SystemStatusResponse(BaseModel):
    """Payload for ``GET /api/status``."""

    status: str
    version: str
    workspace: str
    document_count: int
    chunk_count: int
    last_sync_time: Optional[str]


class GraphNode(BaseModel):
    id: str
    name: str
    group: str


class GraphLink(BaseModel):
    source: str
    target: str
    type: str          # "structural" | "semantic"
    weight: float      # 1.0 for structural; cosine score for semantic
    reason: Optional[str] = None  # semantic link: "Common topics: [X, Y, Z]"


class GraphDataResponse(BaseModel):
    """Payload for ``GET /api/graph``."""
    nodes: List[GraphNode]
    links: List[GraphLink]
    warnings: List[str] = Field(default_factory=list)


class BlacklistRequest(BaseModel):
    """Payload for ``POST/DELETE /api/graph/blacklist``."""
    source: str
    target: str


class BlacklistResponse(BaseModel):
    """Payload for ``GET /api/graph/blacklist``."""
    pairs: List[List[str]]


class SaveRequest(BaseModel):
    """Payload for ``POST /api/save``."""

    filename: str = Field(..., description="Vault-relative path (must end with .md)")
    content: str = Field(..., description="Full Markdown content to write")
    workspace_id: str = Field(default="ws-default", description="Target workspace identifier")


class SaveResponse(BaseModel):
    """Response for ``POST /api/save`` — aligned with Frontend SaveResponse."""

    saved: bool
    path: str
    synced_chunks: int


class QueryRequest(BaseModel):
    """Payload for ``POST /api/query``."""

    query: str = Field(..., description="Natural-language question")
    workspace_id: str = Field(default="ws-default", description="Workspace to scope retrieval to")
    model: str = Field(default="", description="LiteLLM model identifier (uses default if empty)")
    current_file_context: Optional[str] = Field(default=None, description="Raw content of the active file")
    cursor_position: int = Field(default=0, description="Active character offset in the editor")



class QueryResponse(BaseModel):
    """Response for ``POST /api/query`` — aligned with Frontend QueryResponse."""

    answer: str
    context: List[ContextSource] = Field(default_factory=list)


class FileMetadata(BaseModel):
    """Metadata for a single vault file."""

    name: str
    path: str
    size: int
    last_modified: str


class FileDetail(BaseModel):
    """Full file detail with content and Inspector metadata."""

    name: str
    path: str
    content: str
    size: int
    last_modified: str
    token_count: int
    chunk_count: int
    wikilinks: List[str] = Field(default_factory=list)


class FilesListResponse(BaseModel):
    """Response for ``GET /api/files``."""

    workspace_id: Optional[str]
    files: List[FileMetadata]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_WIKILINK_RE = re.compile(r"\[\[([^\]|]+?)(?:\|[^\]]+?)?\]\]")


def _extract_wikilinks(content: str) -> List[str]:
    """Extract unique ``[[wikilink]]`` targets from markdown content."""
    return sorted(set(_WIKILINK_RE.findall(content)))


# Compact stopword set (English + common Turkish)
_STOPWORDS = frozenset(
    "a an the and or but in on at to for of is it this that with from by as are"
    " was were be been has have had do does did will would can could not no nor"
    " so if then than too very just about up out all more also how when where"
    " which who what why its my your he she we they i you me him her us them"
    " bir ve ile de da bu o bir için gibi daha ne nasıl kadar olan ile olarak"
    " ise veya ya hem ama ancak fakat çok en her hangi bazı".split()
)

_WORD_RE = re.compile(r"[a-zA-ZçğıöşüÇĞİÖŞÜ]{3,}")


def _extract_keywords(text: str, top_n: int = 20) -> List[str]:
    """Return the *top_n* highest-frequency non-stopword words."""
    from collections import Counter
    words = _WORD_RE.findall(text.lower())
    counts = Counter(w for w in words if w not in _STOPWORDS)
    return [w for w, _ in counts.most_common(top_n)]


def _compute_reason(content_a: str, content_b: str) -> Optional[str]:
    """Return a reason string from the top-3 shared keywords, or ``None``."""
    kw_a = set(_extract_keywords(content_a))
    kw_b = set(_extract_keywords(content_b))
    shared = kw_a & kw_b
    if not shared:
        return None
    # Rank by combined frequency
    from collections import Counter
    words_a = _WORD_RE.findall(content_a.lower())
    words_b = _WORD_RE.findall(content_b.lower())
    combo = Counter(w for w in words_a if w in shared) + Counter(w for w in words_b if w in shared)
    top3 = [w for w, _ in combo.most_common(3)]
    return f"Common topics: [{', '.join(top3)}]"


def _estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars per token for English text)."""
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except (ImportError, Exception):
        return len(text) // 4


def _file_metadata(abs_path: Path, vault_root: Path) -> FileMetadata:
    """Build a FileMetadata from an absolute path."""
    stat = abs_path.stat()
    rel = str(abs_path.relative_to(vault_root))
    modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
    return FileMetadata(
        name=abs_path.name,
        path=rel,
        size=stat.st_size,
        last_modified=modified,
    )


# ---------------------------------------------------------------------------
# Application lifespan — initialise & tear down core services
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage startup / shutdown of heavyweight core services."""

    settings = Settings()
    logger.info("IMBUTO API starting — initialising core services …")

    if not settings.resolved_vault_path.exists():
        os.makedirs(settings.resolved_vault_path, exist_ok=True)

    try:
        from personal_os.core.workspace import cleanup_orphaned_tmp_files
        cleanup_orphaned_tmp_files(settings.resolved_vault_path)
    except Exception as exc:
        logger.error("Failed to execute boot-time garbage collection: %s", exc)

    try:
        vector_store = VectorStoreManager(settings)
    except Exception as e:
        import logging
        from pathlib import Path
        _logger = logging.getLogger("imbuto.api")
        _logger.warning(f"VectorStore initialization failed: {e}. Attempting to clear locks...")
        
        lock_file = Path(settings.resolved_chroma_persist_dir) / "chroma.sqlite3-wal"
        
        if lock_file.exists():
            lock_file.unlink()
            _logger.info("Stale lock file removed. Retrying initialization...")
            vector_store = VectorStoreManager(settings)
        else:
            _logger.error("Critical: VectorStore failed and no lock file found to clear.")
            raise e
    vector_store.__enter__()

    llm_gateway = LLMGateway(settings)
    file_manager = FileManager(settings)
    workspace_manager = WorkspaceManager()
    orchestrator = QueryOrchestrator(settings, vector_store, llm_gateway)

    app.state.settings = settings
    app.state.vector_store = vector_store
    app.state.llm_gateway = llm_gateway
    app.state.file_manager = file_manager
    app.state.workspace_manager = workspace_manager
    app.state.orchestrator = orchestrator

    # Initialise link blacklist (data dir = parent of vault, e.g. data/)
    data_dir = settings.resolved_vault_path.parent
    link_blacklist.init(data_dir)

    logger.info("IMBUTO API ready.")
    yield

    logger.info("IMBUTO API shutting down — releasing resources …")
    vector_store.__exit__(None, None, None)


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

import hmac

async def verify_internal_token(request: Request, x_internal_token: str = Header(default="")):
    # Bypass auth for the unauthenticated health-check used by Electron bootstrap
    if request.url.path == "/health":
        return
    expected_token = os.environ.get("IMBUTO_INTERNAL_TOKEN")
    if not expected_token or not hmac.compare_digest(x_internal_token, expected_token):
        raise HTTPException(status_code=401, detail="Unauthorized")

app = FastAPI(
    title="IMBUTO OS API",
    description="REST gateway for the IMBUTO Knowledge OS core.",
    version="1.0.0",
    lifespan=lifespan,
    dependencies=[Depends(verify_internal_token)],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["app://.", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
async def health_check() -> Dict[str, str]:
    """Liveness probe."""
    vs: VectorStoreManager = app.state.vector_store
    try:
        stats = vs.get_collection_stats()
        db_status = f"connected ({stats.get('count', 0)} chunks)"
    except Exception:
        db_status = "disconnected"

    return {"status": "ok", "vector_db": db_status}


@app.get("/api/status", response_model=SystemStatusResponse)
async def system_status(
    workspace_id: Optional[str] = Query(default=None, description="Scope to workspace if provided")
) -> SystemStatusResponse:
    """Return real-time system status including document counts and last sync time."""
    vs: VectorStoreManager = app.state.vector_store
    fm: FileManager = app.state.file_manager

    # 1. Document count
    try:
        # In a real workspace scenario, this would filter by workspace paths.
        # For now, we list all files mapped by FileManager.
        document_count = len(fm.list_files())
    except Exception:
        document_count = 0

    # 2. Chunk count
    try:
        chunk_count = vs.get_collection_stats().get("count", 0)
    except Exception:
        chunk_count = 0

    # 3. Last sync time
    last_sync_time = None
    try:
        from personal_os.core.sync_tracker import SyncTracker
        settings = app.state.settings
        tracker = SyncTracker(str(settings.resolved_sync_state_path))
        last_sync_time = tracker.get_last_sync()
    except Exception:
        pass

    return SystemStatusResponse(
        status="running",
        version="1.0.0",
        workspace=workspace_id or "global",
        document_count=document_count,
        chunk_count=chunk_count,
        last_sync_time=last_sync_time,
    )


@app.get("/api/workspaces")
async def list_workspaces() -> List[Dict[str, Any]]:
    """Return every registered workspace from the JSON registry."""
    wm: WorkspaceManager = app.state.workspace_manager
    return wm.list_workspaces()


# ---------------------------------------------------------------------------
# File endpoints
# ---------------------------------------------------------------------------


@app.get("/api/files", response_model=FilesListResponse)
async def list_files(
    workspace_id: Optional[str] = Query(default=None, description="Filter by workspace"),
) -> FilesListResponse:
    """List Markdown files with metadata, optionally scoped to a workspace."""
    fm: FileManager = app.state.file_manager
    wm: WorkspaceManager = app.state.workspace_manager
    vault_root: Path = fm.vault_path

    if workspace_id:
        try:
            ws = wm.get_workspace(workspace_id)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' not found")

        file_metas: List[FileMetadata] = []
        for ws_path in ws.get("paths", []):
            ws_dir = Path(ws_path).resolve()
            if ws_dir.exists() and ws_dir.is_dir():
                for p in sorted(ws_dir.rglob("*.md")):
                    if p.is_file():
                        file_metas.append(_file_metadata(p, ws_dir))
        return FilesListResponse(workspace_id=workspace_id, files=file_metas)

    # Global — scan from vault root
    file_metas = [_file_metadata(p, vault_root) for p in fm.list_files()]
    return FilesListResponse(workspace_id=None, files=file_metas)


@app.get("/api/graph", response_model=GraphDataResponse)
async def get_graph_data(
    background_tasks: BackgroundTasks,
    workspace_id: Optional[str] = Query(default=None, description="Scope to workspace if provided"),
    folder_path: Optional[str] = Query(default=None, description="Limit to folder (vault-relative)"),
) -> GraphDataResponse:
    """Return the full Adaptive-Linking-Engine graph.

    Combines **structural** edges (`[[wikilinks]]`) directly in response,
    and enqueues **semantic** edges computation in the background.
    """
    import time

    _log = logging.getLogger("imbuto.graph")

    fm: FileManager = app.state.file_manager
    vs: VectorStoreManager = app.state.vector_store
    vault_root: Path = fm.vault_path

    nodes: List[GraphNode] = []
    links: List[GraphLink] = []
    graph_warnings: List[str] = []

    try:
        t0 = time.perf_counter()
        files = fm.list_files()

        # ------------------------------------------------------------------
        # Pass 1 — nodes, structural edges, file hashes
        # ------------------------------------------------------------------
        structural_pairs: Set[FrozenSet[str]] = set()

        stem_to_rel: Dict[str, str] = {}
        rel_paths: List[str] = []
        file_contents: Dict[str, str] = {}

        for f in files:
            try:
                rel = str(f.relative_to(vault_root))
                content = fm.read_file(rel)
            except Exception:
                continue

            # Folder scoping: skip files outside the requested folder
            if folder_path and not rel.startswith(folder_path.rstrip("/") + "/") and rel != folder_path:
                continue

            parent = str(f.relative_to(vault_root).parent)
            group = parent if parent != "." else "root"
            nodes.append(GraphNode(id=rel, name=f.stem, group=group))
            stem_to_rel[f.stem] = rel
            rel_paths.append(rel)
            file_contents[rel] = content

            h = compute_sha256(content)
            graph_cache.update_hash(rel, h)

            for target_name in _extract_wikilinks(content):
                target_rel = stem_to_rel.get(target_name)
                if target_rel and target_rel != rel:
                    pair = frozenset({rel, target_rel})
                    if pair not in structural_pairs:
                        structural_pairs.add(pair)
                        links.append(
                            GraphLink(
                                source=rel,
                                target=target_rel,
                                type="structural",
                                weight=1.0,
                            )
                        )

        # Second pass — resolve forward-references
        for rel, content in file_contents.items():
            for target_name in _extract_wikilinks(content):
                target_rel = stem_to_rel.get(target_name)
                if target_rel and target_rel != rel:
                    pair = frozenset({rel, target_rel})
                    if pair not in structural_pairs:
                        structural_pairs.add(pair)
                        links.append(
                            GraphLink(
                                source=rel,
                                target=target_rel,
                                type="structural",
                                weight=1.0,
                            )
                        )

        t_structural = time.perf_counter()
        _log.info(
            "Pass 1 done: %d nodes, %d structural edges (%.2fs)",
            len(nodes), len(links), t_structural - t0,
        )

        # ------------------------------------------------------------------
        # Pass 2 — Semantic edges (offloaded to background!)
        # ------------------------------------------------------------------
        if len(rel_paths) >= 2 and vs._collection is not None:
            background_tasks.add_task(
                vs.compute_similarities,
                rel_paths,
                str(vault_root),
                structural_pairs=structural_pairs,
                file_contents=file_contents
            )
            graph_warnings.append("Semantic similarities are computing in background")

        t_total = time.perf_counter()
        _log.info(
            "Structural Graph complete: %d nodes, %d edges (%.2fs total)",
            len(nodes), len(links), t_total - t0,
        )

    except Exception as exc:
        _log.error("Graph endpoint error: %s — returning partial graph", exc, exc_info=True)

    # Filter out blacklisted edges
    links = [
        lnk for lnk in links
        if not link_blacklist.is_blacklisted(frozenset({lnk.source, lnk.target}))
    ]

    return GraphDataResponse(nodes=nodes, links=links, warnings=graph_warnings)


# ---------------------------------------------------------------------------
# Blacklist endpoints
# ---------------------------------------------------------------------------


@app.get("/api/graph/blacklist", response_model=BlacklistResponse)
async def get_blacklist() -> BlacklistResponse:
    """Return all blacklisted (ignored) link pairs."""
    return BlacklistResponse(pairs=link_blacklist.get_all())


@app.post("/api/graph/blacklist", response_model=BlacklistResponse)
async def add_to_blacklist(payload: BlacklistRequest) -> BlacklistResponse:
    """Add a link pair to the blacklist."""
    link_blacklist.add_pair(payload.source, payload.target)
    return BlacklistResponse(pairs=link_blacklist.get_all())


@app.delete("/api/graph/blacklist", response_model=BlacklistResponse)
async def remove_from_blacklist(payload: BlacklistRequest) -> BlacklistResponse:
    """Remove a link pair from the blacklist."""
    link_blacklist.remove_pair(payload.source, payload.target)
    return BlacklistResponse(pairs=link_blacklist.get_all())


@app.get("/api/files/{file_path:path}", response_model=FileDetail)
async def get_file(file_path: str) -> FileDetail:
    """Return raw content + detailed metadata for a single file.

    Provides token_count, chunk_count (from ChromaDB), and extracted wikilinks
    for the Frontend Inspector panel.
    """
    fm: FileManager = app.state.file_manager
    vs: VectorStoreManager = app.state.vector_store
    vault_root: Path = fm.vault_path

    # Decode percent-encoded path segments from the frontend
    file_path = unquote(file_path)

    try:
        content = fm.read_file(file_path)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    abs_path = (vault_root / file_path).resolve()
    stat = abs_path.stat()
    modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()

    # Token count
    token_count = _estimate_tokens(content)

    # Chunk count from ChromaDB — count chunks whose file_path metadata matches
    chunk_count = 0
    try:
        collection = vs._collection
        if collection is not None:
            results = collection.get(
                where={"file_path": {"$eq": str(abs_path)}},
                include=[],
            )
            chunk_count = len(results.get("ids", []))
    except Exception:
        pass

    # Extract wikilinks
    wikilinks = _extract_wikilinks(content)

    return FileDetail(
        name=abs_path.name,
        path=file_path,
        content=content,
        size=stat.st_size,
        last_modified=modified,
        token_count=token_count,
        chunk_count=chunk_count,
        wikilinks=wikilinks,
    )


# ---------------------------------------------------------------------------
# Save endpoint
# ---------------------------------------------------------------------------


def _background_sync(settings: Settings, vs: VectorStoreManager, workspace_id: str = "global") -> None:
    """Safe background worker for vector store synchronization."""
    try:
        synced_chunks = vs.incremental_sync(str(settings.resolved_vault_path))
        logger.info("Background sync complete. %d chunks synced.", synced_chunks)
    except Exception as exc:
        logger.error("Background sync failed automatically. Error: %s", exc)
    finally:
        _active_syncs.discard(workspace_id)

@app.post("/api/save", response_model=SaveResponse)
async def save_file(payload: SaveRequest, background_tasks: BackgroundTasks) -> SaveResponse:
    """Write a Markdown file and trigger background incremental vector sync."""
    fm: FileManager = app.state.file_manager
    vs: VectorStoreManager = app.state.vector_store
    settings: Settings = app.state.settings

    try:
        abs_path = fm.write_file(payload.filename, payload.content)
    except (ValueError, Exception) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    _active_syncs.add("global")
    background_tasks.add_task(_background_sync, settings, vs, "global")

    return SaveResponse(
        saved=True,
        path=str(abs_path),
        synced_chunks=0,
    )

@app.get("/api/sync-status")
async def sync_status() -> Dict[str, bool]:
    """Return whether background sync is active."""
    return {"is_syncing": len(_active_syncs) > 0}


# ---------------------------------------------------------------------------
# Query endpoint
# ---------------------------------------------------------------------------


@app.post("/api/query", response_model=QueryResponse)
async def query_knowledge(payload: QueryRequest) -> QueryResponse:
    """Execute a RAG query and return the answer + full source context."""
    orchestrator: QueryOrchestrator = app.state.orchestrator
    settings: Settings = app.state.settings

    model_name: str = payload.model or settings.default_model
    workspace_id: Optional[str] = payload.workspace_id or None

    try:
        result = orchestrator.ask(
            query=payload.query,
            model_name=model_name,
            workspace_id=workspace_id,
            current_file_context=payload.current_file_context,
            cursor_position=payload.cursor_position,
        )
    except Exception as exc:
        logger.exception("Query failed.")
        raise HTTPException(status_code=500, detail=str(exc))

    return QueryResponse(answer=result.answer, context=result.sources)
