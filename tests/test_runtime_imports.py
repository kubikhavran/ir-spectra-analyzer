"""Regression tests for runtime imports outside pytest's conftest bootstrap."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_runtime_import_helper_enables_project_local_io_package():
    """The runtime bootstrap should make `io.format_registry` importable in a clean Python process."""
    repo_root = Path(__file__).resolve().parents[1]
    script = """
from app.runtime_imports import install_project_imports
install_project_imports()
from file_io.format_registry import FormatRegistry
print(FormatRegistry.__name__)
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "FormatRegistry"


def test_runtime_import_helper_reads_real_spa_fixture():
    """A clean Python process should be able to load a real `.SPA` fixture after bootstrap."""
    repo_root = Path(__file__).resolve().parents[1]
    script = """
from pathlib import Path
from app.runtime_imports import install_project_imports
install_project_imports()
from file_io.format_registry import FormatRegistry
spec = FormatRegistry().read(Path('tests/fixtures/0min-1-97C.SPA'))
print(spec.n_points, spec.y_unit.value)
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "55587" in result.stdout
