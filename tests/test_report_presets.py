"""Tests for named report presets shared across export surfaces."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.report_presets import ReportPresetManager
from reporting.pdf_generator import ReportOptions
from storage.settings import Settings
from ui.dialogs.batch_pdf_export_dialog import BatchPDFExportDialog
from ui.dialogs.batch_project_pdf_export_dialog import BatchProjectPDFExportDialog
from ui.dialogs.export_dialog import ExportDialog


def _make_manager(tmp_path: Path) -> ReportPresetManager:
    """Create a preset manager backed by a temporary settings file."""
    settings = Settings(tmp_path / "settings.json")
    return ReportPresetManager(settings)


def test_report_preset_manager_saves_and_loads_named_presets(tmp_path):
    """Named presets should roundtrip through settings-backed storage."""
    manager = _make_manager(tmp_path)
    options = ReportOptions(
        include_metadata=False,
        include_peak_table=True,
        include_structures=False,
        dpi=220,
    )

    manager.save_preset("Lab standard", options)

    preset = manager.get_preset("Lab standard")
    assert preset is not None
    assert preset.name == "Lab standard"
    assert preset.options == options
    assert [item.name for item in manager.list_presets()] == ["Lab standard"]


def test_report_preset_manager_deletes_presets(tmp_path):
    """Deleting a preset should remove it and clear last-used state when needed."""
    manager = _make_manager(tmp_path)
    manager.save_preset("Minimal", ReportOptions(include_metadata=False))
    manager.set_last_used_preset_name("Minimal")

    manager.delete_preset("Minimal")

    assert manager.get_preset("Minimal") is None
    assert manager.get_last_used_preset_name() is None


def test_export_dialog_defaults_when_no_presets_exist(qtbot, tmp_path):
    """No presets should still keep the default report behavior intact."""
    manager = _make_manager(tmp_path)
    dialog = ExportDialog(preset_manager=manager)
    qtbot.addWidget(dialog)

    assert dialog.selected_format == "pdf"
    assert dialog.report_options == ReportOptions()
    assert dialog._preset_combo.count() == 1
    assert dialog._preset_combo.currentText() == "Current defaults"


def test_selecting_preset_updates_dialog_checkbox_state(qtbot, tmp_path):
    """Picking a preset should immediately update the visible report checkboxes."""
    manager = _make_manager(tmp_path)
    manager.save_preset(
        "Minimal report",
        ReportOptions(
            include_metadata=False,
            include_peak_table=False,
            include_structures=False,
        ),
    )
    dialog = ExportDialog(preset_manager=manager)
    qtbot.addWidget(dialog)

    dialog._preset_combo.setCurrentIndex(dialog._preset_combo.findData("Minimal report"))

    assert dialog._include_metadata_checkbox.isChecked() is False
    assert dialog._include_peak_table_checkbox.isChecked() is False
    assert dialog._include_structures_checkbox.isChecked() is False
    assert dialog.report_options == ReportOptions(
        include_metadata=False,
        include_peak_table=False,
        include_structures=False,
    )


def test_export_dialog_can_save_current_checkbox_state_as_preset(qtbot, tmp_path, monkeypatch):
    """Saving from the dialog should persist the current option combination as a preset."""
    from PySide6.QtWidgets import QInputDialog

    manager = _make_manager(tmp_path)
    dialog = ExportDialog(preset_manager=manager)
    qtbot.addWidget(dialog)
    dialog._include_metadata_checkbox.setChecked(False)
    dialog._include_peak_table_checkbox.setChecked(True)
    dialog._include_structures_checkbox.setChecked(False)

    monkeypatch.setattr(
        QInputDialog,
        "getText",
        lambda *args, **kwargs: ("Peaks only", True),
    )

    dialog._save_preset_button.click()

    preset = manager.get_preset("Peaks only")
    assert preset is not None
    assert preset.options == ReportOptions(
        include_metadata=False,
        include_peak_table=True,
        include_structures=False,
    )


def test_all_pdf_export_dialogs_share_the_same_preset_source(qtbot, tmp_path):
    """Single and batch export dialogs should see the same saved presets and last-used choice."""
    manager = _make_manager(tmp_path)
    options = ReportOptions(
        include_metadata=False,
        include_peak_table=True,
        include_structures=False,
    )
    manager.save_preset("Lab standard", options)
    manager.set_last_used_preset_name("Lab standard")

    export_dialog = ExportDialog(preset_manager=manager)
    batch_spa_dialog = BatchPDFExportDialog(preset_manager=manager)
    batch_project_dialog = BatchProjectPDFExportDialog(preset_manager=manager)
    qtbot.addWidget(export_dialog)
    qtbot.addWidget(batch_spa_dialog)
    qtbot.addWidget(batch_project_dialog)

    for dialog in (export_dialog, batch_spa_dialog, batch_project_dialog):
        assert dialog._preset_combo.findData("Lab standard") >= 0
        assert dialog._preset_combo.currentText() == "Lab standard"
        assert dialog._include_metadata_checkbox.isChecked() is False
        assert dialog._include_peak_table_checkbox.isChecked() is True
        assert dialog._include_structures_checkbox.isChecked() is False
