"""
MatchResultsPanel — Panel výsledků spektrálního porovnávání.

Zodpovědnost:
- Zobrazení seřazených výsledků matching (name, score)
- Signal pro výběr kandidáta (pro overlay v SpectrumWidget)
- Signal pro import referenčního spektra z SPA souboru
"""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from matching.quality import match_quality_color, match_quality_label


class MatchResultsPanel(QWidget):
    """Panel showing ranked spectral match results."""

    candidate_selected = Signal(object)  # emits MatchResult on selection change
    import_reference = Signal()  # user clicked "Import Reference..."
    match_requested = Signal()  # user pressed Enter in the name filter
    apply_assignments_requested = Signal(object)  # emits MatchResult to copy assignments from

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._results: list = []
        self._setup_ui()

    def name_filter(self) -> str:
        """Return the current name-substring filter for scoping the library search."""
        return self._name_filter_edit.text().strip()

    def selected_result(self):
        """Return the currently selected MatchResult, or None."""
        row = self._list.currentRow()
        if 0 <= row < len(self._results):
            return self._results[row]
        return None

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        header = QHBoxLayout()
        self._status_label = QLabel("No results")
        self._status_label.setStyleSheet("color: gray; font-size: 9pt;")
        self._status_label.setToolTip(
            "Similarity score is an internal spectral metric "
            "(coarse cosine search + fine rerank). Not equivalent to OMNIC HQI."
        )
        header.addWidget(self._status_label)
        header.addStretch()
        self._import_btn = QPushButton("Import Reference...")
        self._import_btn.clicked.connect(self.import_reference)
        header.addWidget(self._import_btn)
        layout.addLayout(header)

        # Name filter: scope Match Spectrum to references whose name contains
        # this text (e.g. a client prefix "NIT"), so a huge library is searched
        # as a small subset. Empty = search everything.
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Name filter:"))
        self._name_filter_edit = QLineEdit()
        self._name_filter_edit.setPlaceholderText("e.g. NIT — limits Match Spectrum, empty = all")
        self._name_filter_edit.setClearButtonEnabled(True)
        self._name_filter_edit.returnPressed.connect(self.match_requested)
        filter_row.addWidget(self._name_filter_edit)
        layout.addLayout(filter_row)

        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._on_row_changed)
        layout.addWidget(self._list)

        # Copy peak assignments + structure from the selected match's saved
        # .irproj (looked up by name in the annotated-projects folder).
        self._apply_btn = QPushButton("Apply assignments from match")
        self._apply_btn.setToolTip(
            "Copy vibration assignments and structure from the selected match's "
            "saved project onto the current spectrum (nearest peaks, blanks only)"
        )
        self._apply_btn.setEnabled(False)
        self._apply_btn.clicked.connect(self._on_apply_clicked)
        layout.addWidget(self._apply_btn)

    def set_results(self, results: list) -> None:
        """Populate the panel with MatchResult objects.

        Args:
            results: List of MatchResult objects sorted by score descending.
        """
        self._results = results
        self._list.clear()
        if not results:
            self._status_label.setText("No results")
            self._apply_btn.setEnabled(False)
            return
        self._status_label.setText(f"{len(results)} candidates")
        self._apply_btn.setEnabled(True)
        for result in results:
            score_pct = result.score * 100
            quality = match_quality_label(result.score)
            text = f"{result.name}  —  {score_pct:.1f}%  ({quality})"
            item = QListWidgetItem(text)
            item.setData(256, result)  # store in UserRole
            item.setForeground(QColor(match_quality_color(result.score)))
            self._list.addItem(item)
        blocker = QSignalBlocker(self._list)
        self._list.setCurrentRow(0)
        del blocker
        self.candidate_selected.emit(results[0])

    def select_result_by_ref_id(self, ref_id: int) -> bool:
        """Select one result by database ID and emit it for overlay refresh."""
        for row, result in enumerate(self._results):
            if int(result.ref_id) != int(ref_id):
                continue
            if self._list.currentRow() == row:
                self.candidate_selected.emit(result)
            else:
                self._list.setCurrentRow(row)
            return True
        return False

    def _on_row_changed(self, row: int) -> None:
        has_selection = 0 <= row < len(self._results)
        self._apply_btn.setEnabled(has_selection)
        if has_selection:
            self.candidate_selected.emit(self._results[row])

    def _on_apply_clicked(self) -> None:
        result = self.selected_result()
        if result is not None:
            self.apply_assignments_requested.emit(result)
