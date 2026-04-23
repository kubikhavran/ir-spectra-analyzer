"""Panel showing ranked functional-group scores and band suggestions."""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)


class FunctionalGroupPanel(QWidget):
    """Ranked functional-group results with clickable diagnostic suggestions."""

    group_selected = Signal(object)  # emits FunctionalGroupScore
    suggestion_selected = Signal(object)  # emits DiagnosticBandMatch
    diagnostic_visibility_changed = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._results: list = []
        self._active_peak = None
        self._assignment_preview_map: dict[str, str] = {}
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self._status_label = QLabel("No functional-group analysis")
        self._status_label.setStyleSheet("color: gray; font-size: 9pt;")
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
        self._group_list.currentRowChanged.connect(self._on_group_row_changed)
        layout.addWidget(self._group_list, stretch=3)

        self._group_info_label = QLabel()
        self._group_info_label.setWordWrap(True)
        self._group_info_label.setOpenExternalLinks(True)
        self._group_info_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self._group_info_label.setStyleSheet(
            "font-size: 9pt; color: #444; background: #FAFAFA; border: 1px solid #E0E0E0; "
            "padding: 6px; border-radius: 4px;"
        )
        self._group_info_label.setText("Select a functional group to inspect its evidence.")
        layout.addWidget(self._group_info_label)

        self._peak_info_label = QLabel()
        self._peak_info_label.setWordWrap(True)
        self._peak_info_label.setStyleSheet(
            "font-size: 9pt; color: #375A7F; background: #F4F8FB; border: 1px solid #D6E4F0; "
            "padding: 6px; border-radius: 4px;"
        )
        self._peak_info_label.setText("Select a peak to see assignment suggestions for it.")
        layout.addWidget(self._peak_info_label)

        self._detail_label = QLabel("Diagnostic vibrations")
        self._detail_label.setStyleSheet("font-size: 9pt; color: #555;")
        layout.addWidget(self._detail_label)

        self._detail_list = QListWidget()
        self._detail_list.itemDoubleClicked.connect(self._on_detail_double_clicked)
        layout.addWidget(self._detail_list, stretch=2)

    def clear(self) -> None:
        self._results = []
        self._group_list.clear()
        self._detail_list.clear()
        self._status_label.setText("No functional-group analysis")
        self._group_info_label.setText("Select a functional group to inspect its evidence.")
        self._peak_info_label.setText("Select a peak to see assignment suggestions for it.")
        self._assignment_preview_map = {}
        self._detail_label.setText("Diagnostic vibrations")

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
            self._status_label.setText("No functional-group analysis")
            self._group_info_label.setText("Select a functional group to inspect its evidence.")
            self._peak_info_label.setText("Select a peak to see assignment suggestions for it.")
            self._detail_label.setText("Diagnostic vibrations")
            return

        self._status_label.setText(f"{len(results)} functional groups ranked")
        for result in results:
            item = QListWidgetItem(f"{result.group_name}  —  {result.score:.1f}%")
            item.setData(256, result)
            item.setForeground(QColor(result.color))
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

    def set_active_peak(self, peak) -> None:
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

        if self._active_peak is not None:
            self._detail_label.setText(
                f"Suggestions for active peak {self._active_peak.position:.0f} cm\u207b\u00b9"
            )
        else:
            self._detail_label.setText("Suggested vibrations and evidence")

        suggestions = list(result.suggested_bands or result.bands)
        if self._active_peak is not None:
            suggestions.sort(
                key=lambda band: (
                    not self._is_actionable_band(band),
                    not (band.is_assignable and band.covers_wavenumber(self._active_peak.position)),
                    not self._can_assign_band(band),
                    not band.covers_wavenumber(self._active_peak.position),
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
            item.setData(256, band)
            item.setForeground(self._band_foreground_color(band))
            item.setToolTip(self._band_tooltip(band))
            if self._active_peak is not None and band.covers_wavenumber(self._active_peak.position):
                item.setBackground(QColor("#E8F6F3"))
            self._detail_list.addItem(item)

    def _rebuild_group_info(self, result) -> None:
        matched = ", ".join(band.label for band in result.matched_bands[:3]) or "none"
        missing = ", ".join(band.label for band in result.missing_bands[:3]) or "none"
        bonuses = ", ".join(result.matched_bonus_labels) or "none"
        sources = self._format_source_links(result.source_links)
        self._group_info_label.setText(
            f"<b>{result.group_name}</b><br>"
            f"Matched: {matched}<br>"
            f"Missing required: {missing}<br>"
            f"Coherence bonus: {bonuses}<br>"
            f"Sources: {sources}"
        )

    def _rebuild_peak_info(self, result) -> None:
        if self._active_peak is None:
            self._peak_info_label.setText("Select a peak to see assignment suggestions for it.")
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
            preview_text = f' It will assign "{preview_name}".' if preview_name else ""
            self._peak_info_label.setText(
                f"<b>Peak {active_position:.0f} cm\u207b\u00b9</b><br>"
                f"Best assignable match: {best_band.label} ({best_band.confidence:.0f}%). "
                f"Observed {best_band.observed_intensity_class}, expected {best_band.expected_intensity}. "
                f"Double-click a green suggestion to assign it into the peak table.{preview_text}"
            )
            return

        local_evidence = [
            band for band in result.bands if band.covers_wavenumber(active_position)
        ]
        if local_evidence:
            best_band = max(local_evidence, key=lambda band: band.confidence)
            self._peak_info_label.setText(
                f"<b>Peak {active_position:.0f} cm\u207b\u00b9</b><br>"
                f"This group has local evidence at {best_band.label}, but no assignable suggestion "
                "is available for the active peak yet."
            )
            return

        self._peak_info_label.setText(
            f"<b>Peak {active_position:.0f} cm\u207b\u00b9</b><br>"
            "The active peak lies outside this group's diagnostic regions."
        )

    def _band_foreground_color(self, band) -> QColor:
        if band.is_missing_required:
            return QColor("#C0392B")
        if band.is_confirmed:
            return QColor(band.color)
        return QColor("#AF6E00")

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
            lines.append(f'Will assign: {preview_name}')
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
            rendered.append(f'<a href="{link}">[{index}]</a>')
        return " ".join(rendered)

    def _on_detail_double_clicked(self, item: QListWidgetItem) -> None:
        band = item.data(256)
        if band is not None and self._is_actionable_band(band):
            self.suggestion_selected.emit(band)
