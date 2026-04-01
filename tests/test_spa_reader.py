"""Tests for SPA file reader."""
from __future__ import annotations

from pathlib import Path

import pytest


def test_spa_reader_raises_on_missing_file() -> None:
    """SPAReader should raise FileNotFoundError for non-existent files."""
    from io.spa_reader import SPAReader

    reader = SPAReader()
    with pytest.raises(FileNotFoundError):
        reader.read(Path("/nonexistent/file.spa"))
