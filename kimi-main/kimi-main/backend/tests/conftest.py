"""Pytest bootstrap for backend tests."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure `backend/` is importable so tests can resolve the `app` package.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
