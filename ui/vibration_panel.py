"""
VibrationPanel — Panel předvoleb vibrací.

Zodpovědnost:
- Zobrazení seznamu vibračních předvoleb dle kategorie
- Přiřazení předvolby k vybranému peaku kliknutím
- Filtrování předvoleb dle rozsahu wavenumberů
"""
from __future__ import annotations

from PySide6.QtWidgets import QWidget, QVBoxLayout, QListWidget
from PySide6.QtCore import Signal

from core.vibration_presets import VibrationPreset


class VibrationPanel(QWidget):
    """Panel displaying vibration presets for assignment to peaks."""

    preset_selected = Signal(object)  # emits VibrationPreset

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._presets: list[VibrationPreset] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._list = QListWidget()
        layout.addWidget(self._list)

    def set_presets(self, presets: list[VibrationPreset]) -> None:
        """Populate the panel with vibration presets.

        Args:
            presets: List of presets to display.
        """
        self._presets = presets
        self._list.clear()
        for preset in presets:
            self._list.addItem(
                f"{preset.name}  "
                f"({preset.typical_range_min:.0f}–{preset.typical_range_max:.0f} cm⁻¹)"
            )
