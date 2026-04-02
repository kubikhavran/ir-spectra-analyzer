"""Dialog for batch-importing reference spectra from a folder."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.reference_import import BatchImportSummary, ReferenceImportService
from storage.database import Database


class BatchImportDialog(QDialog):
    """Dialog for importing multiple `.spa` files into the reference library."""

    def __init__(self, db: Database, parent=None) -> None:
        super().__init__(parent)
        self._service = ReferenceImportService(db)
        self.setWindowTitle("Batch Import References")
        self.setMinimumSize(760, 520)
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Build the dialog layout."""
        root_layout = QVBoxLayout(self)

        folder_layout = QHBoxLayout()
        self._folder_edit = QLineEdit()
        self._folder_edit.setReadOnly(True)
        self._folder_edit.setPlaceholderText("Choose a folder containing .spa files")
        browse_button = QPushButton("Browse...")
        browse_button.clicked.connect(self._on_browse)
        folder_layout.addWidget(QLabel("Folder:"))
        folder_layout.addWidget(self._folder_edit)
        folder_layout.addWidget(browse_button)
        root_layout.addLayout(folder_layout)

        self._skip_duplicates_checkbox = QCheckBox("Skip duplicates by filename")
        self._skip_duplicates_checkbox.setChecked(True)
        root_layout.addWidget(self._skip_duplicates_checkbox)

        self._detect_peaks_checkbox = QCheckBox("Auto-detect peaks")
        self._detect_peaks_checkbox.setChecked(False)
        root_layout.addWidget(self._detect_peaks_checkbox)

        self._summary_label = QLabel("Select a folder and click Import.")
        self._summary_label.setWordWrap(True)
        root_layout.addWidget(self._summary_label)

        self._results_table = QTableWidget(0, 4)
        self._results_table.setHorizontalHeaderLabels(
            ["File", "Status", "Reference Name", "Reason"]
        )
        self._results_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._results_table.verticalHeader().setVisible(False)
        self._results_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._results_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self._results_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self._results_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        root_layout.addWidget(self._results_table)

        buttons_layout = QHBoxLayout()
        self._import_button = QPushButton("Import")
        self._import_button.setEnabled(False)
        self._import_button.clicked.connect(self._on_import)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        buttons_layout.addStretch()
        buttons_layout.addWidget(self._import_button)
        buttons_layout.addWidget(close_button)
        root_layout.addLayout(buttons_layout)

    def _on_browse(self) -> None:
        """Open a folder picker and update the dialog state."""
        folder = QFileDialog.getExistingDirectory(self, "Select Folder with SPA Files")
        if folder:
            self._set_folder(Path(folder))

    def _set_folder(self, folder: Path) -> None:
        """Store the selected folder and show how many `.spa` files were found."""
        self._folder_edit.setText(str(folder))
        self._import_button.setEnabled(True)
        self._results_table.setRowCount(0)
        try:
            files = self._service.scan_folder(folder)
        except (FileNotFoundError, NotADirectoryError) as exc:
            self._summary_label.setText(str(exc))
            self._import_button.setEnabled(False)
            return

        if files:
            self._summary_label.setText(f"Found {len(files)} .spa file(s) in the selected folder.")
        else:
            self._summary_label.setText("No .spa files found in the selected folder.")

    def _on_import(self) -> None:
        """Run the batch import for the currently selected folder."""
        folder_text = self._folder_edit.text().strip()
        if not folder_text:
            self._summary_label.setText("No folder selected.")
            return

        try:
            summary = self._service.batch_import_folder(
                Path(folder_text),
                skip_duplicates_by_filename=self._skip_duplicates_checkbox.isChecked(),
                detect_peaks=self._detect_peaks_checkbox.isChecked(),
            )
        except (FileNotFoundError, NotADirectoryError) as exc:
            self._summary_label.setText(str(exc))
            self._results_table.setRowCount(0)
            return

        self._populate_results(summary)

    def _populate_results(self, summary: BatchImportSummary) -> None:
        """Render batch results into the table and summary label."""
        self._results_table.setRowCount(0)
        for result in summary.results:
            row = self._results_table.rowCount()
            self._results_table.insertRow(row)
            self._results_table.setItem(row, 0, QTableWidgetItem(result.path.name))
            self._results_table.setItem(row, 1, QTableWidgetItem(result.status.value))
            self._results_table.setItem(row, 2, QTableWidgetItem(result.reference_name))
            self._results_table.setItem(row, 3, QTableWidgetItem(result.reason))

        self._summary_label.setText(
            f"Total .spa files found: {summary.total_found}\n"
            f"Imported: {summary.imported} | Skipped: {summary.skipped} | Failed: {summary.failed}"
        )
