"""Tests for ReferenceLibraryDialog."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.reference_import import (  # noqa: E402
    BatchImportResult,
    BatchImportStatus,
    BatchImportSummary,
)
from app.reference_library_service import ReferenceSearchOutcome  # noqa: E402
from core.spectrum import Spectrum  # noqa: E402
from matching.search_engine import MatchResult  # noqa: E402
from storage.database import Database  # noqa: E402
from ui.dialogs.reference_library_dialog import ReferenceLibraryDialog  # noqa: E402


@pytest.fixture
def db():
    """Provide an in-memory Database instance."""
    d = Database(":memory:")
    d.initialize()
    yield d
    d.close()


def _make_arrays():
    wn = np.linspace(400.0, 4000.0, 100)
    inten = np.ones(100, dtype=np.float64)
    return wn, inten


class _FakeLibraryService:
    def __init__(self, db, folder: Path | None = None):
        self._db = db
        self._folder = folder

    def discover_project_library_folder(self):
        return self._folder

    def selected_library_folder(self):
        return self._folder

    def set_selected_library_folder(self, folder: Path):
        self._folder = folder
        return folder

    def get_library_references(self):
        if self._folder is None:
            return []
        return self._db.get_reference_spectra()

    def import_project_library(self):
        return None


def test_dialog_opens_empty_db(qtbot, db):
    """Dialog should open without error when the database has no references."""
    dlg = ReferenceLibraryDialog(db)
    qtbot.addWidget(dlg)
    assert dlg.windowTitle() == "Reference Library"
    assert dlg._table.rowCount() == 0
    assert dlg._library_label.text() == "Reference library folder: not selected"
    assert dlg._search_label.text() == "Similarity search: choose a reference folder first"


def test_table_populates_with_one_reference(qtbot, db):
    """Table row count should equal the number of inserted reference spectra."""
    wn, inten = _make_arrays()
    folder = Path("/tmp/reference-library")
    db.add_reference_spectrum(
        name="Test Ref",
        wavenumbers=wn,
        intensities=inten,
        description="A test",
        source=str(folder / "test.spa"),
        y_unit="Absorbance",
    )
    dlg = ReferenceLibraryDialog(db, library_service=_FakeLibraryService(db, folder))
    qtbot.addWidget(dlg)
    assert dlg._table.rowCount() == 1
    assert dlg._table.item(0, 0).text() == "Test Ref"


def test_delete_button_disabled_on_no_selection(qtbot, db):
    """Delete button must be disabled when no table row is selected."""
    dlg = ReferenceLibraryDialog(db)
    qtbot.addWidget(dlg)
    assert not dlg._delete_btn.isEnabled()


def test_rename_button_disabled_on_no_selection(qtbot, db):
    """Rename button must be disabled when no table row is selected."""
    dlg = ReferenceLibraryDialog(db)
    qtbot.addWidget(dlg)
    assert not dlg._rename_btn.isEnabled()


def test_buttons_enabled_after_row_selection(qtbot, db):
    """After selecting the first row, both Delete and Rename buttons become enabled."""
    wn, inten = _make_arrays()
    folder = Path("/tmp/reference-library")
    db.add_reference_spectrum("Ref A", wn, inten, source=str(folder / "Ref A.spa"))
    dlg = ReferenceLibraryDialog(db, library_service=_FakeLibraryService(db, folder))
    qtbot.addWidget(dlg)

    dlg._table.selectRow(0)
    qtbot.waitUntil(lambda: dlg._delete_btn.isEnabled())

    assert dlg._delete_btn.isEnabled()
    assert dlg._rename_btn.isEnabled()


def test_preview_text_updates_on_row_selection(qtbot, db):
    """Selecting a row updates the preview summary on the right side."""
    wn, inten = _make_arrays()
    folder = Path("/tmp/reference-library")
    db.add_reference_spectrum(
        name="Preview Ref",
        wavenumbers=wn,
        intensities=inten,
        description="Preview description",
        source=str(folder / "preview.spa"),
        y_unit="Transmittance",
    )
    dlg = ReferenceLibraryDialog(db, library_service=_FakeLibraryService(db, folder))
    qtbot.addWidget(dlg)

    dlg._table.selectRow(0)
    qtbot.waitUntil(lambda: "Preview Ref" in dlg._preview_label.text())

    preview = dlg._preview_label.text()
    assert "Name: Preview Ref" in preview
    assert "Quality: —" in preview
    assert "Description: Preview description" in preview
    assert f"Source: {folder / 'preview.spa'}" in preview
    assert "Y Unit: Transmittance" in preview
    assert f"Points: {len(wn)}" in preview

    x_data, y_data = dlg._preview_curve.getData()
    assert np.allclose(np.asarray(x_data), wn)
    assert np.allclose(np.asarray(y_data), inten)
    assert not dlg._preview_placeholder.isVisible()


def test_rename_updates_database_and_table(qtbot, db, monkeypatch):
    """Rename action updates both the database row and the visible table text."""
    wn, inten = _make_arrays()
    folder = Path("/tmp/reference-library")
    db.add_reference_spectrum("Old Name", wn, inten, source=str(folder / "Old Name.spa"))
    dlg = ReferenceLibraryDialog(db, library_service=_FakeLibraryService(db, folder))
    qtbot.addWidget(dlg)
    dlg._table.selectRow(0)
    qtbot.waitUntil(lambda: dlg._rename_btn.isEnabled())

    monkeypatch.setattr(
        "ui.dialogs.reference_library_dialog.QInputDialog.getText",
        lambda *args, **kwargs: ("Renamed Ref", True),
    )

    qtbot.mouseClick(dlg._rename_btn, Qt.MouseButton.LeftButton)

    assert dlg._table.rowCount() == 1
    assert dlg._table.item(0, 0).text() == "Renamed Ref"
    assert db.get_reference_spectra()[0]["name"] == "Renamed Ref"
    assert dlg._preview_label.text() == "Select a row to preview"


def test_delete_removes_selected_reference(qtbot, db, monkeypatch):
    """Delete action removes the selected reference after confirmation."""
    wn, inten = _make_arrays()
    folder = Path("/tmp/reference-library")
    db.add_reference_spectrum("Delete Me", wn, inten, source=str(folder / "Delete Me.spa"))
    dlg = ReferenceLibraryDialog(db, library_service=_FakeLibraryService(db, folder))
    qtbot.addWidget(dlg)
    dlg._table.selectRow(0)
    qtbot.waitUntil(lambda: dlg._delete_btn.isEnabled())

    monkeypatch.setattr(
        "ui.dialogs.reference_library_dialog.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    qtbot.mouseClick(dlg._delete_btn, Qt.MouseButton.LeftButton)

    assert dlg._table.rowCount() == 0
    assert db.get_reference_spectra() == []
    assert dlg._preview_label.text() == "Select a row to preview"


def test_project_library_button_disabled_when_no_bundled_folder(qtbot, db):
    """The sync/search buttons should disable cleanly when no reference folder exists."""

    class _MissingLibraryService:
        def discover_project_library_folder(self):
            return None

        def get_library_references(self):
            return []

        def import_project_library(self):
            raise AssertionError("Import should not be attempted without a discovered folder")

    dlg = ReferenceLibraryDialog(db, library_service=_MissingLibraryService())
    qtbot.addWidget(dlg)

    assert not dlg._sync_project_library_btn.isEnabled()
    assert dlg._library_label.text() == "Reference library folder: not selected"
    assert not dlg._find_similar_btn.isEnabled()


def test_similarity_search_button_disabled_without_current_spectrum(qtbot, db):
    """Library ranking should be unavailable when no current spectrum is provided."""
    dlg = ReferenceLibraryDialog(
        db,
        library_service=_FakeLibraryService(db, Path("/tmp/reference-library")),
    )
    qtbot.addWidget(dlg)

    assert not dlg._find_similar_btn.isEnabled()
    assert dlg._search_label.text() == "Similarity search: load a spectrum to rank the library"


def test_sync_project_library_imports_references_and_updates_status(qtbot, db):
    """Syncing the active reference folder should populate the table and status text."""
    wn, inten = _make_arrays()
    folder = Path("tests/fixtures/reference library_1")

    class _FakeLibraryService:
        def discover_project_library_folder(self):
            return folder

        def get_library_references(self):
            return db.get_reference_spectra()

        def import_project_library(self):
            db.add_reference_spectrum(
                name="FER58-SE",
                wavenumbers=wn,
                intensities=inten,
                source=str(folder / "FER58-SE.SPA"),
                y_unit="Transmittance",
            )
            return BatchImportSummary(
                folder=folder,
                results=(
                    BatchImportResult(
                        path=folder / "FER58-SE.SPA",
                        status=BatchImportStatus.IMPORTED,
                        reference_name="FER58-SE",
                    ),
                    BatchImportResult(
                        path=folder / "FER59-SE.SPA",
                        status=BatchImportStatus.SKIPPED,
                        reference_name="FER59-SE",
                        reason="source path already imported",
                    ),
                ),
            )

    dlg = ReferenceLibraryDialog(db, library_service=_FakeLibraryService())
    qtbot.addWidget(dlg)

    qtbot.mouseClick(dlg._sync_project_library_btn, Qt.MouseButton.LeftButton)

    assert dlg._table.rowCount() == 1
    assert dlg._table.item(0, 0).text() == "FER58-SE"
    assert "Last sync: Imported 1 | Skipped 1 | Failed 0" in dlg._library_label.text()


def test_import_file_button_imports_selected_files_and_refreshes_table(qtbot, db, monkeypatch):
    """Import File should import selected spectra and show a completion summary."""
    wn, inten = _make_arrays()
    imported_paths: list[Path] = []

    class _FakeImportService:
        def import_reference_file(self, path: Path, *, prefer_filename: bool = False):
            imported_paths.append(path)
            db.add_reference_spectrum(
                name=path.stem,
                wavenumbers=wn,
                intensities=inten,
                source=str(path),
                y_unit="Absorbance",
            )
            return SimpleNamespace(name=path.stem)

    folder = Path("/tmp/reference-library")
    monkeypatch.setattr(
        "ui.dialogs.reference_library_dialog.QFileDialog.getOpenFileNames",
        lambda *args, **kwargs: (
            ["/tmp/reference-library/FER58-SE.SPA", "/tmp/reference-library/FER59-SE.SPA"],
            "OMNIC SPA Files (*.spa *.SPA)",
        ),
    )

    summary_messages: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "ui.dialogs.reference_library_dialog.QMessageBox.information",
        lambda _parent, title, text: summary_messages.append((title, text)),
    )

    dlg = ReferenceLibraryDialog(
        db,
        import_service=_FakeImportService(),
        library_service=_FakeLibraryService(db, folder),
    )
    qtbot.addWidget(dlg)

    qtbot.mouseClick(dlg._import_file_btn, Qt.MouseButton.LeftButton)

    assert imported_paths == [
        Path("/tmp/reference-library/FER58-SE.SPA"),
        Path("/tmp/reference-library/FER59-SE.SPA"),
    ]
    assert dlg._table.rowCount() == 2
    assert dlg._table.item(0, 0).text() == "FER58-SE"
    assert dlg._table.item(1, 0).text() == "FER59-SE"
    assert summary_messages == [("Reference Import Summary", "Imported: 2\nFailed: 0")]


def test_choose_folder_sets_active_library_and_syncs(qtbot, db, monkeypatch):
    """Choosing a folder should activate it and refresh the library table."""
    wn, inten = _make_arrays()
    chosen_folder = Path("/tmp/reference-library")
    selected_folders: list[Path] = []

    class _FakeSelectableLibraryService(_FakeLibraryService):
        def set_selected_library_folder(self, folder: Path):
            selected_folders.append(folder)
            self._folder = folder
            return folder

        def import_project_library(self):
            db.add_reference_spectrum(
                name="FER58-SE",
                wavenumbers=wn,
                intensities=inten,
                source=str(chosen_folder / "FER58-SE.SPA"),
                y_unit="Transmittance",
            )
            return BatchImportSummary(
                folder=chosen_folder,
                results=(
                    BatchImportResult(
                        path=chosen_folder / "FER58-SE.SPA",
                        status=BatchImportStatus.IMPORTED,
                        reference_name="FER58-SE",
                    ),
                ),
            )

    monkeypatch.setattr(
        "ui.dialogs.reference_library_dialog.QFileDialog.getExistingDirectory",
        lambda *args, **kwargs: str(chosen_folder),
    )

    dlg = ReferenceLibraryDialog(
        db,
        library_service=_FakeSelectableLibraryService(db),
    )
    qtbot.addWidget(dlg)

    qtbot.mouseClick(dlg._choose_library_folder_btn, Qt.MouseButton.LeftButton)

    assert selected_folders == [chosen_folder]
    assert dlg._table.rowCount() == 1
    assert dlg._table.item(0, 0).text() == "FER58-SE"
    assert dlg._library_label.text().startswith("Reference library folder: /tmp/reference-library")


def test_import_file_skips_paths_outside_active_folder(qtbot, db, monkeypatch):
    """Import File should reject files outside the active reference folder."""
    folder = Path("/tmp/reference-library")
    imported_paths: list[Path] = []

    class _FakeImportService:
        def import_reference_file(self, path: Path, *, prefer_filename: bool = False):
            imported_paths.append(path)
            return SimpleNamespace(name=path.stem)

    monkeypatch.setattr(
        "ui.dialogs.reference_library_dialog.QFileDialog.getOpenFileNames",
        lambda *args, **kwargs: (
            ["/elsewhere/FER58-SE.SPA"],
            "OMNIC SPA Files (*.spa *.SPA)",
        ),
    )

    summary_messages: list[str] = []
    monkeypatch.setattr(
        "ui.dialogs.reference_library_dialog.QMessageBox.information",
        lambda _parent, title, text: summary_messages.append(text),
    )

    dlg = ReferenceLibraryDialog(
        db,
        import_service=_FakeImportService(),
        library_service=_FakeLibraryService(db, folder),
    )
    qtbot.addWidget(dlg)

    qtbot.mouseClick(dlg._import_file_btn, Qt.MouseButton.LeftButton)

    assert imported_paths == []
    assert summary_messages == [
        "Imported: 0\nFailed: 1\n\nFER58-SE.SPA: file is outside the active reference folder"
    ]


def test_find_similar_ranks_table_and_populates_similarity_column(qtbot, db):
    """Similarity search should sort references by score and show percent values."""
    wn, inten = _make_arrays()
    current = Spectrum(wavenumbers=wn, intensities=inten, title="Current")

    ref_ids = [
        db.add_reference_spectrum("Ref B", wn, inten, y_unit="Absorbance"),
        db.add_reference_spectrum("Ref A", wn, inten, y_unit="Absorbance"),
    ]

    class _FakeLibraryService:
        def discover_project_library_folder(self):
            return Path("tests/fixtures/reference library_1")

        def get_library_references(self):
            return db.get_reference_spectra()

        def import_project_library(self):
            return None

        def search_spectrum(self, spectrum, *, top_n, auto_import_project_library):
            assert spectrum is current
            assert top_n is None
            assert auto_import_project_library is True
            return ReferenceSearchOutcome(
                results=(
                    MatchResult(ref_id=ref_ids[1], name="Ref A", score=0.91),
                    MatchResult(ref_id=ref_ids[0], name="Ref B", score=0.42),
                ),
                references=tuple(db.get_reference_spectra()),
                imported_summary=None,
                library_folder=Path("tests/fixtures/reference library_1"),
            )

    dlg = ReferenceLibraryDialog(
        db,
        current_spectrum=current,
        library_service=_FakeLibraryService(),
    )
    qtbot.addWidget(dlg)

    qtbot.mouseClick(dlg._find_similar_btn, Qt.MouseButton.LeftButton)

    assert dlg._table.item(0, 0).text() == "Ref A"
    assert dlg._table.item(0, 1).text() == "91.0%"
    assert dlg._table.item(0, 2).text() == "Excellent"
    assert dlg._table.item(1, 0).text() == "Ref B"
    assert dlg._table.item(1, 1).text() == "42.0%"
    assert dlg._table.item(1, 2).text() == "Possible"
    assert dlg._clear_search_btn.isEnabled()
    assert dlg._search_label.text() == "Similarity search: ranked 2 library spectra"


def test_show_all_clears_similarity_ranking(qtbot, db):
    """Clearing similarity search should restore the default unranked table view."""
    wn, inten = _make_arrays()
    current = Spectrum(wavenumbers=wn, intensities=inten, title="Current")
    db.add_reference_spectrum("Ref B", wn, inten, y_unit="Absorbance")
    db.add_reference_spectrum("Ref A", wn, inten, y_unit="Absorbance")

    class _FakeLibraryService:
        def discover_project_library_folder(self):
            return Path("tests/fixtures/reference library_1")

        def get_library_references(self):
            return db.get_reference_spectra()

        def import_project_library(self):
            return None

        def search_spectrum(self, spectrum, *, top_n, auto_import_project_library):
            refs = tuple(db.get_reference_spectra())
            return ReferenceSearchOutcome(
                results=tuple(
                    MatchResult(ref_id=ref["id"], name=ref["name"], score=0.9 - i * 0.3)
                    for i, ref in enumerate(reversed(refs))
                ),
                references=refs,
                imported_summary=None,
                library_folder=Path("tests/fixtures/reference library_1"),
            )

    dlg = ReferenceLibraryDialog(
        db,
        current_spectrum=current,
        library_service=_FakeLibraryService(),
    )
    qtbot.addWidget(dlg)

    qtbot.mouseClick(dlg._find_similar_btn, Qt.MouseButton.LeftButton)
    assert dlg._table.item(0, 1).text() != "—"
    assert dlg._table.item(0, 2).text() != "—"

    qtbot.mouseClick(dlg._clear_search_btn, Qt.MouseButton.LeftButton)

    assert dlg._table.item(0, 0).text() == "Ref A"
    assert dlg._table.item(1, 0).text() == "Ref B"
    assert dlg._table.item(0, 1).text() == "—"
    assert dlg._table.item(0, 2).text() == "—"
    assert dlg._search_label.text() == "Similarity search: not run yet"
