"""
Internationalization (i18n) module for the Personal IMBUTO OS.

Provides a :class:`Translator` that loads language strings from
JSON files in the ``locales/`` directory.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict

logger: logging.Logger = logging.getLogger("imbuto.translator")

import sys
import os

def get_locales_path() -> Path:
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS) / 'locales'
    return (Path(__file__).resolve().parent.parent / 'locales').resolve()

_LOCALES_DIR: Path = get_locales_path()


class Translator:
    """Simple i18n translator loading JSON key-value stores.

    Args:
        language: Language code (e.g., ``en`` or ``tr``).
            Defaults to ``en``.
    """

    def __init__(self, language: str = "en") -> None:
        self.language: str = language
        self._translations: Dict[str, str] = self._load_locale(language)

    def _load_locale(self, lang: str) -> Dict[str, str]:
        """Load JSON from locales folder, fallback to empty dict."""
        path = _LOCALES_DIR / f"{lang}.json"
        if not path.exists():
            logger.warning("Locale file not found: %s", path)
            # Try fallback to en
            if lang != "en":
                fallback = _LOCALES_DIR / "en.json"
                if fallback.exists():
                    logger.info("Falling back to en.json")
                    with fallback.open("r", encoding="utf-8") as f:
                        return json.load(f)
            return {}

        try:
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as exc:
            logger.error("Failed to parse locale %s: %s", path, exc)
            return {}

    def t(self, key: str) -> str:
        """Get translated string for key, falling back to key itself."""
        return self._translations.get(key, key)

    def has(self, key: str) -> bool:
        """Check whether a translation key exists."""
        return key in self._translations
