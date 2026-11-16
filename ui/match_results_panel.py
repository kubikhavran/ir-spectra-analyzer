"""
MatchResultsPanel — Panel výsledků spektrálního porovnávání.

Zodpovědnost:
- Zobrazení seřazených výsledků matching (name, score)
- Signal pro výběr kandidáta (pro overlay v SpectrumWidget)
- Signal pro import referenčního spektra z SPA souboru
- Volitelné omezení seznamu na shody s uloženým .irproj projektem
- Náhled struktury molekuly při přejetí myší nad shodou
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QSignalBlocker, QSize, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QHideEvent, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from matching.quality import match_quality_label
from ui import theme
from ui.i18n import tr

SAVED_PROJECT_MARKER = "\U0001f4be"  # floppy disk — match has a saved .irproj
SKELETON_MARKER = "▲"  # ▲ — skeleton agrees markedly better than the whole spectrum
# How far the skeleton score must exceed the overall score to be worth flagging.
SKELETON_LEAD_PP = 10.0

# Hover preview size in logical pixels, and the device ratio its PNG is drawn at.
PREVIEW_DISPLAY_PX = 220


# Column geometry shared by the header row and the row painter.
_SCORE_WIDTH = 118  # percentage + bar
_FP_WIDTH = 64
_ROW_PADDING = 6
_QUALITY_COLORS = {
    "Excellent": theme.QUALITY_EXCELLENT,
    "Strong": theme.QUALITY_STRONG,
    "Possible": theme.QUALITY_POSSIBLE,
}


def quality_color(score: float) -> str:
    """Bar colour for a similarity score — the only place quality is colour-coded."""
    return _QUALITY_COLORS.get(match_quality_label(score), theme.QUALITY_WEAK)


class _MatchRowDelegate(QStyledItemDelegate):
    """Draws a match as a table row: name · score with a bar · skeleton score.

    Rows used to be one sentence coloured by quality; orange and light blue
    text on white was hard to read and the numbers did not line up. Here the
    text is always dark, the numbers sit in columns and the bar carries the
    quality colour.
    """

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        hint = super().sizeHint(option, index)
        return QSize(0, max(hint.height(), 26))

    def paint(self, painter, option, index) -> None:
        result = index.data(256)
        if result is None:
            super().paint(painter, option, index)
            return
        view_option = QStyleOptionViewItem(option)
        self.initStyleOption(view_option, index)
        view_option.text = ""
        if view_option.widget is not None:
            view_option.widget.style().drawControl(
                QStyle.ControlElement.CE_ItemViewItem, view_option, painter, view_option.widget
            )
        selected = bool(view_option.state & QStyle.StateFlag.State_Selected)
        text_color = QColor("#FFFFFF") if selected else QColor(theme.TEXT)
        muted = QColor("#DDE8F3") if selected else QColor(theme.TEXT_MUTED)
        rect: QRect = view_option.rect
        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)

        fp_rect = QRect(
            rect.right() - _FP_WIDTH - _ROW_PADDING, rect.top(), _FP_WIDTH, rect.height()
        )
        score_rect = QRect(fp_rect.left() - _SCORE_WIDTH, rect.top(), _SCORE_WIDTH, rect.height())
        name_rect = QRect(
            rect.left() + _ROW_PADDING,
            rect.top(),
            max(score_rect.left() - rect.left() - 2 * _ROW_PADDING, 10),
            rect.height(),
        )

        score = float(getattr(result, "score", 0.0))
        fingerprint = float(getattr(result, "fingerprint_score", 0.0))
        name = str(index.data(_NAME_ROLE) or getattr(result, "name", ""))
        metrics = painter.fontMetrics()
        painter.setPen(text_color)
        painter.drawText(
            name_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            metrics.elidedText(name, Qt.TextElideMode.ElideRight, name_rect.width()),
        )

        # Score: number, then a bar whose length is the score.
        number_rect = QRect(score_rect.left(), rect.top(), 50, rect.height())
        painter.drawText(
            number_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
            f"{score * 100:.1f}%",
        )
        track = QRect(number_rect.right() + 8, rect.center().y() - 3, 54, 7)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 70) if selected else QColor(theme.HEADER))
        painter.drawRoundedRect(track, 3, 3)
        fill = QRect(track)
        fill.setWidth(max(int(round(track.width() * max(0.0, min(score, 1.0)))), 2))
        painter.setBrush(QColor("#FFFFFF") if selected else QColor(quality_color(score)))
        painter.drawRoundedRect(fill, 3, 3)

        leads = (fingerprint - score) * 100 >= SKELETON_LEAD_PP
        painter.setPen(text_color if leads else muted)
        painter.drawText(
            fp_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
            f"{SKELETON_MARKER if leads else ''}{fingerprint * 100:.0f}%",
        )
        painter.restore()


_NAME_ROLE = 258  # display name of a row, including the saved-project marker


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
        # name -> PNG bytes of its saved structure; supplied by the main window so
        # the panel itself never touches the disk.
        self._structure_provider: Callable[[str], bytes | None] | None = None
        self._preview_popup: QLabel | None = None
        self._preview_name: str = ""
        self._setup_ui()

    def set_structure_preview_provider(
        self, provider: Callable[[str], bytes | None] | None
    ) -> None:
        """Supply the source of structure previews shown on hover.

        Args:
            provider: Callable mapping a match name to PNG bytes, or None when
                that match has no saved structure to show.
        """
        self._structure_provider = provider
        self._hide_structure_preview()

    def name_filter(self) -> str:
        """Return the current name-substring filter for scoping the library search."""
        return str(self._name_filter_edit.text()).strip()

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
        self._status_label = QLabel(tr("No results"))
        self._status_label.setTextFormat(Qt.TextFormat.PlainText)
        self._status_label.setStyleSheet(theme.CAPTION_STYLE)
        self._status_label.setToolTip(
            tr(
                "Similarity score is an internal spectral metric "
                "(coarse cosine search + fine rerank). Not equivalent to OMNIC HQI."
            )
        )
        header.addWidget(self._status_label)
        header.addStretch()
        self._import_btn = QPushButton(tr("Import Reference..."))
        self._import_btn.clicked.connect(self.import_reference)
        header.addWidget(self._import_btn)
        layout.addLayout(header)

        # Name filter: scope Match Spectrum to references whose name contains
        # this text (e.g. a client prefix "NIT"), so a huge library is searched
        # as a small subset. Empty = search everything.
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel(tr("Name filter:")))
        self._name_filter_edit = QLineEdit()
        self._name_filter_edit.setPlaceholderText(
            tr("e.g. NIT — limits Match Spectrum, empty = all")
        )
        self._name_filter_edit.setClearButtonEnabled(True)
        self._name_filter_edit.returnPressed.connect(self.match_requested)
        filter_row.addWidget(self._name_filter_edit)
        layout.addLayout(filter_row)

        # Assignments can only be copied from a match that also exists as a saved
        # .irproj, so allow hiding everything else instead of hunting through the
        # full ranked list.
        self._saved_only_check = QCheckBox(tr("Only matches with a saved project (.irproj)"))
        self._saved_only_check.setToolTip(
            tr(
                "Show only matches that have a saved .irproj in the annotated projects "
                "folder — those are the ones you can apply assignments from"
            )
        )
        self._saved_only_check.toggled.connect(self._on_saved_only_toggled)
        layout.addWidget(self._saved_only_check)

        # Column titles over the list — the rows are painted to the same grid.
        columns = QHBoxLayout()
        columns.setContentsMargins(_ROW_PADDING + 2, 2, _ROW_PADDING + 2, 0)
        columns.setSpacing(0)
        name_title = QLabel(tr("Reference"))
        score_title = QLabel(tr("Match"))
        score_title.setFixedWidth(_SCORE_WIDTH)
        score_title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        score_title.setIndent(20)
        fp_title = QLabel(tr("Skeleton"))
        fp_title.setFixedWidth(_FP_WIDTH)
        fp_title.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        fp_title.setToolTip(
            tr(
                "Similarity over the skeleton region 400–1600 cm⁻¹ only. "
                "▲ marks a skeleton score at least 10 points above the overall one — "
                "typically the same skeleton carrying a different substituent."
            )
        )
        for title in (name_title, score_title, fp_title):
            title.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 9pt; font-weight: 600;")
        columns.addWidget(name_title, 1)
        columns.addWidget(score_title)
        columns.addWidget(fp_title)
        layout.addLayout(columns)

        self._list = QListWidget()
        self._list.setItemDelegate(_MatchRowDelegate(self._list))
        self._list.setAlternatingRowColors(True)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.currentRowChanged.connect(self._on_row_changed)
        # Hovering a candidate shows the structure saved for it, so a long hit
        # list can be scanned for "is this actually the same molecule?" without
        # clicking through every row.
        self._list.setMouseTracking(True)
        self._list.itemEntered.connect(self._on_item_hovered)
        self._list.viewport().installEventFilter(self)
        layout.addWidget(self._list)

        # Which bands the sample and the selected reference do not share — the
        # evidence behind a "same skeleton, different group" reading.
        self._difference_label = QLabel("")
        self._difference_label.setTextFormat(Qt.TextFormat.PlainText)
        self._difference_label.setWordWrap(True)
        self._difference_label.setStyleSheet(theme.CAPTION_STYLE)
        self._difference_label.setToolTip(
            tr("Bands with no counterpart within 8 cm⁻¹ in the other spectrum, strongest first")
        )
        layout.addWidget(self._difference_label)

        # Copy peak assignments + structure from the selected match's saved
        # .irproj (looked up by name in the annotated-projects folder).
        self._apply_btn = QPushButton(tr("Apply assignments from match"))
        self._apply_btn.setProperty("role", "primary")
        self._apply_btn.setToolTip(
            tr(
                "Copy vibration assignments and structure from the selected match's "
                "saved project onto the current spectrum (nearest peaks, blanks only)"
            )
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
        self._hide_structure_preview()
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
            item.setData(_NAME_ROLE, f"{marker}{result.name}")
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
            self._status_label.setText(tr("No results"))
            return
        total = len(self._results)
        n_saved = sum(1 for result in self._results if self.has_saved_project(result))
        if not self._saved_only_check.isChecked():
            self._status_label.setText(
                tr("{total} candidates ({saved} saved)").format(total=total, saved=n_saved)
            )
        elif n_saved:
            self._status_label.setText(
                tr("{saved} of {total} candidates saved").format(total=total, saved=n_saved)
            )
        elif self._saved_project_names:
            self._status_label.setText(
                tr("No saved project among {total} candidates").format(total=total)
            )
        else:
            self._status_label.setText(tr("No annotated projects folder set"))

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

    # ------------------------------------------------------------------
    # Structure preview on hover
    # ------------------------------------------------------------------

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        """Hide the preview as soon as the pointer leaves the list."""
        if event.type() == QEvent.Type.Leave and watched is self._list.viewport():
            self._hide_structure_preview()
        return bool(super().eventFilter(watched, event))

    def hideEvent(self, event: QHideEvent) -> None:  # noqa: N802
        """Never leave a preview floating over the app when the panel goes away."""
        self._hide_structure_preview()
        super().hideEvent(event)

    def _on_item_hovered(self, item: QListWidgetItem) -> None:
        """Show the structure saved for the hovered match, if there is one."""
        if self._structure_provider is None:
            return
        result = item.data(256)
        name = str(getattr(result, "name", "")).strip()
        if not name:
            self._hide_structure_preview()
            return
        if name == self._preview_name and self._preview_popup is not None:
            self._move_preview_to_cursor()
            return

        png = self._structure_provider(name)
        if not png:
            self._hide_structure_preview()
            return
        pixmap = QPixmap()
        if not pixmap.loadFromData(png) or pixmap.isNull():
            self._hide_structure_preview()
            return

        popup = self._ensure_preview_popup()
        popup.setPixmap(
            pixmap.scaled(
                PREVIEW_DISPLAY_PX,
                PREVIEW_DISPLAY_PX,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        popup.adjustSize()
        self._preview_name = name
        self._move_preview_to_cursor()
        popup.show()

    def _ensure_preview_popup(self) -> QLabel:
        """Create the floating preview window on first use."""
        if self._preview_popup is None:
            popup = QLabel(None, Qt.WindowType.ToolTip)
            # Near a screen edge the popup can be nudged under the pointer; if it
            # took mouse events the list would see a Leave and start flickering.
            popup.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            popup.setAlignment(Qt.AlignmentFlag.AlignCenter)
            popup.setStyleSheet(
                "background: white; border: 1px solid #9E9E9E; border-radius: 3px; padding: 4px;"
            )
            self._preview_popup = popup
        return self._preview_popup

    def _move_preview_to_cursor(self) -> None:
        """Place the preview beside the pointer, kept inside the screen."""
        popup = self._preview_popup
        if popup is None:
            return
        position = QCursor.pos() + QPoint(18, 18)
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        if screen is not None:
            bounds = screen.availableGeometry()
            position.setX(min(position.x(), bounds.right() - popup.width()))
            position.setY(min(position.y(), bounds.bottom() - popup.height()))
            position.setX(max(position.x(), bounds.left()))
            position.setY(max(position.y(), bounds.top()))
        popup.move(position)

    def _hide_structure_preview(self) -> None:
        """Take the preview off screen and forget what it was showing."""
        self._preview_name = ""
        if self._preview_popup is not None:
            self._preview_popup.hide()
