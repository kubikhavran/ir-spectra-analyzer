"""Tests for batch reference import helpers and dialog."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.reference_import import (  # noqa: E402
    BatchImportResult,
    BatchImportStatus,
    BatchImportSummary,
    ReferenceImportService,
)
from core.peak import Peak  # noqa: E402
from core.spectrum import SpectralUnit, Spectrum  # noqa: E402
from storage.database import Database  # noqa: E402
from ui.dialogs.batch_import_dialog import BatchImportDialog  # noqa: E402
from ui.workers.reference_import_worker import ReferenceBatchImportWorker  # noqa: E402


@pytest.fixture
def db():
    """Provide an in-memory Database instance."""
    database = Database(":memory:")
    database.initialize()
    yield database
    database.close()


@pytest.fixture
def file_db(tmp_path):
    """Provide a file-backed Database instance for background-worker tests."""
    database = Database(tmp_path / "batch-import.db")
    database.initialize()
    yield database
    database.close()


def _make_spectrum(path: Path, title: str | None = None) -> Spectrum:
    """Create a synthetic Spectrum for import tests."""
    wavenumbers = np.linspace(400.0, 4000.0, 32)
    intensities = np.linspace(0.1, 0.9, 32)
    return Spectrum(
        wavenumbers=wavenumbers,
        intensities=intensities,
        title=title or path.stem,
        source_path=path,
        y_unit=SpectralUnit.ABSORBANCE,
    )


def test_batch_import_dialog_opens_empty_state(qtbot, db):
    """The dialog should open with no selected folder and no results."""
    dlg = BatchImportDialog(db)
    qtbot.addWidget(dlg)

    assert dlg.windowTitle() == "Batch Import References"
    assert dlg._folder_edit.text() == ""
    assert dlg._results_table.rowCount() == 0
    assert not dlg._import_button.isEnabled()


def test_batch_import_dialog_no_folder_selected_is_safe(qtbot, db, monkeypatch):
    """Clicking import without a folder should not invoke the batch import service."""
    dlg = BatchImportDialog(db)
    qtbot.addWidget(dlg)

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("batch_import_folder should not be called without a folder")

    monkeypatch.setattr(dlg._service, "batch_import_folder", _fail_if_called)

    dlg._on_import()

    assert dlg._summary_label.text() == "No folder selected."
    assert dlg._results_table.rowCount() == 0


def test_reference_import_service_imports_folder_and_reports_counts(tmp_path, db, monkeypatch):
    """Batch import should read files, insert references, and report failures clearly."""
    folder = tmp_path / "batch"
    folder.mkdir()
    ok_a = folder / "alpha.spa"
    ok_b = folder / "beta.spa"
    bad = folder / "broken.spa"
    for path in (ok_a, ok_b, bad):
        path.write_bytes(b"spa")

    service = ReferenceImportService(db)
    read_calls: list[str] = []

    def _fake_read(path: Path) -> Spectrum:
        read_calls.append(path.name)
        if path.name == "broken.spa":
            raise ValueError("Corrupted SPA")
        return _make_spectrum(path, title=f"Imported {path.stem}")

    monkeypatch.setattr(service, "_read_spectrum", _fake_read)

    summary = service.batch_import_folder(folder, skip_duplicates_by_filename=False)
    refs = db.get_reference_spectra()

    assert read_calls == ["alpha.spa", "beta.spa", "broken.spa"]
    assert summary.total_found == 3
    assert summary.imported == 2
    assert summary.skipped == 0
    assert summary.failed == 1
    assert {ref["name"] for ref in refs} == {"Imported alpha", "Imported beta"}
    assert {ref["source"] for ref in refs} == {str(ok_a), str(ok_b)}
    assert any(
        result.path.name == "broken.spa"
        and result.status == BatchImportStatus.FAILED
        and result.reason == "Corrupted SPA"
        for result in summary.results
    )


def test_reference_import_service_skips_duplicates_when_enabled(tmp_path, db, monkeypatch):
    """Duplicate filename detection should skip already imported references before reading."""
    folder = tmp_path / "batch"
    folder.mkdir()
    existing = folder / "existing.spa"
    new_file = folder / "new_file.spa"
    existing.write_bytes(b"spa")
    new_file.write_bytes(b"spa")

    db.add_reference_spectrum(
        name="existing",
        wavenumbers=np.linspace(400.0, 4000.0, 8),
        intensities=np.linspace(0.0, 1.0, 8),
        source=str(existing),
        y_unit="Absorbance",
    )

    service = ReferenceImportService(db)
    read_calls: list[str] = []

    def _fake_read(path: Path) -> Spectrum:
        read_calls.append(path.name)
        return _make_spectrum(path)

    monkeypatch.setattr(service, "_read_spectrum", _fake_read)

    summary = service.batch_import_folder(folder, skip_duplicates_by_filename=True)

    assert read_calls == ["new_file.spa"]
    assert summary.total_found == 2
    assert summary.imported == 1
    assert summary.skipped == 1
    assert summary.failed == 0
    assert any(
        result.path.name == "existing.spa"
        and result.status == BatchImportStatus.SKIPPED
        and result.reason == "source path already imported"
        for result in summary.results
    )


def test_reference_import_service_detects_peaks_when_enabled(tmp_path, db, monkeypatch):
    """Batch import should attach detected peaks to in-memory results when requested."""
    folder = tmp_path / "batch"
    folder.mkdir()
    spa_file = folder / "sample.spa"
    spa_file.write_bytes(b"spa")

    service = ReferenceImportService(db)
    monkeypatch.setattr(service, "_read_spectrum", lambda path: _make_spectrum(path))
    detected = (Peak(position=1715.0, intensity=0.7), Peak(position=2918.0, intensity=0.4))
    monkeypatch.setattr("app.reference_import.detect_peaks_for_spectrum", lambda spectrum: detected)

    summary = service.batch_import_folder(folder, detect_peaks=True)

    assert summary.imported == 1
    assert summary.results[0].detected_peaks == detected


def test_batch_import_dialog_renders_summary_results(qtbot, db, monkeypatch, tmp_path):
    """The dialog should render batch summary counts and per-file results."""
    dlg = BatchImportDialog(db)
    qtbot.addWidget(dlg)

    summary = BatchImportSummary(
        folder=tmp_path,
        results=(
            BatchImportResult(
                path=tmp_path / "ok.spa",
                status=BatchImportStatus.IMPORTED,
                reference_name="ok",
            ),
            BatchImportResult(
                path=tmp_path / "skip.spa",
                status=BatchImportStatus.SKIPPED,
                reference_name="skip",
                reason="reference name already exists",
            ),
            BatchImportResult(
                path=tmp_path / "bad.spa",
                status=BatchImportStatus.FAILED,
                reference_name="bad",
                reason="Parse failure",
            ),
        ),
    )

    monkeypatch.setattr(dlg._service, "batch_import_folder", lambda *args, **kwargs: summary)
    dlg._folder_edit.setText(str(tmp_path))

    dlg._on_import()

    assert dlg._results_table.rowCount() == 3
    assert dlg._results_table.item(0, 0).text() == "ok.spa"
    assert dlg._results_table.item(1, 1).text() == "skipped"
    assert dlg._results_table.item(2, 3).text() == "Parse failure"
    assert "Total .spa files found: 3" in dlg._summary_label.text()
    assert "Imported: 1 | Skipped: 1 | Failed: 1" in dlg._summary_label.text()


def test_batch_import_dialog_passes_detect_peaks_option(qtbot, db, monkeypatch, tmp_path):
    """The dialog should pass the auto-detect checkbox state into the batch service."""
    dlg = BatchImportDialog(db)
    qtbot.addWidget(dlg)
    dlg._folder_edit.setText(str(tmp_path))
    dlg._detect_peaks_checkbox.setChecked(True)

    captured: dict[str, object] = {}

    def _fake_batch_import(folder, *, skip_duplicates_by_filename, detect_peaks):
        captured["folder"] = folder
        captured["skip_duplicates_by_filename"] = skip_duplicates_by_filename
        captured["detect_peaks"] = detect_peaks
        return BatchImportSummary(folder=folder, results=())

    monkeypatch.setattr(dlg._service, "batch_import_folder", _fake_batch_import)

    dlg._on_import()

    assert captured["folder"] == tmp_path
    assert captured["skip_duplicates_by_filename"] is True
    assert captured["detect_peaks"] is True


def test_reference_batch_import_worker_imports_real_fixture_folder(file_db):
    """The batch-import worker should populate a file-backed DB from real SPA fixtures."""
    folder = Path(__file__).resolve().parent / "fixtures" / "reference library_1"
    worker = ReferenceBatchImportWorker(
        db_path=file_db.db_path,
        folder=folder,
        skip_duplicates_by_filename=True,
        detect_peaks=False,
    )

    completed = []
    failures = []
    worker.completed.connect(completed.append)
    worker.failed.connect(failures.append)

    worker.run()

    assert failures == []
    assert len(completed) == 1
    assert completed[0].imported == len(list(folder.glob("*.SPA")))
    assert len(file_db.get_reference_spectra()) == completed[0].imported


def test_batch_import_dialog_runs_background_import_for_file_db(qtbot, file_db):
    """File-backed DB mode should import on a worker thread and update the dialog when done."""
    folder = Path(__file__).resolve().parent / "fixtures" / "reference library_1"
    dlg = BatchImportDialog(file_db)
    qtbot.addWidget(dlg)

    dlg._set_folder(folder)
    dlg._on_import()

    expected_rows = len(list(folder.glob("*.SPA")))
    qtbot.waitUntil(lambda: dlg._results_table.rowCount() == expected_rows, timeout=10000)
    if dlg._import_thread is not None:
        qtbot.waitUntil(lambda: not dlg._import_thread.isRunning(), timeout=10000)

    assert dlg._results_table.rowCount() == expected_rows
    assert "Imported:" in dlg._summary_label.text()
