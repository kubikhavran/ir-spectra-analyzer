"""Dialog for managing the reference spectrum library."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from storage.database import Database


class ReferenceLibraryDialog(QDialog):
    """Dialog for viewing, renaming, and deleting reference spectra."""

    def __init__(self, db: Database, parent=None) -> None:
        super().__init__(parent)
        self._db = db
        self._refs: list[dict] = []
        self.setWindowTitle("Reference Library")
        self.setMinimumSize(700, 500)
        self._setup_ui()
        self._load_data()

    def _setup_ui(self) -> None:
        """Build the dialog layout."""
        root_layout = QVBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)

        # --- Left: table ---
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["Name", "Description", "Source", "Y Unit", "Created At"]
        )
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setSortingEnabled(True)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)

        left_layout.addWidget(self._table)
        splitter.addWidget(left_widget)

        # --- Right: preview ---
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(4, 4, 4, 4)

        self._preview_label = QLabel("Select a row to preview")
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._preview_label.setWordWrap(True)
        right_layout.addWidget(self._preview_label)
        right_layout.addStretch()

        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)

        root_layout.addWidget(splitter)

        # --- Bottom buttons ---
        btn_layout = QHBoxLayout()

        self._rename_btn = QPushButton("Rename")
        self._rename_btn.setEnabled(False)
        self._rename_btn.clicked.connect(self._on_rename)

        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setEnabled(False)
        self._delete_btn.clicked.connect(self._on_delete)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)

        btn_layout.addWidget(self._rename_btn)
        btn_layout.addWidget(self._delete_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)

        root_layout.addLayout(btn_layout)

    def _load_data(self) -> None:
        """Fetch all reference spectra from DB and populate the table."""
        self._refs = self._db.get_reference_spectra()

        # Disable sorting while inserting to avoid index confusion
        self._table.setSortingEnabled(False)
        self._table.setRowCount(0)

        for ref in self._refs:
            row = self._table.rowCount()
            self._table.insertRow(row)

            name_item = QTableWidgetItem(ref["name"])
            name_item.setData(Qt.ItemDataRole.UserRole, ref["id"])
            self._table.setItem(row, 0, name_item)
            self._table.setItem(row, 1, QTableWidgetItem(ref.get("description", "")))
            self._table.setItem(row, 2, QTableWidgetItem(ref.get("source", "")))
            self._table.setItem(row, 3, QTableWidgetItem(ref.get("y_unit", "")))
            self._table.setItem(row, 4, QTableWidgetItem(ref.get("created_at", "")))

        self._table.setSortingEnabled(True)
        self._table.resizeColumnsToContents()
        self._table.clearSelection()
        self._preview_label.setText("Select a row to preview")
        self._update_button_state()

    def _selected_ref_id(self) -> int | None:
        """Return the DB id of the currently selected row, or None."""
        selected = self._table.selectedItems()
        if not selected:
            return None
        row = self._table.currentRow()
        item = self._table.item(row, 0)
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _selected_ref(self) -> dict | None:
        """Return the full dict for the selected reference, or None."""
        ref_id = self._selected_ref_id()
        if ref_id is None:
            return None
        return next((r for r in self._refs if r["id"] == ref_id), None)

    def _on_selection_changed(self) -> None:
        """Update preview and button states when the table selection changes."""
        self._update_button_state()
        ref = self._selected_ref()
        if ref is None:
            self._preview_label.setText("Select a row to preview")
            return

        n_points = len(ref.get("wavenumbers", []))
        text = (
            f"Name: {ref['name']}\n"
            f"Description: {ref.get('description', '')}\n"
            f"Source: {ref.get('source', '')}\n"
            f"Y Unit: {ref.get('y_unit', '')}\n"
            f"Created: {ref.get('created_at', '')}\n"
            f"Points: {n_points}"
        )
        self._preview_label.setText(text)

    def _update_button_state(self) -> None:
        """Enable/disable action buttons based on whether a row is selected."""
        has_selection = self._selected_ref_id() is not None
        self._rename_btn.setEnabled(has_selection)
        self._delete_btn.setEnabled(has_selection)

    def _on_delete(self) -> None:
        """Confirm and delete the selected reference spectrum."""
        ref = self._selected_ref()
        if ref is None:
            return

        answer = QMessageBox.question(
            self,
            "Delete Reference",
            f'Delete reference spectrum "{ref["name"]}"?\nThis cannot be undone.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self._db.delete_reference_spectrum(ref["id"])
        self._preview_label.setText("Select a row to preview")
        self._load_data()

    def _on_rename(self) -> None:
        """Prompt for a new name and rename the selected reference spectrum."""
        ref = self._selected_ref()
        if ref is None:
            return

        new_name, ok = QInputDialog.getText(
            self,
            "Rename Reference",
            "New name:",
            text=ref["name"],
        )
        if not ok or not new_name.strip():
            return

        self._db.rename_reference_spectrum(ref["id"], new_name.strip())
        self._load_data()
