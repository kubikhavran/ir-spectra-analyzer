"""Tests for reference-library folder scanning."""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.reference_import import ReferenceImportService

_FIXTURE = Path("tests/fixtures/reference library_1/FER58-SE.SPA")


def _service() -> ReferenceImportService:
    return ReferenceImportService(MagicMock())


def test_scan_folder_is_recursive_and_case_insensitive(tmp_path: Path) -> None:
    if not _FIXTURE.exists():
        pytest.skip("fixture not available")
    shutil.copy(_FIXTURE, tmp_path / "A.SPA")  # uppercase extension
    shutil.copy(_FIXTURE, tmp_path / "b.spa")  # lowercase extension
    sub = tmp_path / "batch2"
    sub.mkdir()
    shutil.copy(_FIXTURE, sub / "C.SPA")  # nested subfolder
    (tmp_path / "notes.txt").write_text("ignore me")

    found = _service().scan_folder(tmp_path)
    names = sorted(p.relative_to(tmp_path).as_posix() for p in found)

    assert names == ["A.SPA", "b.spa", "batch2/C.SPA"]


def test_scan_folder_includes_jcamp_extensions(tmp_path: Path) -> None:
    (tmp_path / "spectrum.jdx").write_text("##TITLE=x\n##END=\n")
    (tmp_path / "spectrum.dx").write_text("##TITLE=y\n##END=\n")
    (tmp_path / "ignore.csv").write_text("a,b\n1,2\n")

    found = {p.suffix.lower() for p in _service().scan_folder(tmp_path)}

    assert ".jdx" in found
    assert ".dx" in found
    assert ".csv" not in found


def test_scan_folder_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        _service().scan_folder(tmp_path / "does-not-exist")
