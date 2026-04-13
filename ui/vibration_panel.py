"""
VibrationPanel — Panel předvoleb vibrací.

Zodpovědnost:
- Zobrazení seznamu vibračních předvoleb dle kategorie
- Přiřazení předvolby k vybranému peaku kliknutím
- Filtrování předvoleb dle rozsahu wavenumberů aktivního peaku
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.vibration_presets import VibrationPreset


class VibrationPanel(QWidget):
    """Panel displaying vibration presets for assignment to peaks.

    Workflow:
    1. MainWindow calls set_presets() after loading a spectrum.
    2. When the user selects a peak in PeakTableWidget, MainWindow calls
       highlight_for_peak() which filters/highlights relevant presets.
    3. Double-clicking a preset emits preset_selected(VibrationPreset).
    4. MainWindow handles preset_selected by assigning it to the active peak.
    """

    preset_selected = Signal(object)  # emits VibrationPreset on double-click
    preset_clicked_for_assign = Signal(object)  # emits VibrationPreset on single-click

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._presets: list[VibrationPreset] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Filter presets…")
        self._filter_edit.textChanged.connect(self._apply_filter)
        layout.addWidget(self._filter_edit)

        self._hint_label = QLabel("")
        self._hint_label.setStyleSheet("color: gray; font-size: 9pt;")
        layout.addWidget(self._hint_label)

        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._list)

    def set_presets(self, presets: list[VibrationPreset]) -> None:
        """Populate the panel with vibration presets.

        Args:
            presets: List of presets to display.
        """
        self._presets = presets
        self._rebuild_list(self._filter_edit.text())

    def highlight_for_peak(self, wavenumber: float) -> None:
        """Visually highlight presets whose range covers the given wavenumber.

        Called by MainWindow when the user selects a peak in the peak table.

        Args:
            wavenumber: Peak position in cm⁻¹.
        """
        self._hint_label.setText(f"Active peak: {wavenumber:.1f} cm⁻¹")
        for i in range(self._list.count()):
            item = self._list.item(i)
            preset = item.data(256)  # Qt.ItemDataRole.UserRole == 256
            if preset is not None and preset.covers_wavenumber(wavenumber):
                item.setBackground(QColor("#C8E6C9"))  # soft green, readable on any theme
                item.setForeground(QColor("#000000"))
            else:
                item.setBackground(QBrush())  # transparent — inherits theme default
                item.setForeground(QBrush())  # reset to theme default text color

    def _rebuild_list(self, filter_text: str = "") -> None:
        """Rebuild the list widget applying an optional text filter."""
        self._list.clear()
        needle = filter_text.strip().lower()
        for preset in self._presets:
            label = (
                f"{preset.name}  "
                f"({preset.typical_range_min:.0f}–{preset.typical_range_max:.0f} cm⁻¹)"
            )
            if needle and needle not in label.lower():
                continue
            item = QListWidgetItem(label)
            item.setData(256, preset)  # store preset in UserRole
            self._list.addItem(item)

    def _apply_filter(self, text: str) -> None:
        self._rebuild_list(text)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        preset = item.data(256)
        if preset is not None:
            self.preset_clicked_for_assign.emit(preset)

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        preset = item.data(256)
        if preset is not None:
            self.preset_selected.emit(preset)
