"""Panel showing ranked functional-group scores and band suggestions."""

from __future__ import annotations

from html import escape
from typing import TYPE_CHECKING

from PySide6.QtCore import QRectF, QSignalBlocker, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from ui import theme
from ui.i18n import tr
from ui.score_row_delegate import NAME_ROLE, SCORE_ROLE, ScoreRowDelegate

if TYPE_CHECKING:
    from core.peak import Peak

_BAND_ROLE = 256
_BAND_STATUS_ROLE = 257
_BAND_ACTIONABLE_ROLE = 258
_BAND_PREVIEW_ROLE = 259


class _DiagnosticBandDelegate(QStyledItemDelegate):
    """Renders each diagnostic band as a structured two-line card row with a status pill."""

    _ROW_HEIGHT = 44

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:  # noqa: N802
        width = option.rect.width() if option.rect.width() > 0 else 220
        return QSize(width, self._ROW_HEIGHT)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        band = index.data(_BAND_ROLE)
        if band is None:
            super().paint(painter, option, index)
            return

        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)

        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
        actionable = bool(index.data(_BAND_ACTIONABLE_ROLE))
        status_text = str(index.data(_BAND_STATUS_ROLE) or "")
        preview_name = str(index.data(_BAND_PREVIEW_ROLE) or "")

        if actionable:
            pill_bg, pill_fg = theme.SUCCESS_SOFT, theme.SUCCESS
        elif getattr(band, "is_missing_required", False):
            pill_bg, pill_fg = theme.DANGER_SOFT, theme.DANGER
        elif getattr(band, "is_confirmed", False):
            pill_bg, pill_fg = theme.ACCENT_SOFT, theme.ACCENT_DARK
        else:
            pill_bg, pill_fg = theme.WARNING_SOFT, theme.WARNING

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = option.rect.adjusted(6, 4, -8, -4)
        top_h = rect.height() // 2
        top_rect = rect.adjusted(0, 0, 0, -(rect.height() - top_h))
        bottom_rect = rect.adjusted(0, top_h + 1, 0, 0)

        # 1. Status pill on top-left
        pill_font = QFont(option.font)
        pill_font.setBold(True)
        if pill_font.pointSizeF() > 0:
            pill_font.setPointSizeF(max(7.5, pill_font.pointSizeF() * 0.85))
        painter.setFont(pill_font)
        pill_metrics = QFontMetrics(pill_font)
        pill_w = pill_metrics.horizontalAdvance(status_text) + 12
        pill_h = min(17, top_rect.height())
        pill_rect = QRectF(
            top_rect.left(),
            top_rect.top() + (top_rect.height() - pill_h) / 2.0,
            pill_w,
            pill_h,
        )
        painter.setBrush(QColor(pill_bg))
        painter.setPen(QPen(QColor(theme.ON_ACCENT), 1.0) if is_selected else Qt.PenStyle.NoPen)
        painter.drawRoundedRect(pill_rect, pill_h / 2.0, pill_h / 2.0)
        painter.setPen(QColor(pill_fg))
        painter.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, status_text)

        # 2. Confidence % on top-right
        conf_text = f"{band.confidence:.0f}%"
        title_font = QFont(option.font)
        title_font.setBold(True)
        painter.setFont(title_font)
        title_metrics = QFontMetrics(title_font)
        conf_w = title_metrics.horizontalAdvance(conf_text) + 6
        conf_rect = top_rect.adjusted(top_rect.width() - conf_w, 0, 0, 0)
        painter.setPen(QColor(theme.ON_ACCENT if is_selected else theme.ACCENT_DARK))
        painter.drawText(
            conf_rect,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            conf_text,
        )

        # 3. Band label between pill and confidence
        label_rect = top_rect.adjusted(int(pill_w) + 6, 0, -(conf_w + 4), 0)
        painter.setPen(QColor(theme.ON_ACCENT if is_selected else theme.TEXT))
        elided_label = title_metrics.elidedText(
            str(band.label), Qt.TextElideMode.ElideRight, max(20, label_rect.width())
        )
        painter.drawText(
            label_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            elided_label,
        )

        # 4. Secondary subtitle line: range + observed intensity + assignment preview
        sub_font = QFont(option.font)
        if sub_font.pointSizeF() > 0:
            sub_font.setPointSizeF(max(7.5, sub_font.pointSizeF() * 0.9))
        painter.setFont(sub_font)
        sub_metrics = QFontMetrics(sub_font)
        sub_text = (
            f"{band.range_min:.0f}\u2013{band.range_max:.0f} cm\u207b\u00b9 \u00b7 "
            f"{band.observed_intensity_class}"
        )
        if preview_name:
            sub_text += f"  \u2192  {preview_name}"
        painter.setPen(
            QColor(
                theme.ON_ACCENT_MUTED
                if is_selected
                else (theme.SUCCESS if actionable else theme.TEXT_MUTED)
            )
        )
        elided_sub = sub_metrics.elidedText(
            sub_text, Qt.TextElideMode.ElideRight, max(20, bottom_rect.width())
        )
        painter.drawText(
            bottom_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            elided_sub,
        )
        painter.restore()


