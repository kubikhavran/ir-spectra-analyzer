"""
MatchResultsPanel — Panel výsledků spektrálního porovnávání.

Zodpovědnost:
- Zobrazení seřazených výsledků matching (name, score)
- Signal pro výběr kandidáta (pro overlay v SpectrumWidget)
- Signal pro import referenčního spektra z SPA souboru
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class MatchResultsPanel(QWidget):
    """Panel showing ranked spectral match results."""

    candidate_selected = Signal(object)  # emits MatchResult on selection change
    import_reference = Signal()  # user clicked "Import Reference..."

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._results: list = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        header = QHBoxLayout()
        self._status_label = QLabel("No results")
        self._status_label.setStyleSheet("color: gray; font-size: 9pt;")
        header.addWidget(self._status_label)
        header.addStretch()
        self._import_btn = QPushButton("Import Reference...")
        self._import_btn.clicked.connect(self.import_reference)
        header.addWidget(self._import_btn)
        layout.addLayout(header)

        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._on_row_changed)
        layout.addWidget(self._list)

    def set_results(self, results: list) -> None:
        """Populate the panel with MatchResult objects.

        Args:
            results: List of MatchResult objects sorted by score descending.
        """
        self._results = results
        self._list.clear()
        if not results:
            self._status_label.setText("No results")
            return
        self._status_label.setText(f"{len(results)} candidates")
        for result in results:
            score_pct = result.score * 100
            text = f"{result.name}  —  {score_pct:.1f}%"
            item = QListWidgetItem(text)
            item.setData(256, result)  # store in UserRole
            if score_pct >= 90:
                item.setForeground(
                    __import__("PySide6.QtGui", fromlist=["QColor"]).QColor("#2E7D32")
                )
            elif score_pct >= 70:
                item.setForeground(
                    __import__("PySide6.QtGui", fromlist=["QColor"]).QColor("#E65100")
                )
            self._list.addItem(item)

    def _on_row_changed(self, row: int) -> None:
        if 0 <= row < len(self._results):
            self.candidate_selected.emit(self._results[row])
