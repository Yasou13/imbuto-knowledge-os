import hashlib
import json
import os
import uuid
from filelock import FileLock
from pathlib import Path
from typing import Union, Dict, Any

def compute_sha256(data: Union[str, bytes, Path]) -> str:
    """
    Compute a SHA-256 hash robustly.
    Handles strings, raw bytes, and file paths (read in 64KB chunks).
    """
    hasher = hashlib.sha256()
    
    if isinstance(data, Path):
        with open(data, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                hasher.update(chunk)
    elif isinstance(data, str):
        hasher.update(data.encode("utf-8"))
    elif isinstance(data, bytes):
        hasher.update(data)
    else:
        raise TypeError(f"Unsupported data type for hashing: {type(data)}")
        
    return hasher.hexdigest()

def atomic_json_write(file_path: Union[str, Path], data: Dict[str, Any]) -> None:
    """Safely and atomically write JSON data to disk across platforms."""
    target_path = Path(file_path)
    tmp_path = target_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    lock_path = target_path.with_suffix(f"{target_path.suffix}.lock")
    
    try:
        with FileLock(str(lock_path)):
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, target_path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
