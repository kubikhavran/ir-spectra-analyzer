"""
PeakTableWidget — Tabulka detekovaných peaků.

Zodpovědnost:
- Zobrazení peaků ve formátu QTableWidget
- Editace labelu a přiřazené vibrace inline
- Synchronizace s SpectrumWidget (výběr v tabulce = highlight v grafu)
- Signály pro přidání/odebrání peaku
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from core.peak import Peak


class PeakTableWidget(QWidget):
    """Editable table displaying detected/assigned IR peaks."""

    peak_selected = Signal(object)  # emits Peak on row selection
    peak_deleted = Signal(object)  # emits Peak on delete action
    vibration_label_removed = Signal(object, str)  # emits (Peak, label_str) on removal

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._peaks: list[Peak] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(
            ["Position (cm⁻¹)", "Intensity", "Label", "Vibration"]
        )
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setSelectionBehavior(self._table.SelectionBehavior.SelectRows)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        self._table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self._table)

    def _on_selection_changed(self) -> None:
        row = self._table.currentRow()
        if 0 <= row < len(self._peaks):
            self.peak_selected.emit(self._peaks[row])

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        """Detect when user clears/edits the Vibration column and emit removed labels."""
        if item.column() != 3:
            return
        row = item.row()
        if not (0 <= row < len(self._peaks)):
            return
        peak = self._peaks[row]
        if not peak.vibration_labels:
            return
        new_text = item.text().strip()
        new_labels = [lb.strip() for lb in new_text.split("/") if lb.strip()] if new_text else []
        for label in list(peak.vibration_labels):
            if label not in new_labels:
                self.vibration_label_removed.emit(peak, label)

    def set_peaks(self, peaks: list[Peak]) -> None:
        """Populate the table with peaks."""
        self._peaks = peaks
        self._table.blockSignals(True)
        self._table.setRowCount(len(peaks))
        for row, peak in enumerate(peaks):
            self._table.setItem(row, 0, QTableWidgetItem(str(int(round(peak.position)))))
            self._table.setItem(row, 1, QTableWidgetItem(str(int(round(peak.intensity)))))
            self._table.setItem(row, 2, QTableWidgetItem(peak.label))
            assignment = peak.display_label if peak.vibration_labels else ""
            self._table.setItem(row, 3, QTableWidgetItem(assignment))
        self._table.blockSignals(False)

    def selected_peak(self) -> Peak | None:
        """Return the currently selected Peak, or None."""
        row = self._table.currentRow()
        if 0 <= row < len(self._peaks):
            return self._peaks[row]
        return None

    def select_peak(self, peak: Peak) -> None:
        """Programmatically select the row matching the given peak."""
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if item is None:
                continue
            try:
                pos = float(item.text())
            except ValueError:
                continue
            if abs(pos - peak.position) < 0.1:
                self._table.selectRow(row)
                self._table.scrollToItem(item)
                return
