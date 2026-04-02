"""
VibrationEditor — Dialog pro editaci vibrační předvolby.

Zodpovědnost:
- Vytvoření a editace VibrationPreset
- Validace rozsahu wavenumberů
- CRUD operace přes databázi
"""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLineEdit


class VibrationEditorDialog(QDialog):
    """Dialog for creating and editing vibration presets."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Vibration Preset")
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QFormLayout(self)
        self._name_edit = QLineEdit()
        self._range_min_edit = QLineEdit()
        self._range_max_edit = QLineEdit()
        layout.addRow("Name:", self._name_edit)
        layout.addRow("Min (cm⁻¹):", self._range_min_edit)
        layout.addRow("Max (cm⁻¹):", self._range_max_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)
