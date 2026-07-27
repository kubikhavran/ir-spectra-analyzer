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


# The lab reference library under tests/fixtures/reference library_1/ holds the
# analyst's authentic spectra and is deliberately gitignored, so a fresh clone
# does not have it. Tests that need it are marked `lab_fixtures` and skip when
# it is absent instead of failing.
LAB_LIBRARY = os.path.join(_PROJECT_ROOT, "tests", "fixtures", "reference library_1")


def pytest_configure(config) -> None:
    config.addinivalue_line(
        "markers",
        "lab_fixtures: requires the lab reference library (not part of the repository)",
    )


def pytest_collection_modifyitems(config, items) -> None:
    import glob

    import pytest

    if glob.glob(os.path.join(LAB_LIBRARY, "*.SPA")):
        return
    skip_marker = pytest.mark.skip(reason="lab reference library is not part of the repository")
    for item in items:
        if "lab_fixtures" in item.keywords:
            item.add_marker(skip_marker)
