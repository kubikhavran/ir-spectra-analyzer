"""Panel showing a combined interpretation summary across analysis layers."""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from matching.quality import match_quality_label


class ConsensusPanel(QWidget):
    """Read-only summary panel combining chemistry and library evidence."""

    hypothesis_selected = Signal(str)
    match_requested = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._analysis = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self._status_label = QLabel("No consensus analysis")
        self._status_label.setStyleSheet("color: gray; font-size: 9pt;")
        self._status_label.setToolTip(
            "Consensus combines functional-group evidence, library matches, and assigned peaks. "
            "It is an interpretation aid, not a definitive identification."
        )
        layout.addWidget(self._status_label)

        self._headline_label = QLabel("Run matching or inspect functional groups to build consensus.")
        self._headline_label.setWordWrap(True)
        self._headline_label.setStyleSheet(
            "font-size: 10pt; font-weight: 600; color: #2C3E50; "
            "background: #F8F9FA; border: 1px solid #E5E7E9; padding: 6px; border-radius: 4px;"
        )
        layout.addWidget(self._headline_label)

        self._overview_label = QLabel()
        self._overview_label.setWordWrap(True)
        self._overview_label.setStyleSheet(
            "font-size: 9pt; color: #444; background: #FAFAFA; border: 1px solid #E0E0E0; "
            "padding: 6px; border-radius: 4px;"
        )
        self._overview_label.setText("Confirmed, uncertain, and conflicting evidence will appear here.")
        layout.addWidget(self._overview_label)

        self._hypothesis_caption = QLabel("Top hypotheses")
        self._hypothesis_caption.setStyleSheet("font-size: 9pt; color: #555;")
        layout.addWidget(self._hypothesis_caption)

        self._hypothesis_list = QListWidget()
        self._hypothesis_list.currentRowChanged.connect(self._on_hypothesis_row_changed)
        layout.addWidget(self._hypothesis_list, stretch=3)

        self._detail_label = QLabel()
        self._detail_label.setWordWrap(True)
        self._detail_label.setStyleSheet(
            "font-size: 9pt; color: #444; background: #FAFAFA; border: 1px solid #E0E0E0; "
            "padding: 6px; border-radius: 4px;"
        )
        self._detail_label.setText("Select a hypothesis to inspect its evidence.")
        layout.addWidget(self._detail_label)

        self._match_caption = QLabel("Top spectral matches")
        self._match_caption.setStyleSheet("font-size: 9pt; color: #555;")
        layout.addWidget(self._match_caption)

        self._match_list = QListWidget()
        self._match_list.currentRowChanged.connect(self._on_match_row_changed)
        layout.addWidget(self._match_list, stretch=2)

    def clear(self) -> None:
        self._analysis = None
        self._hypothesis_list.clear()
        self._match_list.clear()
        self._status_label.setText("No consensus analysis")
        self._headline_label.setText("Run matching or inspect functional groups to build consensus.")
        self._overview_label.setText("Confirmed, uncertain, and conflicting evidence will appear here.")
        self._detail_label.setText("Select a hypothesis to inspect its evidence.")

    def set_analysis(self, analysis) -> None:
        previous_hypothesis_id = self.current_hypothesis_id()
        previous_match_id = self.current_match_id()
        self._analysis = analysis
        self._hypothesis_list.clear()
        self._match_list.clear()

        if analysis is None:
            self.clear()
            return

        self._status_label.setText(f"Interpretation confidence {analysis.overall_score:.0f}%")
        self._headline_label.setText(analysis.headline)
        self._overview_label.setText(self._format_overview(analysis))

        for hypothesis in analysis.hypotheses:
            item = QListWidgetItem(f"{hypothesis.title}  —  {hypothesis.score:.1f}%")
            item.setData(Qt.ItemDataRole.UserRole, hypothesis)
            item.setForeground(self._score_color(hypothesis.score))
            self._hypothesis_list.addItem(item)

        for match in analysis.top_matches:
            quality = match_quality_label(match.score / 100.0)
            item = QListWidgetItem(f"{match.label}  —  {match.score:.1f}%  ({quality})")
            item.setData(Qt.ItemDataRole.UserRole, match)
            item.setToolTip(match.details)
            self._match_list.addItem(item)

        self._select_hypothesis(previous_hypothesis_id)
        self._select_match(previous_match_id)
        current = self.current_hypothesis()
        self._detail_label.setText(
            self._format_hypothesis_detail(current)
            if current is not None
            else "Select a hypothesis to inspect its evidence."
        )

    def current_hypothesis(self):
        item = self._hypothesis_list.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def current_hypothesis_id(self) -> str | None:
        hypothesis = self.current_hypothesis()
        if hypothesis is None:
            return None
        return str(hypothesis.hypothesis_id)

    def current_match(self):
        item = self._match_list.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def current_match_id(self) -> int | None:
        match = self.current_match()
        if match is None or match.target_id is None:
            return None
        return int(match.target_id)

    def _select_hypothesis(self, hypothesis_id: str | None) -> None:
        if self._hypothesis_list.count() == 0:
            return
        row = 0
        if hypothesis_id is not None:
            row = next(
                (
                    index
                    for index in range(self._hypothesis_list.count())
                    if self._hypothesis_list.item(index).data(Qt.ItemDataRole.UserRole).hypothesis_id
                    == hypothesis_id
                ),
                0,
            )
        blocker = QSignalBlocker(self._hypothesis_list)
        self._hypothesis_list.setCurrentRow(row)
        del blocker

    def _select_match(self, match_id: int | None) -> None:
        if self._match_list.count() == 0:
            return
        if match_id is None:
            blocker = QSignalBlocker(self._match_list)
            self._match_list.setCurrentRow(-1)
            del blocker
            return
        row = next(
            (
                index
                for index in range(self._match_list.count())
                if int(self._match_list.item(index).data(Qt.ItemDataRole.UserRole).target_id)
                == match_id
            ),
            -1,
        )
        blocker = QSignalBlocker(self._match_list)
        self._match_list.setCurrentRow(row)
        del blocker

    def _on_hypothesis_row_changed(self, row: int) -> None:
        if row < 0:
            self._detail_label.setText("Select a hypothesis to inspect its evidence.")
            return
        item = self._hypothesis_list.item(row)
        if item is None:
            return
        hypothesis = item.data(Qt.ItemDataRole.UserRole)
        self._detail_label.setText(self._format_hypothesis_detail(hypothesis))
        self.hypothesis_selected.emit(str(hypothesis.hypothesis_id))

    def _on_match_row_changed(self, row: int) -> None:
        if row < 0:
            return
        item = self._match_list.item(row)
        if item is None:
            return
        match = item.data(Qt.ItemDataRole.UserRole)
        if match.target_id is not None:
            self.match_requested.emit(int(match.target_id))

    def _format_overview(self, analysis) -> str:
        confirmed = ", ".join(evidence.label for evidence in analysis.confirmed_features[:4]) or "none"
        uncertain = ", ".join(evidence.label for evidence in analysis.uncertain_features[:4]) or "none"
        conflicts = ", ".join(evidence.label for evidence in analysis.conflicts[:3]) or "none"
        return (
            f"{analysis.summary}<br><br>"
            f"<b>Confirmed:</b> {confirmed}<br>"
            f"<b>Uncertain:</b> {uncertain}<br>"
            f"<b>Conflicts:</b> {conflicts}"
        )

    def _format_hypothesis_detail(self, hypothesis) -> str:
        supporting = "<br>".join(
            f"• {evidence.label} ({evidence.score:.0f}%) — {evidence.details}"
            for evidence in hypothesis.supporting_evidence[:4]
        ) or "• none"
        conflicts = "<br>".join(
            f"• {evidence.label} — {evidence.details}"
            for evidence in hypothesis.conflicting_evidence[:3]
        ) or "• none"
        checks = "<br>".join(
            f"• {evidence.label} — {evidence.details}"
            for evidence in hypothesis.recommended_checks[:3]
        ) or "• none"
        return (
            f"<b>{hypothesis.title}</b><br>"
            f"{hypothesis.summary}<br><br>"
            f"<b>Supporting evidence</b><br>{supporting}<br><br>"
            f"<b>Conflicts</b><br>{conflicts}<br><br>"
            f"<b>Next checks</b><br>{checks}"
        )

    def _score_color(self, score: float) -> QColor:
        if score >= 70.0:
            return QColor("#1E8449")
        if score >= 45.0:
            return QColor("#AF6E00")
        return QColor("#566573")
