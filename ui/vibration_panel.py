"""
VibrationPanel — Panel předvoleb vibrací.

Zodpovědnost:
- Zobrazení seznamu vibračních předvoleb dle kategorie
- Přiřazení předvolby k vybranému peaku kliknutím
- Filtrování předvoleb dle rozsahu wavenumberů aktivního peaku
- Přidání vlastních vibrací uložených v databázi
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
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
        self._active_peak = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

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

    def set_active_peak(self, peak) -> None:
        """Track the currently active peak for context menu remove action."""
        self._active_peak = peak

    def set_presets(self, presets: list[VibrationPreset]) -> None:
        self._presets = presets
        self._rebuild_list(self._filter_edit.text())

    def highlight_for_peak(self, wavenumber: float) -> None:
        self._hint_label.setText(f"Active peak: {wavenumber:.0f} cm\u207b\u00b9")
        for i in range(self._list.count()):
            item = self._list.item(i)
            preset = item.data(256)
            if preset is not None and preset.covers_wavenumber(wavenumber):
                item.setBackground(QColor("#C8E6C9"))
                item.setForeground(QColor("#000000"))
            else:
                item.setBackground(QBrush())
                item.setForeground(QBrush())

    def _rebuild_list(self, filter_text: str = "") -> None:
        self._list.clear()
        needle = filter_text.strip().lower()
        for preset in self._presets:
            label = (
                f"{preset.name}  "
                f"({preset.typical_range_min:.0f}\u2013{preset.typical_range_max:.0f} cm\u207b\u00b9)"
            )
            if not preset.is_builtin:
                label = f"\u2605 {label}"
            if needle and needle not in label.lower():
                continue
            item = QListWidgetItem(label)
            item.setData(256, preset)
            if not preset.is_builtin:
                item.setForeground(QColor("#1A5276"))  # dark blue for custom
            self._list.addItem(item)

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

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("e.g. \u03bd(C=O) \u2013CO\u2013O\u2013")
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