class FunctionalGroupPanel(QWidget):
    """Ranked functional-group results with clickable diagnostic suggestions."""

    group_selected = Signal(object)  # emits FunctionalGroupScore
    suggestion_selected = Signal(object)  # emits DiagnosticBandMatch
    diagnostic_visibility_changed = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._results: list = []
        self._active_peak: Peak | None = None
        self._assignment_preview_map: dict[str, str] = {}
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(5)

        self._status_label = QLabel("No functional-group analysis")
        self._status_label.setStyleSheet(theme.CAPTION_STYLE)
        self._status_label.setToolTip(
            "Confidence score is a heuristic ranking from diagnostic IR bands. "
            "It is not a statistically calibrated probability."
        )
        layout.addWidget(self._status_label)

        self._show_regions_checkbox = QCheckBox("Show highlighted regions in spectrum")
        self._show_regions_checkbox.setChecked(True)
        self._show_regions_checkbox.toggled.connect(self.diagnostic_visibility_changed.emit)
        layout.addWidget(self._show_regions_checkbox)

        self._group_list = QListWidget()
        self._group_list.setItemDelegate(ScoreRowDelegate(self._group_list))
        self._group_list.setAlternatingRowColors(True)
        self._group_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._group_list.currentRowChanged.connect(self._on_group_row_changed)
        layout.addWidget(self._group_list, stretch=3)

        self._group_info_label = QLabel()
        self._group_info_label.setTextFormat(Qt.TextFormat.RichText)
        self._group_info_label.setWordWrap(True)
        self._group_info_label.setOpenExternalLinks(True)
        self._group_info_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction
        )
        self._group_info_label.setStyleSheet(theme.INFO_CARD_STYLE)
        self._group_info_label.setText("Select a functional group to inspect its evidence.")
        layout.addWidget(self._group_info_label)

        self._peak_info_label = QLabel()
        self._peak_info_label.setTextFormat(Qt.TextFormat.RichText)
        self._peak_info_label.setWordWrap(True)
        self._peak_info_label.setStyleSheet(theme.ACCENT_CARD_STYLE)
        self._peak_info_label.setText("Select a peak to see assignment suggestions for it.")
        layout.addWidget(self._peak_info_label)

        self._detail_label = QLabel("Diagnostic vibrations")
        self._detail_label.setStyleSheet(theme.SECTION_TITLE_STYLE)
        layout.addWidget(self._detail_label)

        self._detail_list = QListWidget()
        self._detail_delegate = _DiagnosticBandDelegate(self._detail_list)
        self._detail_list.setItemDelegate(self._detail_delegate)
        self._detail_list.setAlternatingRowColors(True)
        self._detail_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._detail_list.itemDoubleClicked.connect(self._on_detail_double_clicked)
        layout.addWidget(self._detail_list, stretch=2)

    def clear(self) -> None:
        self._results = []
        self._group_list.clear()
        self._detail_list.clear()
        self._status_label.setText(tr("No functional-group analysis"))
        self._group_info_label.setText(tr("Select a functional group to inspect its evidence."))
        self._peak_info_label.setText(tr("Select a peak to see assignment suggestions for it."))
        self._assignment_preview_map = {}
        self._detail_label.setText(tr("Diagnostic vibrations"))

    def set_results(self, results: list) -> None:
        previous_group_id = None
        current = self.current_result()
        if current is not None:
            previous_group_id = current.group_id

        self._results = list(results)
        self._group_list.clear()
        self._detail_list.clear()
        self._assignment_preview_map = {}

        if not results:
            self._status_label.setText(tr("No functional-group analysis"))
            self._group_info_label.setText(tr("Select a functional group to inspect its evidence."))
            self._peak_info_label.setText(tr("Select a peak to see assignment suggestions for it."))
            self._detail_label.setText(tr("Diagnostic vibrations"))
            return

        self._status_label.setText(
            tr("{count} functional groups ranked").format(count=len(results))
        )
        for result in results:
            item = QListWidgetItem(f"{result.group_name}  —  {result.score:.1f}%")
            item.setData(256, result)
            item.setData(NAME_ROLE, str(result.group_name))
            item.setData(SCORE_ROLE, float(result.score))
            self._group_list.addItem(item)

        selected_row = 0
        if previous_group_id is not None:
            selected_row = next(
                (
                    index
                    for index, result in enumerate(results)
                    if result.group_id == previous_group_id
                ),
                0,
            )

        blocker = QSignalBlocker(self._group_list)
        self._group_list.setCurrentRow(selected_row)
        del blocker
        selected_result = results[selected_row]
        self._rebuild_group_info(selected_result)
        self._rebuild_peak_info(selected_result)
        self.group_selected.emit(selected_result)
        self._rebuild_detail_list(selected_result)

    def set_active_peak(self, peak: Peak | None) -> None:
        self._active_peak = peak
        current = self.current_result()
        if current is not None:
            self._rebuild_peak_info(current)
            self._rebuild_detail_list(current)

    def set_assignment_preview_map(self, preview_map: dict[str, str]) -> None:
        self._assignment_preview_map = dict(preview_map)
        current = self.current_result()
        if current is not None:
            self._rebuild_peak_info(current)
            self._rebuild_detail_list(current)

    def current_result(self):
        row = self._group_list.currentRow()
        if 0 <= row < len(self._results):
            return self._results[row]
        return None

    def select_group_by_id(self, group_id: str) -> bool:
        """Select one functional-group row by group ID."""
        for row, result in enumerate(self._results):
            if result.group_id != group_id:
                continue
            if self._group_list.currentRow() == row:
                self.group_selected.emit(result)
                self._rebuild_group_info(result)
                self._rebuild_peak_info(result)
                self._rebuild_detail_list(result)
            else:
                self._group_list.setCurrentRow(row)
            return True
        return False

    def _on_group_row_changed(self, row: int) -> None:
        if 0 <= row < len(self._results):
            result = self._results[row]
            self.group_selected.emit(result)
            self._rebuild_group_info(result)
            self._rebuild_peak_info(result)
            self._rebuild_detail_list(result)

    def _rebuild_detail_list(self, result) -> None:
        self._detail_list.clear()
        active_peak = self._active_peak

        if active_peak is not None:
            self._detail_label.setText(
                tr("Suggestions for active peak {wavenumber} cm\u207b\u00b9").format(
                    wavenumber=f"{active_peak.position:.0f}"
                )
            )
        else:
            self._detail_label.setText(tr("Suggested vibrations and evidence"))

        suggestions = list(result.suggested_bands or result.bands)
        if active_peak is not None:
            suggestions.sort(
                key=lambda band: (
                    not self._is_actionable_band(band),
                    not (band.is_assignable and band.covers_wavenumber(active_peak.position)),
                    not self._can_assign_band(band),
                    not band.covers_wavenumber(active_peak.position),
                    band.is_missing_required,
                    -band.confidence,
                    -band.range_max,
                )
            )
        else:
            suggestions.sort(
                key=lambda band: (
                    not self._can_assign_band(band),
                    band.is_missing_required,
                    -band.confidence,
                    -band.range_max,
                )
            )

        for band in suggestions:
            prefix = self._band_prefix(band)
            text = (
                f"{prefix}{band.evidence_label}  {band.confidence:.0f}%  {band.label}  "
                f"({band.range_min:.0f}\u2013{band.range_max:.0f} cm\u207b\u00b9, "
                f"{band.observed_intensity_class})"
            )
            preview_name = self._preview_name_for_band(band)
            if preview_name:
                text += f"  \u2192  {preview_name}"
            item = QListWidgetItem(text)
            item.setData(_BAND_ROLE, band)
            item.setData(_BAND_STATUS_ROLE, f"{prefix.strip()} \u00b7 {band.evidence_label}")
            item.setData(_BAND_ACTIONABLE_ROLE, self._is_actionable_band(band))
            item.setData(_BAND_PREVIEW_ROLE, preview_name)
            item.setForeground(self._band_foreground_color(band))
            item.setToolTip(self._band_tooltip(band))
            if active_peak is not None and band.covers_wavenumber(active_peak.position):
                item.setBackground(QColor(theme.ROW_POSITIVE))
            self._detail_list.addItem(item)

    def _rebuild_group_info(self, result) -> None:
        matched = ", ".join(escape(str(band.label)) for band in result.matched_bands[:3]) or "none"
        missing = ", ".join(escape(str(band.label)) for band in result.missing_bands[:3]) or "none"
        bonuses = ", ".join(escape(str(label)) for label in result.matched_bonus_labels) or "none"
        sources = self._format_source_links(result.source_links)
        self._group_info_label.setText(
            f"<b>{escape(str(result.group_name))}</b><br>"
            f"Matched: {matched}<br>"
            f"Missing required: {missing}<br>"
            f"Coherence bonus: {bonuses}<br>"
            f"Sources: {sources}"
        )

    def _rebuild_peak_info(self, result) -> None:
        if self._active_peak is None:
            self._peak_info_label.setText(tr("Select a peak to see assignment suggestions for it."))
            return

        active_position = self._active_peak.position
        assignable = [
            band
            for band in result.suggested_bands
            if band.is_assignable and band.covers_wavenumber(active_position)
        ]
        if assignable:
            best_band = max(assignable, key=lambda band: band.confidence)
            preview_name = self._preview_name_for_band(best_band)
            preview_text = f' It will assign "{escape(str(preview_name))}".' if preview_name else ""
            self._peak_info_label.setText(
                f"<b>Peak {active_position:.0f} cm\u207b\u00b9</b><br>"
                f"Best assignable match: {escape(str(best_band.label))} "
                f"({best_band.confidence:.0f}%). Observed "
                f"{escape(str(best_band.observed_intensity_class))}, expected "
                f"{escape(str(best_band.expected_intensity))}. "
                f"Double-click a green suggestion to assign it into the peak table.{preview_text}"
            )
            return

        local_evidence = [band for band in result.bands if band.covers_wavenumber(active_position)]
        if local_evidence:
            best_band = max(local_evidence, key=lambda band: band.confidence)
            self._peak_info_label.setText(
                f"<b>Peak {active_position:.0f} cm\u207b\u00b9</b><br>"
                f"This group has local evidence at {escape(str(best_band.label))}, "
                "but no assignable suggestion "
                "is available for the active peak yet."
            )
            return

        self._peak_info_label.setText(
            f"<b>Peak {active_position:.0f} cm\u207b\u00b9</b><br>"
            "The active peak lies outside this group's diagnostic regions."
        )

    def _band_foreground_color(self, band) -> QColor:
        if band.is_missing_required:
            return QColor(theme.DANGER)
        if band.is_confirmed:
            return QColor(band.color)
        return QColor(theme.WARNING)

    def _band_prefix(self, band) -> str:
        if self._is_actionable_band(band):
            return "\u25b6 Assign  "
        if self._can_assign_band(band):
            return "Assign  "
        return "Info  "

    def _band_tooltip(self, band) -> str:
        lines = [
            f"Role: {band.role}",
            f"Expected intensity: {band.expected_intensity}",
            f"Observed intensity: {band.observed_intensity_class}",
        ]
        if band.matched_wavenumber is not None:
            lines.append(f"Matched at: {band.matched_wavenumber:.1f} cm-1")
        preview_name = self._preview_name_for_band(band)
        if preview_name:
            lines.append(f"Will assign: {preview_name}")
        if band.source_links:
            lines.append("Sources: " + ", ".join(band.source_links[:3]))
        if self._is_actionable_band(band):
            lines.append("Double-click to assign this vibration to the active peak.")
        elif self._can_assign_band(band):
            lines.append("Select a peak inside this band's range to enable assignment.")
        else:
            lines.append("Evidence only; no direct assignment is available.")
        return "\n".join(lines)

    def _preview_name_for_band(self, band) -> str:
        return self._assignment_preview_map.get(band.band_id, "")

    def _can_assign_band(self, band) -> bool:
        return bool(self._preview_name_for_band(band))

    def _is_actionable_band(self, band) -> bool:
        if self._active_peak is None:
            return False
        return bool(self._preview_name_for_band(band)) and band.covers_wavenumber(
            self._active_peak.position
        )

    def _format_source_links(self, links: tuple[str, ...]) -> str:
        if not links:
            return "none"
        rendered = []
        for index, link in enumerate(links[:3], start=1):
            rendered.append(f'<a href="{escape(str(link), quote=True)}">[{index}]</a>')
        return " ".join(rendered)

    def _on_detail_double_clicked(self, item: QListWidgetItem) -> None:
        band = item.data(256)
        if band is not None and self._is_actionable_band(band):
            self.suggestion_selected.emit(band)
