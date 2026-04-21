import sys
from pathlib import Path


def get_resource_path(relative_path: str) -> Path:
    """Absolute path to a **read-only, bundled** resource.

    When frozen (PyInstaller), resolves inside ``sys._MEIPASS`` — the
    temporary extraction directory.  Use this ONLY for assets that ship
    inside the binary (templates, locales, static files).
    """
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        base_path = Path(sys._MEIPASS)
    else:
        base_path = Path(__file__).resolve().parent.parent

    return base_path / relative_path


def get_user_data_path(relative_path: str) -> Path:
    """Absolute path to **persistent, mutable** user data.

    When frozen, resolves under ``~/.imbuto/`` so that vault files,
    ChromaDB, sync-state, budget-state, and logs survive across
    application restarts.
    """
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        base_path = Path.home() / ".imbuto"
    else:
        base_path = Path(__file__).resolve().parent.parent

    return base_path / relative_path


def get_user_config_path(relative_path: str) -> Path:
    """Absolute path to **persistent, mutable** config files (.env, etc.).

    When frozen, resolves under ``~/.imbuto/`` — never inside the
    read-only ``sys._MEIPASS`` bundle.  In dev, resolves relative to
    the project root.
    """
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        base_path = Path.home() / ".imbuto"
    else:
        base_path = Path(__file__).resolve().parent.parent

    return base_path / relative_path
