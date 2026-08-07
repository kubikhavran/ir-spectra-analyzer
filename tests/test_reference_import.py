"""Tests for reference-library folder scanning."""

from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
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


# ── Duplicate-name handling: all distinct files must import ────────────────────


def _make_db():
    from storage.database import Database

    db = Database(":memory:")
    db.initialize()
    return db


def test_batch_import_keeps_duplicate_named_files(tmp_path: Path) -> None:
    if not _FIXTURE.exists():
        pytest.skip("fixture not available")
    import shutil

    shutil.copy(_FIXTURE, tmp_path / "A.SPA")
    (tmp_path / "sub1").mkdir()
    shutil.copy(_FIXTURE, tmp_path / "sub1" / "A.SPA")  # same stem, different file
    (tmp_path / "sub2").mkdir()
    shutil.copy(_FIXTURE, tmp_path / "sub2" / "A.SPA")

    db = _make_db()
    summary = ReferenceImportService(db).batch_import_folder(tmp_path, prefer_filename=True)

    imported = [r for r in summary.results if r.status.name == "IMPORTED"]
    assert len(imported) == 3  # none dropped for sharing a name
    names = sorted(r["name"] for r in db.get_reference_metadata())
    assert names == ["A", "A (2)", "A (3)"]


def test_batch_import_resync_skips_by_source_path(tmp_path: Path) -> None:
    if not _FIXTURE.exists():
        pytest.skip("fixture not available")
    import shutil

    shutil.copy(_FIXTURE, tmp_path / "A.SPA")
    (tmp_path / "sub").mkdir()
    shutil.copy(_FIXTURE, tmp_path / "sub" / "A.SPA")

    db = _make_db()
    svc = ReferenceImportService(db)
    svc.batch_import_folder(tmp_path, prefer_filename=True)
    second = svc.batch_import_folder(tmp_path, prefer_filename=True)

    assert all(r.status.name == "SKIPPED" for r in second.results)
    assert len(db.get_reference_metadata()) == 2  # not re-imported


def test_clear_reference_spectra_removes_all(tmp_path: Path) -> None:
    if not _FIXTURE.exists():
        pytest.skip("fixture not available")
    import shutil

    shutil.copy(_FIXTURE, tmp_path / "A.SPA")
    shutil.copy(_FIXTURE, tmp_path / "B.SPA")
    db = _make_db()
    ReferenceImportService(db).batch_import_folder(tmp_path, prefer_filename=True)
    assert len(db.get_reference_metadata()) == 2

    removed = db.clear_reference_spectra()

    assert removed == 2
    assert db.get_reference_metadata() == []


def test_failed_batch_item_is_rolled_back_before_later_commit(tmp_path: Path, monkeypatch) -> None:
    import app.reference_import as reference_import_module

    bad = tmp_path / "bad.spa"
    good = tmp_path / "good.spa"
    bad.write_bytes(b"bad")
    good.write_bytes(b"good")

    def make_spectrum(path: Path):
        first = -1.0 if path == bad else 1.0
        return SimpleNamespace(
            wavenumbers=np.asarray([first, 2.0]),
            intensities=np.asarray([0.1, 0.2]),
            comments="",
            title=path.stem,
            y_unit=SimpleNamespace(value="Absorbance"),
        )

    def compute_feature(wavenumbers, intensities, *, y_unit=None):
        del intensities, y_unit
        if float(wavenumbers[0]) < 0:
            raise ValueError("simulated feature failure")
        return np.asarray([1.0, 2.0], dtype=np.float32)

    db = _make_db()
    service = ReferenceImportService(db)
    monkeypatch.setattr(service, "scan_folder", lambda folder: [bad, good])
    monkeypatch.setattr(service, "_read_spectrum", make_spectrum)
    monkeypatch.setattr(reference_import_module, "compute_search_vector", compute_feature)

    summary = service.batch_import_folder(tmp_path, prefer_filename=True)

    assert [result.status.name for result in summary.results] == ["FAILED", "IMPORTED"]
    assert [row["name"] for row in db.get_reference_metadata()] == ["good"]


def test_batch_import_reports_file_removed_after_scan(tmp_path: Path, monkeypatch) -> None:
    vanished = tmp_path / "vanished.spa"
    vanished.write_bytes(b"temporary")

    db = _make_db()
    service = ReferenceImportService(db)
    monkeypatch.setattr(service, "scan_folder", lambda folder: [vanished])
    vanished.unlink()

    summary = service.batch_import_folder(tmp_path)

    assert summary.failed == 1
    assert summary.results[0].path == vanished
    assert summary.results[0].status.name == "FAILED"
    assert db.get_reference_metadata() == []


def test_reference_peak_detection_uses_shared_prominence_and_polarity(monkeypatch) -> None:
    import processing.peak_detection as peak_detection
    from app.reference_import import detect_peaks_for_spectrum

    captured: dict[str, object] = {}
    spectrum = SimpleNamespace(
        wavenumbers=np.asarray([1000.0, 900.0]),
        intensities=np.asarray([90.0, 50.0]),
        is_dip_spectrum=True,
    )

    monkeypatch.setattr(peak_detection, "default_prominence", lambda value: 1.25)

    def fake_detect(wavenumbers, intensities, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(peak_detection, "detect_peaks", fake_detect)

    assert detect_peaks_for_spectrum(spectrum) == ()
    assert captured == {"prominence": 1.25, "invert": True}
