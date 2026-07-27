"""
MatchResultsPanel — Panel výsledků spektrálního porovnávání.

Zodpovědnost:
- Zobrazení seřazených výsledků matching (name, score)
- Signal pro výběr kandidáta (pro overlay v SpectrumWidget)
- Signal pro import referenčního spektra z SPA souboru
- Volitelné omezení seznamu na shody s uloženým .irproj projektem
"""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
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

SAVED_PROJECT_MARKER = "\U0001f4be"  # floppy disk — match has a saved .irproj
SKELETON_MARKER = "▲"  # ▲ — skeleton agrees markedly better than the whole spectrum
# How far the skeleton score must exceed the overall score to be worth flagging.
SKELETON_LEAD_PP = 10.0


class MatchResultsPanel(QWidget):
    """Panel showing ranked spectral match results."""

    candidate_selected = Signal(object)  # emits MatchResult on selection change
    import_reference = Signal()  # user clicked "Import Reference..."
    match_requested = Signal()  # user pressed Enter in the name filter
    apply_assignments_requested = Signal(object)  # emits MatchResult to copy assignments from

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._results: list = []  # every result from the last search
        self._visible_results: list = []  # results currently shown in the list
        self._saved_project_names: set[str] = set()  # lowercased .irproj stems
        self._setup_ui()

    def name_filter(self) -> str:
        """Return the current name-substring filter for scoping the library search."""
        return self._name_filter_edit.text().strip()

    def selected_result(self):
        """Return the currently selected MatchResult, or None."""
        row = self._list.currentRow()
        if 0 <= row < len(self._visible_results):
            return self._visible_results[row]
        return None

    def set_saved_project_names(self, names: Iterable[str]) -> None:
        """Tell the panel which match names have a saved .irproj project.

        Names are compared case-insensitively, the same way the annotated
        projects folder is searched when assignments are applied.
        """
        new_names = {str(name).strip().lower() for name in names if str(name).strip()}
        if new_names == self._saved_project_names:
            return
        self._saved_project_names = new_names
        self._rebuild_list()

    def set_band_difference(self, summary: str) -> None:
        """Show the band-level difference against the selected reference."""
        self._difference_label.setText(summary)

    def has_saved_project(self, result) -> bool:
        """Return True when a saved .irproj exists for this match's name."""
        return str(getattr(result, "name", "")).strip().lower() in self._saved_project_names

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

        # Assignments can only be copied from a match that also exists as a saved
        # .irproj, so allow hiding everything else instead of hunting through the
        # full ranked list.
        self._saved_only_check = QCheckBox("Only matches with a saved project (.irproj)")
        self._saved_only_check.setToolTip(
            "Show only matches that have a saved .irproj in the annotated projects "
            "folder — those are the ones you can apply assignments from"
        )
        self._saved_only_check.toggled.connect(self._on_saved_only_toggled)
        layout.addWidget(self._saved_only_check)

        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._on_row_changed)
        layout.addWidget(self._list)

        # Which bands the sample and the selected reference do not share — the
        # evidence behind a "same skeleton, different group" reading.
        self._difference_label = QLabel("")
        self._difference_label.setWordWrap(True)
        self._difference_label.setStyleSheet("color: #444; font-size: 9pt;")
        self._difference_label.setToolTip(
            "Bands with no counterpart within 8 cm⁻¹ in the other spectrum, strongest first"
        )
        layout.addWidget(self._difference_label)

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
        self._rebuild_list()

    def select_result_by_ref_id(self, ref_id: int) -> bool:
        """Select one result by database ID and emit it for overlay refresh."""
        if not any(int(result.ref_id) == int(ref_id) for result in self._results):
            return False
        if not any(int(result.ref_id) == int(ref_id) for result in self._visible_results):
            # The target is hidden by the saved-project filter; drop the filter
            # rather than silently ignoring the request.
            self._saved_only_check.setChecked(False)
        for row, result in enumerate(self._visible_results):
            if int(result.ref_id) != int(ref_id):
                continue
            if self._list.currentRow() == row:
                self.candidate_selected.emit(result)
            else:
                self._list.setCurrentRow(row)
            return True
        return False

    def _rebuild_list(self) -> None:
        """Repopulate the list from the cached results and the current filter."""
        previous = self.selected_result()
        saved_only = self._saved_only_check.isChecked()
        self._visible_results = [
            result for result in self._results if not saved_only or self.has_saved_project(result)
        ]

        blocker = QSignalBlocker(self._list)
        self._list.clear()
        for result in self._visible_results:
            score_pct = result.score * 100
            fingerprint_pct = float(getattr(result, "fingerprint_score", 0.0)) * 100
            quality = match_quality_label(result.score)
            saved = self.has_saved_project(result)
            marker = f"{SAVED_PROJECT_MARKER} " if saved and not saved_only else ""
            # A clearly better skeleton score is the substituent-swap signature,
            # so it is flagged even though the overall score stays modest.
            leads = fingerprint_pct - score_pct >= SKELETON_LEAD_PP
            skeleton = f"   {SKELETON_MARKER if leads else ''}fp {fingerprint_pct:.0f}%"
            item = QListWidgetItem(
                f"{marker}{result.name}  —  {score_pct:.1f}%  ({quality}){skeleton}"
            )
            item.setData(256, result)  # store in UserRole
            item.setForeground(QColor(match_quality_color(result.score)))
            tips = [
                "fp = skeleton region 400–1600 cm⁻¹ only. "
                f"{SKELETON_MARKER} marks a skeleton score at least "
                f"{SKELETON_LEAD_PP:.0f} points above the overall one — typically the "
                "same skeleton carrying a different substituent."
            ]
            if saved:
                tips.append("Saved .irproj found — assignments can be applied from this match")
            item.setToolTip("\n".join(tips))
            self._list.addItem(item)

        row = self._row_for_result(previous)
        self._list.setCurrentRow(row)
        del blocker

        self._update_status_label()
        self._on_row_changed(row)

    def _row_for_result(self, result) -> int:
        """Return the row of a previously selected result, else the first row."""
        if result is not None:
            for row, candidate in enumerate(self._visible_results):
                if int(candidate.ref_id) == int(result.ref_id):
                    return row
        return 0 if self._visible_results else -1

    def _update_status_label(self) -> None:
        """Describe how many candidates are shown and how many are applicable."""
        if not self._results:
            self._status_label.setText("No results")
            return
        n_saved = sum(1 for result in self._results if self.has_saved_project(result))
        if not self._saved_only_check.isChecked():
            self._status_label.setText(f"{len(self._results)} candidates ({n_saved} saved)")
        elif n_saved:
            self._status_label.setText(f"{n_saved} of {len(self._results)} candidates saved")
        elif self._saved_project_names:
            self._status_label.setText(f"No saved project among {len(self._results)} candidates")
        else:
            self._status_label.setText("No annotated projects folder set")

    def _on_saved_only_toggled(self, _checked: bool) -> None:
        self._rebuild_list()

    def _on_row_changed(self, row: int) -> None:
        has_selection = 0 <= row < len(self._visible_results)
        # With no folder configured nothing is known to be saved; keep the button
        # live so clicking it still explains how to point at the folder.
        self._apply_btn.setEnabled(
            has_selection
            and (
                not self._saved_project_names or self.has_saved_project(self._visible_results[row])
            )
        )
        if has_selection:
            self.candidate_selected.emit(self._visible_results[row])

    def _on_apply_clicked(self) -> None:
        result = self.selected_result()
        if result is not None:
            self.apply_assignments_requested.emit(result)
