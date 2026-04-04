"""Reusable report options widget with named preset support."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.report_presets import ReportPresetManager
from reporting.pdf_generator import ReportOptions


class ReportOptionsWidget(QWidget):
    """Compact shared UI for report options and reusable presets."""

    options_changed = Signal()

    _DEFAULT_ID = "__defaults__"
    _CUSTOM_ID = "__custom__"

    def __init__(self, preset_manager: ReportPresetManager | None = None, parent=None) -> None:
        super().__init__(parent)
        self._preset_manager = preset_manager or ReportPresetManager()
        self._suppress_state_updates = False
        self._custom_item_visible = False
        self._build_ui()
        self._load_initial_state()

    def _build_ui(self) -> None:
        """Construct the compact preset and checkbox controls."""
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        preset_layout = QHBoxLayout()
        self._preset_combo = QComboBox()
        self._preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        self._save_preset_button = QPushButton("Save Preset...")
        self._save_preset_button.clicked.connect(self._on_save_preset)
        self._delete_preset_button = QPushButton("Delete Preset")
        self._delete_preset_button.clicked.connect(self._on_delete_preset)
        preset_layout.addWidget(QLabel("Preset:"))
        preset_layout.addWidget(self._preset_combo, stretch=1)
        preset_layout.addWidget(self._save_preset_button)
        preset_layout.addWidget(self._delete_preset_button)
        root_layout.addLayout(preset_layout)

        checkbox_layout = QHBoxLayout()
        self._include_metadata_checkbox = QCheckBox("Include metadata")
        self._include_metadata_checkbox.setChecked(True)
        self._include_peak_table_checkbox = QCheckBox("Include peak table")
        self._include_peak_table_checkbox.setChecked(True)
        self._include_structures_checkbox = QCheckBox("Include structures")
        self._include_structures_checkbox.setChecked(True)
        checkbox_layout.addWidget(self._include_metadata_checkbox)
        checkbox_layout.addWidget(self._include_peak_table_checkbox)
        checkbox_layout.addWidget(self._include_structures_checkbox)
        checkbox_layout.addStretch()
        root_layout.addLayout(checkbox_layout)

        for checkbox in (
            self._include_metadata_checkbox,
            self._include_peak_table_checkbox,
            self._include_structures_checkbox,
        ):
            checkbox.toggled.connect(self._on_options_toggled)

    def report_options(self) -> ReportOptions:
        """Return the current checkbox state as ReportOptions."""
        return ReportOptions(
            include_metadata=self._include_metadata_checkbox.isChecked(),
            include_peak_table=self._include_peak_table_checkbox.isChecked(),
            include_structures=self._include_structures_checkbox.isChecked(),
        )

    def current_preset_name(self) -> str | None:
        """Return the selected named preset, or None for defaults/custom."""
        data = self._preset_combo.currentData()
        if data in {self._DEFAULT_ID, self._CUSTOM_ID, None}:
            return None
        return str(data)

    def remember_current_preset(self) -> None:
        """Persist the currently selected named preset as last used."""
        self._preset_manager.set_last_used_preset_name(self.current_preset_name())

    def set_option_controls_enabled(self, enabled: bool) -> None:
        """Enable or disable the preset and checkbox controls."""
        self._preset_combo.setEnabled(enabled)
        self._save_preset_button.setEnabled(enabled)
        self._delete_preset_button.setEnabled(enabled and self.current_preset_name() is not None)
        self._include_metadata_checkbox.setEnabled(enabled)
        self._include_peak_table_checkbox.setEnabled(enabled)
        self._include_structures_checkbox.setEnabled(enabled)

    def _load_initial_state(self) -> None:
        """Load presets and select the last-used named preset when available."""
        self._rebuild_preset_combo()
        last_used = self._preset_manager.get_last_used_preset_name()
        if last_used and self._select_combo_data(last_used):
            self._apply_preset_by_name(last_used)
            return
        self._select_defaults()

    def _rebuild_preset_combo(
        self, *, keep_custom: bool = False, selected: str | None = None
    ) -> None:
        """Refresh the preset combo box from persisted presets."""
        presets = self._preset_manager.list_presets()
        self._custom_item_visible = keep_custom

        self._preset_combo.blockSignals(True)
        self._preset_combo.clear()
        self._preset_combo.addItem("Current defaults", self._DEFAULT_ID)
        if keep_custom:
            self._preset_combo.addItem("Custom", self._CUSTOM_ID)
        for preset in presets:
            self._preset_combo.addItem(preset.name, preset.name)

        if selected is not None and self._select_combo_data(selected):
            pass
        else:
            self._preset_combo.setCurrentIndex(0)
        self._preset_combo.blockSignals(False)
        self._delete_preset_button.setEnabled(self.current_preset_name() is not None)

    def _select_combo_data(self, value: str) -> bool:
        """Select a combo entry by its stored value."""
        index = self._preset_combo.findData(value)
        if index < 0:
            return False
        self._preset_combo.setCurrentIndex(index)
        return True

    def _select_defaults(self) -> None:
        """Select the built-in defaults and apply the default report options."""
        self._preset_combo.blockSignals(True)
        self._select_combo_data(self._DEFAULT_ID)
        self._preset_combo.blockSignals(False)
        self._apply_options(ReportOptions())
        self._delete_preset_button.setEnabled(False)

    def _apply_options(self, options: ReportOptions) -> None:
        """Apply ReportOptions into the checkbox state without entering custom mode."""
        self._suppress_state_updates = True
        try:
            self._include_metadata_checkbox.setChecked(options.include_metadata)
            self._include_peak_table_checkbox.setChecked(options.include_peak_table)
            self._include_structures_checkbox.setChecked(options.include_structures)
        finally:
            self._suppress_state_updates = False
        self.options_changed.emit()

    def _apply_preset_by_name(self, name: str) -> None:
        """Load one named preset into the checkbox state."""
        preset = self._preset_manager.get_preset(name)
        if preset is None:
            self._select_defaults()
            return
        self._apply_options(preset.options)
        self._delete_preset_button.setEnabled(True)

    def _on_preset_changed(self) -> None:
        """Handle user selection of defaults, custom state, or a named preset."""
        data = self._preset_combo.currentData()
        if data == self._DEFAULT_ID:
            self._apply_options(ReportOptions())
            self._delete_preset_button.setEnabled(False)
            return
        if data == self._CUSTOM_ID:
            self._delete_preset_button.setEnabled(False)
            return
        if data is None:
            self._delete_preset_button.setEnabled(False)
            return
        self._apply_preset_by_name(str(data))

    def _on_options_toggled(self) -> None:
        """Switch selection to Custom when checkboxes diverge from the selected preset/default."""
        if self._suppress_state_updates:
            return

        current_data = self._preset_combo.currentData()
        current_options = self.report_options()
        if current_data == self._DEFAULT_ID and current_options == ReportOptions():
            self.options_changed.emit()
            return

        preset_name = self.current_preset_name()
        if preset_name is not None:
            preset = self._preset_manager.get_preset(preset_name)
            if preset is not None and preset.options == current_options:
                self.options_changed.emit()
                return

        if not self._custom_item_visible:
            self._rebuild_preset_combo(keep_custom=True, selected=self._CUSTOM_ID)
        else:
            self._preset_combo.blockSignals(True)
            self._select_combo_data(self._CUSTOM_ID)
            self._preset_combo.blockSignals(False)
            self._delete_preset_button.setEnabled(False)
        self.options_changed.emit()

    def _on_save_preset(self) -> None:
        """Prompt for a preset name and persist the current report options."""
        current_name = self.current_preset_name() or ""
        name, ok = QInputDialog.getText(
            self, "Save Report Preset", "Preset name:", text=current_name
        )
        if not ok:
            return
        normalized = name.strip()
        if not normalized:
            return

        existing = self._preset_manager.get_preset(normalized)
        if existing is not None:
            answer = QMessageBox.question(
                self,
                "Overwrite Preset",
                f"Preset '{normalized}' already exists. Overwrite it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        self._preset_manager.save_preset(normalized, self.report_options())
        self._rebuild_preset_combo(selected=normalized)
        self._apply_preset_by_name(normalized)

    def _on_delete_preset(self) -> None:
        """Delete the currently selected named preset after confirmation."""
        name = self.current_preset_name()
        if name is None:
            return

        answer = QMessageBox.question(
            self,
            "Delete Report Preset",
            f"Delete preset '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        current_options = self.report_options()
        self._preset_manager.delete_preset(name)
        self._rebuild_preset_combo(keep_custom=True, selected=self._CUSTOM_ID)
        self._apply_options(current_options)
        self._delete_preset_button.setEnabled(False)
