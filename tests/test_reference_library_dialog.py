"""Tests for ReferenceLibraryDialog."""

from __future__ import annotations

import os

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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


def test_dialog_opens_empty_db(qtbot, db):
    """Dialog should open without error when the database has no references."""
    dlg = ReferenceLibraryDialog(db)
    qtbot.addWidget(dlg)
    assert dlg.windowTitle() == "Reference Library"
    assert dlg._table.rowCount() == 0


def test_table_populates_with_one_reference(qtbot, db):
    """Table row count should equal the number of inserted reference spectra."""
    wn, inten = _make_arrays()
    db.add_reference_spectrum(
        name="Test Ref",
        wavenumbers=wn,
        intensities=inten,
        description="A test",
        source="test.spa",
        y_unit="Absorbance",
    )
    dlg = ReferenceLibraryDialog(db)
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
    db.add_reference_spectrum("Ref A", wn, inten)
    dlg = ReferenceLibraryDialog(db)
    qtbot.addWidget(dlg)

    dlg._table.selectRow(0)
    qtbot.waitUntil(lambda: dlg._delete_btn.isEnabled())

    assert dlg._delete_btn.isEnabled()
    assert dlg._rename_btn.isEnabled()


def test_preview_text_updates_on_row_selection(qtbot, db):
    """Selecting a row updates the preview summary on the right side."""
    wn, inten = _make_arrays()
    db.add_reference_spectrum(
        name="Preview Ref",
        wavenumbers=wn,
        intensities=inten,
        description="Preview description",
        source="preview.spa",
        y_unit="Transmittance",
    )
    dlg = ReferenceLibraryDialog(db)
    qtbot.addWidget(dlg)

    dlg._table.selectRow(0)
    qtbot.waitUntil(lambda: "Preview Ref" in dlg._preview_label.text())

    preview = dlg._preview_label.text()
    assert "Name: Preview Ref" in preview
    assert "Description: Preview description" in preview
    assert "Source: preview.spa" in preview
    assert "Y Unit: Transmittance" in preview
    assert f"Points: {len(wn)}" in preview


def test_rename_updates_database_and_table(qtbot, db, monkeypatch):
    """Rename action updates both the database row and the visible table text."""
    wn, inten = _make_arrays()
    db.add_reference_spectrum("Old Name", wn, inten)
    dlg = ReferenceLibraryDialog(db)
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
    db.add_reference_spectrum("Delete Me", wn, inten)
    dlg = ReferenceLibraryDialog(db)
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
