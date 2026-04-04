"""Root conftest.py — ensures project root is on sys.path for test discovery."""

from __future__ import annotations

import os
import sys

_PROJECT_ROOT = os.path.dirname(__file__)

# Ensure the project root is on sys.path so all project packages are importable.
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# Force Qt to use the offscreen platform so all tests run headless.
# Must be set before any PySide6 import, which is why it lives here.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
