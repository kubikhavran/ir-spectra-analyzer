"""
VibrationPanel — Panel předvoleb vibrací.

Zodpovědnost:
- Zobrazení seznamu vibračních předvoleb dle kategorie
- Přiřazení předvolby k vybranému peaku kliknutím
- Filtrování předvoleb dle rozsahu wavenumberů aktivního peaku
- Přidání vlastních vibrací uložených v databázi
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from core.vibration_presets import VibrationPreset
from ui import theme
from ui.i18n import tr
from ui.vibration_text_edit import VibrationTextEdit

if TYPE_CHECKING:
    from core.peak import Peak

_ASSIGN_IDLE_TEXT = "Assign to selected peak"
_BROWSE_HINT = "Click a vibration to see its range in the spectrum"

# Preset categories grouped into the panel's "Protecting groups" section.
_PG_CATEGORIES = {"silyl"}

# ── List arrangement ─────────────────────────────────────────────────────────
#: One flat list ordered by wavenumber — the arrangement the panel always had.
MODE_WAVENUMBER = "wavenumber"
#: Collapsible sections by vibration type, with the vibrations that fit the
#: selected peak gathered on top.
MODE_GROUPED = "grouped"
#: Only the vibrations the groups of the drawn structure can show, one section
#: per group, with those that fit the selected peak on top.
MODE_STRUCTURE = "structure"
_MODES: tuple[tuple[str, str], ...] = (
    (MODE_GROUPED, "Grouped by type"),
    (MODE_WAVENUMBER, "Sorted by wavenumber"),
    (MODE_STRUCTURE, "By the drawn structure"),
)
_ALL_MODES = tuple(mode for mode, _label in _MODES)

# Item data roles: 256 holds the VibrationPreset of a row (None for a header),
# 257 the key of a section header.
_PRESET_ROLE = 256
_SECTION_ROLE = 257
#: Colour swatch of a structure-group section (its lane colour in the plot).
_SECTION_COLOR_ROLE = 258

_SECTION_FITS = "fits"
_SECTION_CUSTOM = "custom"
_SECTION_OTHER = "other"
# (section key, title, preset categories it collects), in display order.
_TYPE_SECTIONS: tuple[tuple[str, str, frozenset[str]], ...] = (
    ("stretch", "Stretching ν", frozenset({"stretch"})),
    ("bend", "Bending δ", frozenset({"bend"})),
    ("oop", "Out-of-plane γ", frozenset({"oop"})),
    ("rock", "Rocking and wagging", frozenset({"rocking", "wagging"})),
    ("overtone", "Overtones and combinations", frozenset({"overtone"})),
    ("silyl", "Protecting groups", frozenset(_PG_CATEGORIES)),
)


def _range_text(preset: VibrationPreset) -> str:
    return f"{preset.typical_range_min:.0f}–{preset.typical_range_max:.0f}"


class _PresetDelegate(QStyledItemDelegate):
    """Draws a vibration as two columns: its name, and its range on the right.

    The row text used to be one string, "name  (min–max cm⁻¹)", so long names
    pushed the range out of view behind a horizontal scrollbar. Here the range
    always stays visible, right-aligned, and the name is elided if it must be.
    """

    _RANGE_WIDTH = 82
    _PADDING = 6

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        hint = super().sizeHint(option, index)
        return QSize(0, max(hint.height(), 23))

    def paint(self, painter, option, index) -> None:
        preset = index.data(_PRESET_ROLE)
        section = index.data(_SECTION_ROLE)
        if preset is None and section is None:
            super().paint(painter, option, index)
            return

        view_option = QStyleOptionViewItem(option)
        self.initStyleOption(view_option, index)
        text = view_option.text
        view_option.text = ""
        style = view_option.widget.style() if view_option.widget is not None else None
        rect: QRect = view_option.rect
        painter.save()

        if preset is None:  # section header
            painter.fillRect(rect, QColor(theme.HEADER))
            font = painter.font()
            font.setBold(True)
            painter.setFont(font)
            text_rect = rect.adjusted(self._PADDING, 0, -self._PADDING, 0)
            swatch = index.data(_SECTION_COLOR_ROLE)
            if swatch:
                side = 10
                top = rect.top() + (rect.height() - side) // 2
                painter.fillRect(
                    QRect(rect.left() + self._PADDING, top, side, side), QColor(swatch)
                )
                text_rect = text_rect.adjusted(side + 6, 0, 0, 0)
            painter.setPen(QColor(theme.TEXT_MUTED))
            painter.drawText(
                text_rect,
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                text,
            )
            painter.restore()
            return

        if style is not None:
            style.drawControl(
                QStyle.ControlElement.CE_ItemViewItem, view_option, painter, view_option.widget
            )
        selected = bool(view_option.state & QStyle.StateFlag.State_Selected)
        name_color = QColor(theme.ON_ACCENT) if selected else QColor(theme.TEXT)
        range_color = QColor(theme.ON_ACCENT_MUTED) if selected else QColor(theme.TEXT_MUTED)
        if not selected and not preset.is_builtin:
            name_color = QColor(theme.ACCENT_DARK)

        range_rect = QRect(
            rect.right() - self._RANGE_WIDTH - self._PADDING,
            rect.top(),
            self._RANGE_WIDTH,
            rect.height(),
        )
        name_rect = QRect(
            rect.left() + self._PADDING,
            rect.top(),
            max(range_rect.left() - rect.left() - 2 * self._PADDING, 10),
            rect.height(),
        )
        name = preset.name if preset.is_builtin else f"★ {preset.name}"
        metrics = painter.fontMetrics()
        painter.setPen(name_color)
        painter.drawText(
            name_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            metrics.elidedText(name, Qt.TextElideMode.ElideRight, name_rect.width()),
        )
        painter.setPen(range_color)
        painter.drawText(
            range_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
            _range_text(preset),
        )
        painter.restore()


class VibrationPanel(QWidget):
    """Panel displaying vibration presets for assignment to peaks."""

    preset_selected = Signal(object)  # emits VibrationPreset on double-click
    #: Emits the highlighted VibrationPreset when the user asks for it to be
    #: assigned (the Assign button or Enter). A plain click never assigns — it
    #: only shows where the vibration can appear, so the list can be browsed.
    preset_clicked_for_assign = Signal(object)
    preset_added = Signal()  # emits when a custom preset is saved
    preset_deleted = Signal()  # emits when a preset is deleted (custom) or removed (built-in)
    #: Emits after a preset was edited or the built-in library was reset.
    presets_changed = Signal()
    preset_remove_requested = Signal(object)  # emits VibrationPreset to remove from active peak
    #: Emits the clicked VibrationPreset so its typical window can be outlined in
    #: the spectrum. Separate from the assignment signal: looking up where a
    #: vibration may appear must not depend on a peak being selected.
    preset_range_requested = Signal(object)
    range_visibility_changed = Signal(bool)
    #: Emits MODE_GROUPED / MODE_WAVENUMBER / MODE_STRUCTURE when the user
    #: switches the arrangement.
    view_mode_changed = Signal(str)
    #: The user turned the structure's bands in the spectrum on or off.
    structure_bands_visibility_changed = Signal(bool)

    def __init__(self, db=None, parent=None) -> None:
        super().__init__(parent)
        self._presets: list[VibrationPreset] = []
        self._db = db
        self._active_peak: Peak | None = None
        # The flat wavenumber order is the panel's own default; the main window
        # switches to the grouped arrangement unless the user chose otherwise.
        self._view_mode: str = MODE_WAVENUMBER
        self._collapsed_sections: set[str] = set()
        self._active_wavenumber: float | None = None
        # (group name, preset names) pairs provided by MainWindow from the
        # functional-group knowledge base — used as quick tag filters.
        self._group_tags: list[tuple[str, frozenset[str]]] = []
        # Groups of the drawn structure (chemistry.structure_motifs.FoundMotif).
        self._structure_motifs: list = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self._tag_combo = QComboBox()
        self._tag_combo.addItem(tr("All functional groups"))
        self._tag_combo.setToolTip(
            tr(
                "Show only vibrations diagnostic for one functional group "
                "(e.g. when you already know the molecule contains an acid)"
            )
        )
        self._filter_edit: QLineEdit
        self._tag_combo.currentIndexChanged.connect(
            lambda _index: self._rebuild_list(self._filter_edit.text())
        )
        layout.addWidget(self._tag_combo)

        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText(tr("Filter vibrations…"))
        self._filter_edit.setClearButtonEnabled(True)
        self._filter_edit.textChanged.connect(self._apply_filter)
        layout.addWidget(self._filter_edit)

        self._mode_combo = QComboBox()
        for mode, label in _MODES:
            self._mode_combo.addItem(tr(label), mode)
        self._mode_combo.setCurrentIndex(self._mode_combo.findData(self._view_mode))
        self._mode_combo.setToolTip(
            tr(
                "How the list is arranged: in sections by vibration type, with the "
                "vibrations that fit the selected peak on top; as one list ordered "
                "by wavenumber; or only the vibrations of the groups in the drawn "
                "structure, one section per group."
            )
        )
        self._mode_combo.currentIndexChanged.connect(self._on_mode_selected)
        layout.addWidget(self._mode_combo)

        self._hint_label = QLabel(tr(_BROWSE_HINT))
        self._hint_label.setWordWrap(True)
        self._hint_label.setStyleSheet(theme.CAPTION_STYLE)
        layout.addWidget(self._hint_label)

        self._list = QListWidget()
        self._list.setItemDelegate(_PresetDelegate(self._list))
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setUniformItemSizes(True)
        self._list.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._list.itemClicked.connect(self._on_item_clicked)
        self._list.currentItemChanged.connect(lambda *_: self._update_assign_button())
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self._list)

        # Enter assigns the highlighted vibration, like the button below.
        for key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            shortcut = QShortcut(QKeySequence(key), self._list)
            shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
            shortcut.activated.connect(self._on_assign_clicked)

        # F2 edits the highlighted vibration, as in the reference library.
        edit_shortcut = QShortcut(QKeySequence(Qt.Key.Key_F2), self._list)
        edit_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        edit_shortcut.activated.connect(self._edit_highlighted)

        self._assign_btn = QPushButton(tr(_ASSIGN_IDLE_TEXT))
        self._assign_btn.setProperty("role", "primary")
        self._assign_btn.setEnabled(False)
        self._assign_btn.setToolTip(
            tr(
                "Assign the highlighted vibration to the selected peak.\n"
                "Double-clicking the vibration or pressing Enter does the same."
            )
        )
        self._assign_btn.clicked.connect(self._on_assign_clicked)
        layout.addWidget(self._assign_btn)

        self._show_range_checkbox = QCheckBox(tr("Show vibration range in spectrum"))
        self._show_range_checkbox.setChecked(True)
        self._show_range_checkbox.setToolTip(
            tr(
                "Outline the wavenumber window a clicked vibration can occupy. "
                "Turn off to keep the spectrum clear."
            )
        )
        self._show_range_checkbox.toggled.connect(self.range_visibility_changed.emit)
        layout.addWidget(self._show_range_checkbox)

        self._show_structure_bands_checkbox = QCheckBox(
            tr("Show the structure's bands in spectrum")
        )
        self._show_structure_bands_checkbox.setChecked(True)
        self._show_structure_bands_checkbox.setToolTip(
            tr(
                "Mark where the groups of the drawn structure absorb: one coloured lane "
                "per group at the top of the plot, in the colour of its section here."
            )
        )
        self._show_structure_bands_checkbox.toggled.connect(
            self.structure_bands_visibility_changed.emit
        )
        layout.addWidget(self._show_structure_bands_checkbox)

        add_btn = QPushButton(tr("Add custom vibration…"))
        add_btn.setToolTip(tr("Add a permanent custom vibration entry"))
        add_btn.clicked.connect(self._on_add_custom)
        layout.addWidget(add_btn)

    # ── Arrangement ──────────────────────────────────────────────────────────

    def view_mode(self) -> str:
        """MODE_GROUPED or MODE_WAVENUMBER."""
        return self._view_mode

    def set_view_mode(self, mode: object) -> None:
        """Choose the arrangement without announcing it as a user change."""
        resolved = mode if mode in _ALL_MODES else MODE_GROUPED
        if resolved == self._view_mode:
            return
        self._view_mode = str(resolved)
        blocked = self._mode_combo.blockSignals(True)
        try:
            self._mode_combo.setCurrentIndex(self._mode_combo.findData(self._view_mode))
        finally:
            self._mode_combo.blockSignals(blocked)
        self._rebuild_list(self._filter_edit.text())
        self._reapply_peak_highlight()

    def _on_mode_selected(self, index: int) -> None:
        mode = self._mode_combo.itemData(index)
        if mode not in _ALL_MODES or mode == self._view_mode:
            return
        self._view_mode = str(mode)
        self._rebuild_list(self._filter_edit.text())
        self._reapply_peak_highlight()
        self.view_mode_changed.emit(self._view_mode)

    def preset_rows(self) -> list[int]:
        """Rows of the list that hold a vibration (section headers left out)."""
        return [
            row
            for row in range(self._list.count())
            if self._list.item(row).data(_PRESET_ROLE) is not None
        ]

    def first_preset_item(self) -> QListWidgetItem | None:
        """The first vibration row, whatever headers come before it."""
        rows = self.preset_rows()
        return self._list.item(rows[0]) if rows else None

    def set_db(self, db) -> None:
        """Set the database reference (for saving custom presets)."""
        self._db = db

    def set_active_peak(self, peak: Peak | None) -> None:
        """Track the currently active peak for assignment and the context menu."""
        self._active_peak = peak
        self._update_assign_button()

    def clear_peak_context(self) -> None:
        """Clear active-peak hint and remove range highlighting."""
        self._active_peak = None
        self._active_wavenumber = None
        self._hint_label.setText(tr(_BROWSE_HINT))
        self._rebuild_list(self._filter_edit.text())
        self._update_assign_button()

    def set_functional_group_tags(self, tags: list[tuple[str, frozenset[str]]]) -> None:
        """Populate the functional-group tag filter (name, preset-name set) pairs."""
        self._group_tags = list(tags)
        current = self._tag_combo.currentText()
        self._tag_combo.blockSignals(True)
        self._tag_combo.clear()
        self._tag_combo.addItem(tr("All functional groups"))
        for name, _preset_names in self._group_tags:
            self._tag_combo.addItem(name)
        index = self._tag_combo.findText(current)
        self._tag_combo.setCurrentIndex(index if index >= 0 else 0)
        self._tag_combo.blockSignals(False)
        self._rebuild_list(self._filter_edit.text())

    def _active_tag_preset_names(self) -> frozenset[str] | None:
        """Return the preset-name set of the selected tag, or None for 'All'."""
        index = int(self._tag_combo.currentIndex()) - 1
        if 0 <= index < len(self._group_tags):
            return self._group_tags[index][1]
        return None

    def set_structure_motifs(self, found: list) -> None:
        """The groups of the drawn structure (an empty list when there is none)."""
        self._structure_motifs = list(found)
        if self._view_mode == MODE_STRUCTURE:
            self._rebuild_list(self._filter_edit.text())
            self._reapply_peak_highlight()

    def structure_motifs(self) -> list:
        return list(self._structure_motifs)

    def show_structure_bands(self) -> bool:
        return bool(self._show_structure_bands_checkbox.isChecked())

    def set_presets(self, presets: list[VibrationPreset]) -> None:
        self._presets = presets
        self._rebuild_list(self._filter_edit.text())

    def highlight_for_peak(self, wavenumber: float) -> None:
        self._active_wavenumber = float(wavenumber)
        self._rebuild_list(self._filter_edit.text())
        self._hint_label.setText(
            tr("Active peak: {position} cm\u207b\u00b9 \u00b7 double-click to assign").format(
                position=f"{wavenumber:.0f}"
            )
        )
        self._reapply_peak_highlight()

    def _reapply_peak_highlight(self) -> None:
        """Tint every vibration whose range covers the active peak."""
        wavenumber = self._active_wavenumber
        for i in range(self._list.count()):
            item = self._list.item(i)
            preset = item.data(_PRESET_ROLE)
            if preset is None:
                continue  # section header — leave its styling untouched
            if wavenumber is not None and preset.covers_wavenumber(wavenumber):
                item.setBackground(QColor(theme.MATCH_HIGHLIGHT))
                item.setForeground(QColor(theme.TEXT))
            else:
                item.setBackground(QBrush())
                item.setForeground(QBrush())

    def _add_section_header(self, key: str, title: str, count: int) -> bool:
        """Append one clickable section header; returns False when it is collapsed."""
        collapsed = key in self._collapsed_sections
        arrow = "\u25b8" if collapsed else "\u25be"
        header = QListWidgetItem(f"{arrow} {title}  ({count})")
        header.setData(_SECTION_ROLE, key)
        # Enabled but not selectable: a click folds the section, it never
        # becomes the "highlighted vibration".
        header.setFlags(Qt.ItemFlag.ItemIsEnabled)
        header.setToolTip(tr("Click to fold or unfold this section"))
        self._list.addItem(header)
        return not collapsed

    def _grouped_sections(
        self, presets: list[VibrationPreset]
    ) -> list[tuple[str, str, list[VibrationPreset]]]:
        """Split presets into (key, title, members) sections for the grouped view."""
        remaining = list(presets)
        sections: list[tuple[str, str, list[VibrationPreset]]] = []

        wavenumber = self._active_wavenumber
        if wavenumber is not None:
            fitting = [preset for preset in remaining if preset.covers_wavenumber(wavenumber)]
            if fitting:
                # Narrowest range first: the most specific candidates lead.
                fitting.sort(key=lambda p: p.typical_range_max - p.typical_range_min)
                title = tr("Fits peak {position} cm\u207b\u00b9").format(
                    position=f"{wavenumber:.0f}"
                )
                sections.append((_SECTION_FITS, title, fitting))
                remaining = [p for p in remaining if not any(p is f for f in fitting)]

        custom = [preset for preset in remaining if not preset.is_builtin]
        if custom:
            sections.append((_SECTION_CUSTOM, tr("Custom vibrations"), custom))
            remaining = [preset for preset in remaining if preset.is_builtin]

        for key, title, categories in _TYPE_SECTIONS:
            members = [preset for preset in remaining if preset.category in categories]
            if members:
                sections.append((key, tr(title), members))
                remaining = [preset for preset in remaining if preset.category not in categories]
        if remaining:
            sections.append((_SECTION_OTHER, tr("Other"), remaining))
        return sections

    def _rebuild_list(self, filter_text: str = "") -> None:
        # Preserve the scroll position and selection so a rebuild (highlight
        # refresh, assignment refresh, ...) does not yank the list away from
        # where the user was browsing. The top visible preset is remembered by
        # identity and scrolled back into place after the rebuild.
        scrollbar = self._list.verticalScrollBar()
        scroll_value = scrollbar.value()
        top_item = self._list.itemAt(2, 2)
        top_preset = top_item.data(_PRESET_ROLE) if top_item is not None else None
        current_item = self._list.currentItem()
        current_preset = current_item.data(_PRESET_ROLE) if current_item is not None else None

        self._list.clear()
        needle = filter_text.strip().lower()
        tag_names = self._active_tag_preset_names()

        def _passes(preset) -> bool:
            if tag_names is not None and not preset.answers_to(tag_names):
                return False
            # Same separators as the visible row text, plus a plain hyphen, so a
            # range can be searched the way it is read ("1700-1750").
            label = (
                f"{preset.name} ({preset.typical_range_min:.0f}\u2013{preset.typical_range_max:.0f}"
                f" {preset.typical_range_min:.0f}-{preset.typical_range_max:.0f})"
            )
            return not needle or needle in label.lower()

        def _add_preset(preset) -> None:
            # The text is what tests and screen readers see; the delegate draws
            # the same content as two columns.
            label = f"{preset.name}  ({_range_text(preset)} cm\u207b\u00b9)"
            if not preset.is_builtin:
                label = f"\u2605 {label}"
            item = QListWidgetItem(label)
            item.setData(_PRESET_ROLE, preset)
            item.setToolTip(label)
            self._list.addItem(item)

        passing = [p for p in self._presets if _passes(p)]
        if self._view_mode == MODE_STRUCTURE:
            self._add_structure_sections(passing, _add_preset)
        elif self._view_mode == MODE_GROUPED:
            for key, title, members in self._grouped_sections(passing):
                if self._add_section_header(key, title, len(members)):
                    for preset in members:
                        _add_preset(preset)
        else:
            general = [p for p in passing if p.category not in _PG_CATEGORIES]
            protecting = [p for p in passing if p.category in _PG_CATEGORIES]
            for preset in general:
                _add_preset(preset)
            if protecting:
                header = QListWidgetItem(f"\u2500\u2500 {tr('Protecting groups')} \u2500\u2500")
                header.setFlags(Qt.ItemFlag.NoItemFlags)  # non-selectable, no preset data
                header.setForeground(QColor(theme.TEXT_FAINT))
                self._list.addItem(header)
                for preset in protecting:
                    _add_preset(preset)

        if current_preset is not None:
            for i in range(self._list.count()):
                if self._list.item(i).data(_PRESET_ROLE) is current_preset:
                    self._list.setCurrentRow(i)
                    break
        restored = False
        if top_preset is not None:
            from PySide6.QtWidgets import QAbstractItemView  # noqa: PLC0415

            for i in range(self._list.count()):
                if self._list.item(i).data(_PRESET_ROLE) is top_preset:
                    self._list.scrollToItem(
                        self._list.item(i),
                        QAbstractItemView.ScrollHint.PositionAtTop,
                    )
                    restored = True
                    break
        if not restored:
            scrollbar.setValue(min(scroll_value, scrollbar.maximum()))
        self._update_assign_button()

    def _add_structure_sections(self, passing: list[VibrationPreset], add_preset) -> None:
        """One section per group of the drawn structure; fitting ones on top."""
        from ui.structure_bands import motif_colors, presets_for  # noqa: PLC0415

        if not self._structure_motifs:
            hint = QListWidgetItem(
                tr(
                    "Draw a structure in the Structure panel to see only the vibrations "
                    "of its groups here."
                )
            )
            hint.setFlags(Qt.ItemFlag.NoItemFlags)
            hint.setForeground(QColor(theme.TEXT_MUTED))
            self._list.addItem(hint)
            return
        passing_ids = {id(p) for p in passing}
        colors = motif_colors(self._structure_motifs)
        sections: list[tuple[str, str, list[VibrationPreset], str | None]] = []
        for found in self._structure_motifs:
            members = [p for p in presets_for(found, self._presets) if id(p) in passing_ids]
            if not members:
                continue
            title = tr(found.name) + (f"  · {found.count}×" if found.count > 1 else "")
            sections.append((f"motif:{found.id}", title, members, colors.get(found.id)))

        wavenumber = self._active_wavenumber
        if wavenumber is not None:
            fitting: list[VibrationPreset] = []
            for _key, _title, members, _color in sections:
                for preset in members:
                    if preset.covers_wavenumber(wavenumber) and not any(
                        preset is f for f in fitting
                    ):
                        fitting.append(preset)
            if fitting:
                fitting.sort(key=lambda p: p.typical_range_max - p.typical_range_min)
                title = tr("Fits peak {position} cm⁻¹").format(position=f"{wavenumber:.0f}")
                sections.insert(0, (_SECTION_FITS, title, fitting, None))

        for key, title, members, color in sections:
            expanded = self._add_section_header(key, title, len(members))
            if color is not None:
                header = self._list.item(self._list.count() - 1)
                header.setData(_SECTION_COLOR_ROLE, color)
            if expanded:
                for preset in members:
                    add_preset(preset)

    def _apply_filter(self, text: str) -> None:
        self._rebuild_list(text)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        """A click only looks: outline where the vibration can appear.

        It used to assign as well, so the list could not be browsed while a
        peak was selected without writing an assignment on every click.
        """
        section = item.data(_SECTION_ROLE)
        if section is not None:
            # A section header: fold or unfold it.
            if section in self._collapsed_sections:
                self._collapsed_sections.discard(section)
            else:
                self._collapsed_sections.add(section)
            self._rebuild_list(self._filter_edit.text())
            self._reapply_peak_highlight()
            return
        preset = item.data(_PRESET_ROLE)
        if preset is not None:
            self.preset_range_requested.emit(preset)

    def _highlighted_preset(self) -> VibrationPreset | None:
        item = self._list.currentItem()
        preset = item.data(_PRESET_ROLE) if item is not None else None
        return preset if isinstance(preset, VibrationPreset) else None

    def _on_assign_clicked(self) -> None:
        preset = self._highlighted_preset()
        if preset is not None:
            self.preset_clicked_for_assign.emit(preset)

    def _update_assign_button(self) -> None:
        """Say what the Assign button would do, and enable it only when it can."""
        button = getattr(self, "_assign_btn", None)
        if button is None:  # still building the UI
            return
        peak = self._active_peak
        if peak is None:
            button.setText(tr(_ASSIGN_IDLE_TEXT))
            button.setEnabled(False)
            return
        button.setText(
            tr("Assign to peak {position} cm\u207b\u00b9").format(position=f"{peak.position:.0f}")
        )
        button.setEnabled(self._highlighted_preset() is not None)

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        preset = item.data(_PRESET_ROLE)
        if preset is not None:
            self.preset_selected.emit(preset)

    def _on_context_menu(self, pos) -> None:
        item = self._list.itemAt(pos)
        preset = item.data(_PRESET_ROLE) if item is not None else None
        menu = QMenu(self)
        edit_action = delete_action = remove_action = None
        if preset is not None:
            edit_action = menu.addAction(
                tr("Edit \u201c{name}\u201d\u2026").format(name=preset.name)
            )
            edit_action.setShortcut(QKeySequence(Qt.Key.Key_F2))
            delete_action = menu.addAction(tr("Delete \u201c{name}\u201d").format(name=preset.name))
            # Remove assignment from active peak
            if (
                self._active_peak is not None
                and preset.db_id is not None
                and preset.db_id in self._active_peak.vibration_ids
            ):
                remove_action = menu.addAction(
                    tr("Remove from peak {wavenumber} cm\u207b\u00b9").format(
                        wavenumber=int(round(self._active_peak.position))
                    )
                )
            menu.addSeparator()
        reset_action = menu.addAction(tr("Reset built-in vibrations to defaults\u2026"))
        reset_action.setEnabled(self._db is not None)
        action = menu.exec(self._list.mapToGlobal(pos))
        if action is None:
            return
        if action == edit_action:
            self.edit_preset(preset)
        elif action == delete_action:
            self.delete_preset(preset)
        elif action == remove_action:
            self.preset_remove_requested.emit(preset)
        elif action == reset_action:
            self.reset_builtin_presets()

    # ── Editing the library ──────────────────────────────────────────────────

    def _edit_highlighted(self) -> None:
        preset = self._highlighted_preset()
        if preset is not None:
            self.edit_preset(preset)

    def edit_preset(self, preset: VibrationPreset) -> bool:
        """Open the editor for one vibration (built-in or custom). True when saved."""
        if self._db is None or preset.db_id is None:
            return False
        dialog = _VibrationEditorDialog(self, preset=preset)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        values = dialog.values()
        if not values.name:
            return False
        self._db.update_vibration_preset(
            preset.db_id,
            name=values.name,
            range_min=values.range_min,
            range_max=values.range_max,
            category=values.category,
            description=values.description,
        )
        self.presets_changed.emit()
        return True

    def delete_preset(self, preset: VibrationPreset) -> bool:
        """Remove one vibration after a confirmation. True when it was removed.

        A custom vibration is deleted for good; a built-in one only disappears
        from the list and comes back with "Reset built-in vibrations".
        Assignments already written on peaks keep their text either way.
        """
        if self._db is None or preset.db_id is None:
            return False
        if preset.is_builtin:
            detail = tr(
                "It can be brought back with \u201cReset built-in vibrations to defaults\u201d."
            )
        else:
            detail = tr("A custom vibration cannot be brought back.")
        answer = QMessageBox.question(
            self,
            tr("Delete Vibration"),
            tr("Delete \u201c{name}\u201d from the list?").format(name=preset.name)
            + "\n\n"
            + detail
            + "\n"
            + tr("Peaks that already carry it keep their assignment."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False
        self._db.delete_vibration_preset(preset.db_id)
        self.preset_deleted.emit()
        return True

    def reset_builtin_presets(self) -> bool:
        """Restore the built-in library after a confirmation. True when it ran."""
        if self._db is None:
            return False
        answer = QMessageBox.question(
            self,
            tr("Reset Built-in Vibrations"),
            tr(
                "Restore every built-in vibration to its original name, range and "
                "category, and bring back the ones that were deleted?\n\n"
                "Custom vibrations are not changed."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False
        self._db.reset_builtin_vibration_presets()
        self.presets_changed.emit()
        return True

    def _on_add_custom(self) -> None:
        if self._db is None:
            return
        dlg = _VibrationEditorDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            values = dlg.values()
            if values.name:
                self._db.add_vibration_preset(
                    name=values.name,
                    range_min=values.range_min,
                    range_max=values.range_max,
                    category=values.category,
                    description=values.description,
                )
                self.preset_added.emit()


@dataclass(frozen=True)
class VibrationValues:
    """What the vibration editor returns."""

    name: str
    range_min: float
    range_max: float
    category: str
    description: str


#: Categories offered in the editor: (stored value, section title). The stored
#: values are the ones the built-in library uses, so an edited entry lands in
#: the same section of the grouped list as its siblings.
_CATEGORY_CHOICES: tuple[tuple[str, str], ...] = (
    ("stretch", "Stretching \u03bd"),
    ("bend", "Bending \u03b4"),
    ("oop", "Out-of-plane \u03b3"),
    ("rocking", "Rocking \u03c1"),
    ("wagging", "Wagging \u03c9"),
    ("overtone", "Overtones and combinations"),
    ("silyl", "Protecting groups"),
    ("", "Other"),
)


class _VibrationEditorDialog(QDialog):
    """Add a custom vibration, or edit any vibration — built-in or custom."""

    def __init__(self, parent=None, *, preset: VibrationPreset | None = None) -> None:
        super().__init__(parent)
        self._preset = preset
        if preset is None:
            self.setWindowTitle(tr("Add Custom Vibration"))
        else:
            self.setWindowTitle(tr("Edit Vibration"))
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._name_edit = VibrationTextEdit(self)
        self._name_edit.set_placeholder_text("e.g. \u03bd(C=O) \u2013CO\u2013O\u2013")
        form.addRow(tr("Label:"), self._name_edit)

        self._rmin_spin = QDoubleSpinBox()
        self._rmin_spin.setRange(0.0, 15000.0)
        self._rmin_spin.setDecimals(0)
        self._rmin_spin.setSuffix(" cm\u207b\u00b9")
        self._rmin_spin.setValue(1000.0)
        form.addRow(tr("Range min:"), self._rmin_spin)

        self._rmax_spin = QDoubleSpinBox()
        self._rmax_spin.setRange(0.0, 15000.0)
        self._rmax_spin.setDecimals(0)
        self._rmax_spin.setSuffix(" cm\u207b\u00b9")
        self._rmax_spin.setValue(1200.0)
        form.addRow(tr("Range max:"), self._rmax_spin)

        self._category_combo = QComboBox()
        for value, title in _CATEGORY_CHOICES:
            self._category_combo.addItem(tr(title), value)
        self._category_combo.setToolTip(
            tr("Section of the vibration list the entry appears in when grouped by type")
        )
        form.addRow(tr("Category:"), self._category_combo)

        self._description_edit = QLineEdit()
        self._description_edit.setPlaceholderText(tr("optional note, e.g. a literature source"))
        form.addRow(tr("Note:"), self._description_edit)

        if preset is not None:
            self._name_edit.set_text(preset.name)
            low, high = sorted((float(preset.typical_range_min), float(preset.typical_range_max)))
            self._rmin_spin.setValue(low)
            self._rmax_spin.setValue(high)
            index = self._category_combo.findData(preset.category)
            if index < 0:
                # A category this dialog does not list is kept as it is.
                self._category_combo.addItem(preset.category, preset.category)
                index = self._category_combo.count() - 1
            self._category_combo.setCurrentIndex(index)
            self._description_edit.setText(preset.description)
            if preset.is_builtin and preset.catalog_name != preset.name:
                note = QLabel(
                    tr("Built-in vibration, originally \u201c{name}\u201d").format(
                        name=preset.catalog_name
                    )
                )
                note.setWordWrap(True)
                note.setStyleSheet(theme.CAPTION_STYLE)
                form.addRow("", note)
        else:
            self._category_combo.setCurrentIndex(self._category_combo.findData(""))

        # Keep the interval valid while it is edited instead of accepting an
        # inverted range that can never match a peak.
        self._rmin_spin.valueChanged.connect(self._rmax_spin.setMinimum)
        self._rmax_spin.valueChanged.connect(self._rmin_spin.setMaximum)
        self._rmax_spin.setMinimum(self._rmin_spin.value())
        self._rmin_spin.setMaximum(self._rmax_spin.value())

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> VibrationValues:
        return VibrationValues(
            name=self._name_edit.text().strip(),
            range_min=float(self._rmin_spin.value()),
            range_max=float(self._rmax_spin.value()),
            category=str(self._category_combo.currentData() or ""),
            description=self._description_edit.text().strip(),
        )

    def get_values(self) -> tuple[str, float, float]:
        """Name and range only — kept for callers written for the old add dialog."""
        values = self.values()
        return values.name, values.range_min, values.range_max


#: The add dialog grew into the editor; the old name keeps existing imports working.
_AddVibrationDialog = _VibrationEditorDialog
