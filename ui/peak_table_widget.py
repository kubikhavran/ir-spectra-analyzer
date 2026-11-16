"""
PeakTableWidget — Tabulka detekovaných peaků.

Zodpovědnost:
- Zobrazení peaků ve formátu QTableWidget
- Otevření dedikovaného editoru vibrací dvojklikem
- Synchronizace s SpectrumWidget (výběr v tabulce = highlight v grafu)
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.peak import Peak
from core.peak_assignments import (
    classify_peak_intensities,
    peak_assignment_text,
    peak_has_assignment,
)
from ui import theme
from ui.i18n import tr

# "Rel." is the relative band strength (w / m / s / vs) the report prints. It
# replaced a "Label" column that only repeated the position.
_HEADERS = ["Position (cm⁻¹)", "Intensity", "Rel.", "Vibration"]
_COLUMN_TIPS = {
    2: "Relative band strength: w = weak, m = medium, s = strong, vs = very strong",
    3: "Double-click to edit the vibration text",
}
_NUMERIC_ALIGNMENT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

# How far a non-identical Peak may sit from a table row to still select it (cm⁻¹).
_SELECT_MATCH_TOLERANCE = 1.0


def format_intensity(value: float, scale: float | None = None) -> str:
    """Intensity as table text, with decimals that fit the scale it is on.

    Rounding to a whole number suits %T but turned every absorbance value into
    "0" or "1" — the column carried no information for an absorbance spectrum.
    ``scale`` is the largest magnitude in the column, so every row of one table
    gets the same number of decimals.
    """
    reference = abs(value) if scale is None else scale
    if reference >= 10.0:
        return f"{value:.1f}"
    return f"{value:.3f}"


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
        lines = ["\t".join(tr(header) for header in _HEADERS)]
        for row in selected_rows:
            cells = []
            for col in range(self.columnCount()):
                item = self.item(row, col)
                cells.append(item.text() if item else "")
            lines.append("\t".join(cells))
        QApplication.clipboard().setText("\n".join(lines))


class PeakTableWidget(QWidget):
    """Read-only peak overview; assignments are edited through the dedicated dialog."""

    peak_selected = Signal(object)  # emits Peak on row selection
    peak_deleted = Signal(object)  # emits Peak on delete action
    vibration_edit_requested = Signal(object)  # emits Peak when vibration text should be edited

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._peaks: list[Peak] = []
        self._is_dip_spectrum = False
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(6, 4, 6, 2)
        # How far the assignment work has got, always in view above the rows.
        self._summary_label = QLabel(tr("No peaks"))
        self._summary_label.setStyleSheet(theme.CAPTION_STYLE)
        toolbar.addWidget(self._summary_label)
        self._copy_all_btn = QPushButton(tr("Copy all"))
        self._copy_all_btn.setToolTip(tr("Copy entire peak table to clipboard (TSV)"))
        self._copy_all_btn.clicked.connect(self._copy_all_to_clipboard)
        toolbar.addStretch()
        toolbar.addWidget(self._copy_all_btn)
        layout.addLayout(toolbar)

        self._table = _CopyableTable(0, 4)
        self._table.setHorizontalHeaderLabels([tr(header) for header in _HEADERS])
        for column in (0, 1):
            self._table.horizontalHeaderItem(column).setTextAlignment(_NUMERIC_ALIGNMENT)
        self._table.horizontalHeaderItem(2).setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        for column, tip in _COLUMN_TIPS.items():
            self._table.horizontalHeaderItem(column).setToolTip(tr(tip))
        header = self._table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._table.setColumnWidth(0, 130)
        self._table.setColumnWidth(1, 100)
        self._table.setColumnWidth(2, 60)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.verticalHeader().setDefaultSectionSize(24)
        self._table.setSelectionBehavior(self._table.SelectionBehavior.SelectRows)
        # Position/intensity/label edits were previously accepted visually but
        # never propagated to the Project model.  Keep the table honest and use
        # the existing double-click assignment dialog for actual edits.
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        self._table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        layout.addWidget(self._table)

    def _copy_all_to_clipboard(self) -> None:
        """Copy all rows to clipboard as TSV."""
        lines = ["\t".join(tr(header) for header in _HEADERS)]
        for row in range(self._table.rowCount()):
            cells = []
            for col in range(self._table.columnCount()):
                item = self._table.item(row, col)
                cells.append(item.text() if item else "")
            lines.append("\t".join(cells))
        QApplication.clipboard().setText("\n".join(lines))

    def _on_selection_changed(self) -> None:
        row = int(self._table.currentRow())
        if 0 <= row < len(self._peaks):
            self.peak_selected.emit(self._peaks[row])

    def _on_cell_double_clicked(self, row: int, column: int) -> None:
        if column != 3:
            return
        if 0 <= row < len(self._peaks):
            self.vibration_edit_requested.emit(self._peaks[row])

    def set_peaks(self, peaks: list[Peak], is_dip_spectrum: bool | None = None) -> None:
        """Populate the table with peaks.

        Args:
            peaks: Peaks to list, in display order.
            is_dip_spectrum: Whether bands point down (%T). Needed to rate the
                relative strength; when omitted the last known value is kept.
        """
        self._peaks = peaks
        if is_dip_spectrum is not None:
            self._is_dip_spectrum = bool(is_dip_spectrum)
        strengths = classify_peak_intensities(peaks, is_dip_spectrum=self._is_dip_spectrum)
        self._table.blockSignals(True)
        self._table.setRowCount(len(peaks))
        scale = max((abs(peak.intensity) for peak in peaks), default=0.0)
        for row, peak in enumerate(peaks):
            position_item = QTableWidgetItem(str(int(round(peak.position))))
            position_item.setTextAlignment(_NUMERIC_ALIGNMENT)
            position_item.setToolTip(f"{peak.position:.2f} cm\u207b\u00b9")
            self._table.setItem(row, 0, position_item)
            intensity_item = QTableWidgetItem(format_intensity(peak.intensity, scale))
            intensity_item.setTextAlignment(_NUMERIC_ALIGNMENT)
            self._table.setItem(row, 1, intensity_item)
            strength_item = QTableWidgetItem(strengths.get(id(peak), ""))
            strength_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 2, strength_item)
            assignment = peak_assignment_text(peak)
            vibration_item = QTableWidgetItem(assignment)
            vibration_item.setFlags(vibration_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, 3, vibration_item)
        self._table.blockSignals(False)
        self._summary_label.setText(self.summary_text())

    def summary_text(self) -> str:
        """ "41 peaks · 3 assigned" — the progress line shown above the table."""
        total = len(self._peaks)
        if total == 0:
            return tr("No peaks")
        assigned = sum(1 for peak in self._peaks if peak_has_assignment(peak))
        return tr("{total} peaks \u00b7 {assigned} assigned").format(total=total, assigned=assigned)

    def selected_peak(self) -> Peak | None:
        """Return the currently selected Peak, or None."""
        row = int(self._table.currentRow())
        if 0 <= row < len(self._peaks):
            return self._peaks[row]
        return None

    def selected_peaks(self) -> list[Peak]:
        """Return every peak whose row is selected, in table order."""
        rows = sorted({index.row() for index in self._table.selectedIndexes()})
        return [self._peaks[row] for row in rows if 0 <= row < len(self._peaks)]

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
