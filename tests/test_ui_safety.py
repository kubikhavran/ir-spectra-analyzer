"""Regression tests for project lifecycle and UI state safety."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QDialog, QMessageBox

from core.metadata import SpectrumMetadata
from core.peak import Peak
from core.project import Project
from core.spectrum import Spectrum
from ui.dialogs.background_task_dialog import BackgroundTaskDialogMixin
from ui.main_window import MainWindow
from ui.peak_table_widget import PeakTableWidget


def _spectrum() -> Spectrum:
    return Spectrum(
        wavenumbers=np.linspace(400.0, 4000.0, 64),
        intensities=np.linspace(0.1, 0.8, 64),
        title="Safety",
    )


def _window(qtbot) -> MainWindow:
    db = MagicMock()
    db.get_vibration_presets.return_value = []
    settings = MagicMock()
    settings.get.return_value = None
    window = MainWindow(db=db, settings=settings)
    qtbot.addWidget(window)
    return window


def test_metadata_marks_project_dirty_and_successful_save_cleans_it(qtbot, tmp_path, monkeypatch):
    window = _window(qtbot)
    window._apply_project_to_ui(Project(name="sample", spectrum=_spectrum()))
    assert not window._has_unsaved_changes()

    window._on_metadata_changed(SpectrumMetadata(title="Edited", file_name="sample"))
    assert window._has_unsaved_changes()
    assert window.windowTitle().startswith("*")

    destination = tmp_path / "sample.irproj"
    monkeypatch.setattr(
        "ui.main_window.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: (str(destination), ""),
    )
    monkeypatch.setattr(window, "_refresh_saved_project_names", lambda: None)
    monkeypatch.setattr(window, "_register_saved_project_as_reference", lambda _path: None)
    monkeypatch.setattr(
        "ui.main_window.QMessageBox.critical",
        lambda _parent, _title, message: pytest.fail(message),
    )

    assert window._on_save_project()
    assert destination.exists()
    assert not window._has_unsaved_changes()
    assert not window.windowTitle().startswith("*")


def test_cancelled_unsaved_prompt_blocks_replacement(qtbot, monkeypatch):
    window = _window(qtbot)
    window._apply_project_to_ui(Project(name="sample", spectrum=_spectrum()))
    window._mark_non_undo_dirty()
    monkeypatch.setattr(
        "ui.main_window.QMessageBox.warning",
        lambda *args, **kwargs: QMessageBox.StandardButton.Cancel,
    )

    assert not window._confirm_project_replacement()


def test_stale_background_match_result_is_ignored(qtbot, monkeypatch):
    window = _window(qtbot)
    window._apply_project_to_ui(Project(name="sample", spectrum=_spectrum()))
    context = window._current_match_context()
    applied: list[object] = []
    monkeypatch.setattr(window, "_apply_match_spectrum_outcome", applied.append)

    window._project_revision += 1
    window._on_match_spectrum_completed(SimpleNamespace(), context)

    assert applied == []
    assert "ignored" in window.statusBar().currentMessage().lower()


def test_clear_match_results_also_clears_reference_overlay(qtbot):
    window = _window(qtbot)
    window._apply_project_to_ui(Project(name="sample", spectrum=_spectrum()))
    window._spectrum_widget.set_overlay_spectra([_spectrum()])

    window._clear_match_results()

    assert window._spectrum_widget._overlay_spectra_cache == []


def test_delete_shortcut_does_not_delete_peak_while_editing_metadata(qtbot):
    window = _window(qtbot)
    peak = Peak(position=1000.0, intensity=0.5)
    project = Project(name="sample", spectrum=_spectrum(), peaks=[peak])
    window._apply_project_to_ui(project)
    window._peak_table.select_peak(peak)
    window.show()
    window._metadata_panel._title_edit.setFocus()
    qtbot.wait(1)

    window._on_delete_peak()

    assert project.peaks == [peak]


def test_peak_table_does_not_offer_non_persistent_inline_edits(qtbot):
    table = PeakTableWidget()
    qtbot.addWidget(table)
    table.set_peaks([Peak(position=1000.0, intensity=0.5)])

    assert table._table.editTriggers() == table._table.EditTrigger.NoEditTriggers


def test_switching_project_drops_selected_peak_from_previous_project(qtbot):
    window = _window(qtbot)
    old_peak = Peak(position=1000.0, intensity=0.5)
    window._apply_project_to_ui(Project(name="old", spectrum=_spectrum(), peaks=[old_peak]))
    window._peak_table.select_peak(old_peak)

    window._apply_project_to_ui(Project(name="new", spectrum=_spectrum(), peaks=[]))

    assert window._spectrum_widget._selected_peak is None


def test_dragged_peak_label_marks_project_dirty(qtbot):
    window = _window(qtbot)
    peak = Peak(position=1000.0, intensity=0.5)
    window._apply_project_to_ui(Project(name="sample", spectrum=_spectrum(), peaks=[peak]))

    window._spectrum_widget.peak_label_moved.emit(peak)

    assert window._has_unsaved_changes()
    assert window.windowTitle().startswith("*")


def test_completed_peak_label_drag_emits_model_change(qtbot):
    from PySide6.QtCore import QPointF, Qt

    from ui.spectrum_widget import SpectrumWidget, _DraggableLabel

    class DragEvent:
        @staticmethod
        def button():
            return Qt.MouseButton.LeftButton

        @staticmethod
        def pos():
            return QPointF(3.0, 2.0)

        @staticmethod
        def lastPos():  # noqa: N802 - mirrors the PyQtGraph event API
            return QPointF(1.0, 1.0)

        @staticmethod
        def isFinish():  # noqa: N802 - mirrors the PyQtGraph event API
            return True

        @staticmethod
        def accept():
            return None

    widget = SpectrumWidget()
    qtbot.addWidget(widget)
    peak = Peak(position=1000.0, intensity=0.5)
    widget.set_spectrum(_spectrum())
    widget.set_peaks([peak])
    changed: list[Peak] = []
    widget.peak_label_moved.connect(changed.append)
    label = next(item for item in widget._peak_items if isinstance(item, _DraggableLabel))

    label.mouseDragEvent(DragEvent())

    assert changed == [peak]
    assert peak.manual_placement


def _png_bytes() -> bytes:
    image = QImage(4, 4, QImage.Format.Format_ARGB32)
    image.fill(0xFF336699)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")
    return bytes(data)


def test_molecule_widget_displays_legacy_structure_image(qtbot):
    from ui.molecule_widget import MoleculeWidget

    widget = MoleculeWidget()
    qtbot.addWidget(widget)
    widget.set_structure("", image_bytes=_png_bytes())

    assert not widget.pixmap().isNull()


def test_structure_command_clears_stale_image_and_restores_it_on_undo():
    from core.commands import SetProjectSMILESCommand

    legacy = _png_bytes()
    project = Project(name="sample", spectrum=_spectrum(), structure_image=legacy)
    command = SetProjectSMILESCommand(project, "CCO", "mol")

    command.redo()
    assert project.structure_image == b""
    command.undo()
    assert project.structure_image == legacy


def test_background_task_dialog_cannot_close_until_thread_stops(qtbot):
    class GuardedDialog(BackgroundTaskDialogMixin, QDialog):
        _background_thread_attribute = "_thread"

    dialog = GuardedDialog()
    qtbot.addWidget(dialog)
    dialog._thread = SimpleNamespace(isRunning=lambda: False)
    dialog._show_background_task_running_message = MagicMock()

    dialog.accept()

    assert dialog.result() == QDialog.DialogCode.Rejected
    dialog._show_background_task_running_message.assert_called_once_with()

    dialog._thread = None
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
