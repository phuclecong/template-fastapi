"""Vercel entrypoint — exposes the FastAPI ``app`` from the ``src/`` layout.

Vercel's Python runtime auto-detects a top-level ``app`` in ``main.py`` at the
project root. This project's modules live under ``src/`` and import each other as
``app.*``, so ``src/`` is added to ``sys.path`` before the import. Application
code stays unchanged.

Local development still uses ``uv run uvicorn app.main:app --reload``.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from app.main import app

__all__ = ["app"]
