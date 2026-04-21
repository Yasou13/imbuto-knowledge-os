import os
import sys
import logging
import signal
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

# ── Secure external .env loading ─────────────────────────────────────
_ENV_DIR = Path.home() / ".imbuto"
_ENV_PATH = _ENV_DIR / ".env"

if not _ENV_DIR.exists():
    _ENV_DIR.mkdir(parents=True, exist_ok=True)

if _ENV_PATH.exists():
    load_dotenv(dotenv_path=_ENV_PATH)
else:
    logging.warning(
        "No .env file found at %s — API keys will be missing. "
        "Create this file with your credentials.",
        _ENV_PATH,
    )

# ── Boot the API ─────────────────────────────────────────────────────
from personal_os.api.main import app  # noqa: E402

if __name__ == "__main__":
    config = uvicorn.Config(app, host="127.0.0.1", port=8000)
    server = uvicorn.Server(config)

    def _signal_handler(signum, frame):
        logging.info("Received signal %s, triggering Uvicorn graceful shutdown...", signum)
        server.should_exit = True

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    server.run()
