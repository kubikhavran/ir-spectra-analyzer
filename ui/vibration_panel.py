"""
VibrationPanel — Panel předvoleb vibrací.

Zodpovědnost:
- Zobrazení seznamu vibračních předvoleb dle kategorie
- Přiřazení předvolby k vybranému peaku kliknutím
- Filtrování předvoleb dle rozsahu wavenumberů aktivního peaku
- Přidání vlastních vibrací uložených v databázi
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
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
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.vibration_presets import VibrationPreset
from ui.vibration_text_edit import VibrationTextEdit

if TYPE_CHECKING:
    from core.peak import Peak

# Preset categories grouped into the panel's "Protecting groups" section.
_PG_CATEGORIES = {"silyl"}


class VibrationPanel(QWidget):
    """Panel displaying vibration presets for assignment to peaks."""

    preset_selected = Signal(object)  # emits VibrationPreset on double-click
    preset_clicked_for_assign = Signal(object)  # emits VibrationPreset on single-click
    preset_added = Signal()  # emits when a custom preset is saved
    preset_deleted = Signal()  # emits when a custom preset is deleted
    preset_remove_requested = Signal(object)  # emits VibrationPreset to remove from active peak

    def __init__(self, db=None, parent=None) -> None:
        super().__init__(parent)
        self._presets: list[VibrationPreset] = []
        self._db = db
        self._active_peak: Peak | None = None
        # (group name, preset names) pairs provided by MainWindow from the
        # functional-group knowledge base — used as quick tag filters.
        self._group_tags: list[tuple[str, frozenset[str]]] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self._tag_combo = QComboBox()
        self._tag_combo.addItem("All functional groups")
        self._tag_combo.setToolTip(
            "Show only vibrations diagnostic for one functional group "
            "(e.g. when you already know the molecule contains an acid)"
        )
        self._filter_edit: QLineEdit
        self._tag_combo.currentIndexChanged.connect(
            lambda _index: self._rebuild_list(self._filter_edit.text())
        )
        layout.addWidget(self._tag_combo)

        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Filter vibrations…")
        self._filter_edit.textChanged.connect(self._apply_filter)
        layout.addWidget(self._filter_edit)

        self._hint_label = QLabel("")
        self._hint_label.setStyleSheet("color: gray; font-size: 9pt;")
        layout.addWidget(self._hint_label)

        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._list.itemClicked.connect(self._on_item_clicked)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self._list)

        add_btn = QPushButton("Add custom vibration…")
        add_btn.setToolTip("Add a permanent custom vibration entry")
        add_btn.clicked.connect(self._on_add_custom)
        layout.addWidget(add_btn)

    def set_db(self, db) -> None:
        """Set the database reference (for saving custom presets)."""
        self._db = db

    def set_active_peak(self, peak: Peak | None) -> None:
        """Track the currently active peak for context menu remove action."""
        self._active_peak = peak

    def clear_peak_context(self) -> None:
        """Clear active-peak hint and remove range highlighting."""
        self._active_peak = None
        self._hint_label.setText("")
        self._rebuild_list(self._filter_edit.text())

    def set_functional_group_tags(self, tags: list[tuple[str, frozenset[str]]]) -> None:
        """Populate the functional-group tag filter (name, preset-name set) pairs."""
        self._group_tags = list(tags)
        current = self._tag_combo.currentText()
        self._tag_combo.blockSignals(True)
        self._tag_combo.clear()
        self._tag_combo.addItem("All functional groups")
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

    def set_presets(self, presets: list[VibrationPreset]) -> None:
        self._presets = presets
        self._rebuild_list(self._filter_edit.text())

    def highlight_for_peak(self, wavenumber: float) -> None:
        self._rebuild_list(self._filter_edit.text())
        self._hint_label.setText(f"Active peak: {wavenumber:.0f} cm\u207b\u00b9")
        for i in range(self._list.count()):
            item = self._list.item(i)
            preset = item.data(256)
            if preset is None:
                continue  # section header — leave its styling untouched
            if preset.covers_wavenumber(wavenumber):
                item.setBackground(QColor("#C8E6C9"))
                item.setForeground(QColor("#000000"))
            else:
                item.setBackground(QBrush())
                item.setForeground(QBrush())

    def _rebuild_list(self, filter_text: str = "") -> None:
        # Preserve the scroll position and selection so a rebuild (highlight
        # refresh, assignment refresh, ...) does not yank the list away from
        # where the user was browsing. The top visible preset is remembered by
        # identity and scrolled back into place after the rebuild.
        scrollbar = self._list.verticalScrollBar()
        scroll_value = scrollbar.value()
        top_item = self._list.itemAt(2, 2)
        top_preset = top_item.data(256) if top_item is not None else None
        current_item = self._list.currentItem()
        current_preset = current_item.data(256) if current_item is not None else None

        self._list.clear()
        needle = filter_text.strip().lower()
        tag_names = self._active_tag_preset_names()

        def _passes(preset) -> bool:
            if tag_names is not None and preset.name not in tag_names:
                return False
            label = f"{preset.name} ({preset.typical_range_min:.0f}{preset.typical_range_max:.0f})"
            return not needle or needle in label.lower()

        general = [p for p in self._presets if _passes(p) and p.category not in _PG_CATEGORIES]
        protecting = [p for p in self._presets if _passes(p) and p.category in _PG_CATEGORIES]

        def _add_preset(preset) -> None:
            label = (
                f"{preset.name}  "
                f"({preset.typical_range_min:.0f}\u2013{preset.typical_range_max:.0f} cm\u207b\u00b9)"
            )
            if not preset.is_builtin:
                label = f"\u2605 {label}"
            item = QListWidgetItem(label)
            item.setData(256, preset)
            if not preset.is_builtin:
                item.setForeground(QColor("#1A5276"))  # dark blue for custom
            self._list.addItem(item)

        for preset in general:
            _add_preset(preset)

        if protecting:
            header = QListWidgetItem("\u2500\u2500 Protecting groups \u2500\u2500")
            header.setFlags(Qt.ItemFlag.NoItemFlags)  # non-selectable, no preset data
            header.setForeground(QColor("#7F8C8D"))
            self._list.addItem(header)
            for preset in protecting:
                _add_preset(preset)

        if current_preset is not None:
            for i in range(self._list.count()):
                if self._list.item(i).data(256) is current_preset:
                    self._list.setCurrentRow(i)
                    break
        restored = False
        if top_preset is not None:
            from PySide6.QtWidgets import QAbstractItemView  # noqa: PLC0415

            for i in range(self._list.count()):
                if self._list.item(i).data(256) is top_preset:
                    self._list.scrollToItem(
                        self._list.item(i),
                        QAbstractItemView.ScrollHint.PositionAtTop,
                    )
                    restored = True
                    break
        if not restored:
            scrollbar.setValue(min(scroll_value, scrollbar.maximum()))

    def _apply_filter(self, text: str) -> None:
        self._rebuild_list(text)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        preset = item.data(256)
        if preset is not None:
            self.preset_clicked_for_assign.emit(preset)

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        preset = item.data(256)
        if preset is not None:
            self.preset_selected.emit(preset)

    def _on_context_menu(self, pos) -> None:
        item = self._list.itemAt(pos)
        if item is None:
            return
        preset = item.data(256)
        if preset is None:
            return
        menu = QMenu(self)
        # Delete custom preset (only for non-builtin presets)
        if not preset.is_builtin:
            delete_action = menu.addAction(f"Delete \u201c{preset.name}\u201d")
        else:
            delete_action = None
        # Remove assignment from active peak
        remove_action = None
        if (
            self._active_peak is not None
            and preset.db_id is not None
            and preset.db_id in self._active_peak.vibration_ids
        ):
            remove_action = menu.addAction(
                f"Remove from peak {int(round(self._active_peak.position))} cm\u207b\u00b9"
            )
        if not menu.actions():
            return
        action = menu.exec(self._list.mapToGlobal(pos))
        if delete_action and action == delete_action and self._db is not None:
            self._db.delete_vibration_preset(preset.db_id)
            self.preset_deleted.emit()
        elif remove_action and action == remove_action:
            self.preset_remove_requested.emit(preset)

    def _on_add_custom(self) -> None:
        if self._db is None:
            return
        dlg = _AddVibrationDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            name, rmin, rmax = dlg.get_values()
            if name.strip():
                self._db.add_vibration_preset(
                    name=name.strip(),
                    range_min=rmin,
                    range_max=rmax,
                )
                self.preset_added.emit()


class _AddVibrationDialog(QDialog):
    """Simple dialog for adding a custom vibration preset."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Custom Vibration")
        self.setMinimumWidth(340)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._name_edit = VibrationTextEdit(self)
        self._name_edit.set_placeholder_text("e.g. \u03bd(C=O) \u2013CO\u2013O\u2013")
        form.addRow("Label:", self._name_edit)

        self._rmin_spin = QDoubleSpinBox()
        self._rmin_spin.setRange(400.0, 4000.0)
        self._rmin_spin.setDecimals(0)
        self._rmin_spin.setSuffix(" cm\u207b\u00b9")
        self._rmin_spin.setValue(1000.0)
        form.addRow("Range min:", self._rmin_spin)

        self._rmax_spin = QDoubleSpinBox()
        self._rmax_spin.setRange(400.0, 4000.0)
        self._rmax_spin.setDecimals(0)
        self._rmax_spin.setSuffix(" cm\u207b\u00b9")
        self._rmax_spin.setValue(1200.0)
        form.addRow("Range max:", self._rmax_spin)

        # Keep the interval valid while it is edited instead of accepting an
        # inverted range that can never match a peak.
        self._rmin_spin.valueChanged.connect(self._rmax_spin.setMinimum)
        self._rmax_spin.valueChanged.connect(self._rmin_spin.setMaximum)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_values(self) -> tuple[str, float, float]:
        return (
            self._name_edit.text(),
            self._rmin_spin.value(),
            self._rmax_spin.value(),
        )
