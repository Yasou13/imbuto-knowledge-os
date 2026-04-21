"""
Graph similarity cache — hash-based invalidation for pairwise cosine scores.

Module-level singleton dict cache that avoids recalculating cosine similarity
for file-pairs whose content hasn't changed (SHA-256 digest comparison).
"""

from __future__ import annotations

import hashlib
import logging
import threading
from typing import Dict, FrozenSet, Optional, Set

from personal_os.core.utils import compute_sha256

logger = logging.getLogger("imbuto.graph_cache")

# ---------------------------------------------------------------------------
# Module-level state (singleton cache)
# ---------------------------------------------------------------------------

# vault-relative path → SHA-256 hex digest of file content
_file_hashes: Dict[str, str] = {}

# frozenset({pathA, pathB}) → cosine similarity score
_sim_cache: Dict[FrozenSet[str], float] = {}

# Thread lock for concurrent access
_lock: threading.Lock = threading.Lock()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------



def is_stale(path: str, current_hash: str) -> bool:
    """Return ``True`` if *path* has no cached hash or the hash differs."""
    with _lock:
        return _file_hashes.get(path) != current_hash


def update_hash(path: str, new_hash: str) -> None:
    """Store *new_hash* for *path* and invalidate all pairs involving it."""
    with _lock:
        old = _file_hashes.get(path)
        if old == new_hash:
            return
        _file_hashes[path] = new_hash
        _invalidate_pairs(path)


def get_cached_similarity(pair: FrozenSet[str]) -> Optional[float]:
    """Return cached similarity for *pair*, or ``None`` if absent."""
    with _lock:
        result = _sim_cache.get(pair)
        if result is not None:
            paths = sorted(pair)
            logger.info("Graph cache HIT for %s ↔ %s (sim=%.4f)", paths[0], paths[1], result)
        return result


def set_cached_similarity(pair: FrozenSet[str], score: float) -> None:
    """Store the similarity *score* for *pair*."""
    with _lock:
        paths = sorted(pair)
        logger.info("Graph cache MISS — computed %s ↔ %s (sim=%.4f)", paths[0], paths[1], score)
        _sim_cache[pair] = score


def clear() -> None:
    """Reset all caches (useful for testing)."""
    with _lock:
        _file_hashes.clear()
        _sim_cache.clear()


# ---------------------------------------------------------------------------
# Internal (must be called with _lock held)
# ---------------------------------------------------------------------------


def _invalidate_pairs(path: str) -> None:
    """Remove every cached pair that involves *path*."""
    stale_keys: Set[FrozenSet[str]] = {
        k for k in _sim_cache if path in k
    }
    for k in stale_keys:
        del _sim_cache[k]
