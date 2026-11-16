"""
PeakTableWidget — Tabulka detekovaných peaků.

Zodpovědnost:
- Zobrazení peaků ve formátu QTableWidget
- Otevření dedikovaného editoru vibrací dvojklikem
- Synchronizace s SpectrumWidget (výběr v tabulce = highlight v grafu)
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
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

_STRENGTH_PILL_COLORS: dict[str, tuple[str, str]] = {
    "vs": (theme.STRENGTH_VS_BG, theme.STRENGTH_VS_FG),
    "s": (theme.STRENGTH_S_BG, theme.STRENGTH_S_FG),
    "m": (theme.STRENGTH_M_BG, theme.STRENGTH_M_FG),
    "w": (theme.STRENGTH_W_BG, theme.STRENGTH_W_FG),
}


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


class _PeakTableDelegate(QStyledItemDelegate):
    """Paints pill badges in the Rel. column and an italic hint on unassigned rows."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        col = index.column()
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")

        if col == 2 and text in _STRENGTH_PILL_COLORS:
            opt = QStyleOptionViewItem(option)
            self.initStyleOption(opt, index)
            opt.text = ""
            style = opt.widget.style() if opt.widget else QApplication.style()
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)

            bg_hex, fg_hex = _STRENGTH_PILL_COLORS[text]
            rect = option.rect
            pill_w = min(34, max(22, rect.width() - 8))
            pill_h = min(18, max(14, rect.height() - 6))
            pill_rect = QRectF(
                rect.left() + (rect.width() - pill_w) / 2.0,
                rect.top() + (rect.height() - pill_h) / 2.0,
                pill_w,
                pill_h,
            )

            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setBrush(QColor(bg_hex))
            if option.state & QStyle.StateFlag.State_Selected:
                painter.setPen(QPen(QColor("#FFFFFF"), 1.0))
            else:
                painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(pill_rect, pill_h / 2.0, pill_h / 2.0)

            font = QFont(option.font)
            font.setBold(True)
            if font.pointSizeF() > 0:
                font.setPointSizeF(max(7.5, font.pointSizeF() * 0.9))
            painter.setFont(font)
            painter.setPen(QColor(fg_hex))
            painter.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, text)
            painter.restore()
            return

        if col == 3 and not text:
            opt = QStyleOptionViewItem(option)
            self.initStyleOption(opt, index)
            opt.text = ""
            style = opt.widget.style() if opt.widget else QApplication.style()
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)

            painter.save()
            font = QFont(option.font)
            font.setItalic(True)
            painter.setFont(font)
            is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
            painter.setPen(QColor("#DCEAF6" if is_selected else theme.TEXT_FAINT))
            text_rect = option.rect.adjusted(8, 0, -6, 0)
            painter.drawText(
                text_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                tr("Double-click to assign\u2026"),
            )
            painter.restore()
            return

        super().paint(painter, option, index)


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
    #: Emits the text just put on the clipboard by "Copy IR text" ("" if none).
    ir_text_copied = Signal(str)

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
        self._summary_label.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; background: {theme.SURFACE_ALT}; "
            f"border: 1px solid {theme.BORDER}; border-radius: 8px; "
            "padding: 2px 8px; font-size: 9pt; font-weight: 600;"
        )
        toolbar.addWidget(self._summary_label)
        self._copy_all_btn = QPushButton(tr("Copy all"))
        self._copy_all_btn.setToolTip(tr("Copy entire peak table to clipboard (TSV)"))
        self._copy_all_btn.clicked.connect(self._copy_all_to_clipboard)
        toolbar.addStretch()
        self._copy_ir_btn = QPushButton(tr("Copy IR text"))
        self._copy_ir_btn.setToolTip(
            tr(
                "Copy the peak list as written in a protocol or paper, e.g.\n"
                "IR (cm\u207b\u00b9): 3340 (s, \u03bd(OH)), 1715 (vs, \u03bd(C=O)).\n"
                "Assigned peaks only; when none is assigned yet, all peaks."
            )
        )
        self._copy_ir_btn.clicked.connect(self.copy_ir_text)
        toolbar.addWidget(self._copy_ir_btn)
        toolbar.addWidget(self._copy_all_btn)
        layout.addLayout(toolbar)

        self._table = _CopyableTable(0, 4)
        self._delegate = _PeakTableDelegate(self._table)
        self._table.setItemDelegate(self._delegate)
        self._table.setHorizontalHeaderLabels([tr(header) for header in _HEADERS])
        alignments = {0: _NUMERIC_ALIGNMENT, 1: _NUMERIC_ALIGNMENT, 2: Qt.AlignmentFlag.AlignCenter}
        for column in range(self._table.columnCount()):
            header_item = self._table.horizontalHeaderItem(column)
            if header_item is None:
                continue
            if column in alignments:
                header_item.setTextAlignment(alignments[column])
            if column in _COLUMN_TIPS:
                header_item.setToolTip(tr(_COLUMN_TIPS[column]))
        header = self._table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._table.setColumnWidth(0, 130)
        self._table.setColumnWidth(1, 100)
        self._table.setColumnWidth(2, 60)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.verticalHeader().setDefaultSectionSize(26)
        self._table.setSelectionBehavior(self._table.SelectionBehavior.SelectRows)
        # Position/intensity/label edits were previously accepted visually but
        # never propagated to the Project model.  Keep the table honest and use
        # the existing double-click assignment dialog for actual edits.
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        self._table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        layout.addWidget(self._table)

    def ir_text(self) -> str:
        """The publication-style peak list for the peaks in the table."""
        from core.peak_assignments import (  # noqa: PLC0415
            format_publication_ir_string,
            peak_has_assignment,
        )

        include_unassigned = not any(peak_has_assignment(peak) for peak in self._peaks)
        return format_publication_ir_string(
            self._peaks,
            include_unassigned=include_unassigned,
            is_dip_spectrum=self._is_dip_spectrum,
        )

    def copy_ir_text(self) -> str:
        """Put the publication-style peak list on the clipboard and announce it."""
        text = self.ir_text()
        if text:
            QApplication.clipboard().setText(text)
        self.ir_text_copied.emit(text)
        return text

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
