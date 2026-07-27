"""
PeakTableWidget — Tabulka detekovaných peaků.

Zodpovědnost:
- Zobrazení peaků ve formátu QTableWidget
- Editace labelu a přiřazené vibrace inline
- Synchronizace s SpectrumWidget (výběr v tabulce = highlight v grafu)
- Signály pro přidání/odebrání peaku
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.peak import Peak

_HEADERS = ["Position (cm⁻¹)", "Intensity", "Label", "Vibration"]

# How far a non-identical Peak may sit from a table row to still select it (cm⁻¹).
_SELECT_MATCH_TOLERANCE = 1.0


class _CopyableTable(QTableWidget):
    """QTableWidget that copies selected rows as TSV on Ctrl+C."""

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.matches(QKeySequence.StandardKey.Copy):
            self._copy_selection_to_clipboard()
        else:
            super().keyPressEvent(event)

    def _copy_selection_to_clipboard(self) -> None:
        selected_rows = sorted({idx.row() for idx in self.selectedIndexes()})
        if not selected_rows:
            return
        lines = ["\t".join(_HEADERS)]
        for row in selected_rows:
            cells = []
            for col in range(self.columnCount()):
                item = self.item(row, col)
                cells.append(item.text() if item else "")
            lines.append("\t".join(cells))
        QApplication.clipboard().setText("\n".join(lines))


class PeakTableWidget(QWidget):
    """Editable table displaying detected/assigned IR peaks."""

    peak_selected = Signal(object)  # emits Peak on row selection
    peak_deleted = Signal(object)  # emits Peak on delete action
    vibration_label_removed = Signal(object, str)  # emits (Peak, label_str) on removal
    vibration_edit_requested = Signal(object)  # emits Peak when vibration text should be edited

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._peaks: list[Peak] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        self._copy_all_btn = QPushButton("Copy all")
        self._copy_all_btn.setFixedHeight(22)
        self._copy_all_btn.setToolTip("Copy entire peak table to clipboard (TSV)")
        self._copy_all_btn.clicked.connect(self._copy_all_to_clipboard)
        toolbar.addStretch()
        toolbar.addWidget(self._copy_all_btn)
        layout.addLayout(toolbar)

        self._table = _CopyableTable(0, 4)
        self._table.setHorizontalHeaderLabels(_HEADERS)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setSelectionBehavior(self._table.SelectionBehavior.SelectRows)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        self._table.itemChanged.connect(self._on_item_changed)
        self._table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        layout.addWidget(self._table)

    def _copy_all_to_clipboard(self) -> None:
        """Copy all rows to clipboard as TSV."""
        lines = ["\t".join(_HEADERS)]
        for row in range(self._table.rowCount()):
            cells = []
            for col in range(self._table.columnCount()):
                item = self._table.item(row, col)
                cells.append(item.text() if item else "")
            lines.append("\t".join(cells))
        QApplication.clipboard().setText("\n".join(lines))

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

    def _on_cell_double_clicked(self, row: int, column: int) -> None:
        if column != 3:
            return
        if 0 <= row < len(self._peaks):
            self.vibration_edit_requested.emit(self._peaks[row])

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
            vibration_item = QTableWidgetItem(assignment)
            vibration_item.setFlags(vibration_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, 3, vibration_item)
        self._table.blockSignals(False)

    def selected_peak(self) -> Peak | None:
        """Return the currently selected Peak, or None."""
        row = self._table.currentRow()
        if 0 <= row < len(self._peaks):
            return self._peaks[row]
        return None

    def select_peak(self, peak: Peak) -> None:
        """Programmatically select the row holding the given peak.

        Matching is by identity: the Position column is rounded for display, so
        comparing it against a real position (3041.5 shown as "3042") missed
        every peak that does not sit near a whole wavenumber. Callers that pass
        a different Peak instance — e.g. one reloaded from a saved project —
        fall back to the closest position.
        """
        for row, candidate in enumerate(self._peaks):
            if candidate is peak:
                self._select_row(row)
                return

        nearest_row: int | None = None
        nearest_distance = float("inf")
        for row, candidate in enumerate(self._peaks):
            distance = abs(candidate.position - peak.position)
            if distance < nearest_distance:
                nearest_row, nearest_distance = row, distance
        if nearest_row is not None and nearest_distance <= _SELECT_MATCH_TOLERANCE:
            self._select_row(nearest_row)

    def _select_row(self, row: int) -> None:
        """Select one row and scroll it into view."""
        self._table.selectRow(row)
        item = self._table.item(row, 0)
        if item is not None:
            self._table.scrollToItem(item)
