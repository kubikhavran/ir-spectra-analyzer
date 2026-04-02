"""Dialog for bulk PDF export from a folder of `.spa` files."""

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

from app.batch_pdf_export import BatchPDFExporter, BatchPDFSummary


class BatchPDFExportDialog(QDialog):
    """Dialog for exporting PDF reports in bulk from a folder of spectra."""

    def __init__(self, exporter: BatchPDFExporter | None = None, parent=None) -> None:
        super().__init__(parent)
        self._exporter = exporter or BatchPDFExporter()
        self.setWindowTitle("Batch Export PDF Reports")
        self.setMinimumSize(820, 540)
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Build the dialog layout."""
        root_layout = QVBoxLayout(self)

        input_layout = QHBoxLayout()
        self._input_folder_edit = QLineEdit()
        self._input_folder_edit.setReadOnly(True)
        self._input_folder_edit.setPlaceholderText("Choose a folder containing .spa files")
        browse_input_button = QPushButton("Browse Input...")
        browse_input_button.clicked.connect(self._on_browse_input)
        input_layout.addWidget(QLabel("Input:"))
        input_layout.addWidget(self._input_folder_edit)
        input_layout.addWidget(browse_input_button)
        root_layout.addLayout(input_layout)

        output_layout = QHBoxLayout()
        self._output_folder_edit = QLineEdit()
        self._output_folder_edit.setReadOnly(True)
        self._output_folder_edit.setPlaceholderText("Choose a folder for exported PDFs")
        browse_output_button = QPushButton("Browse Output...")
        browse_output_button.clicked.connect(self._on_browse_output)
        output_layout.addWidget(QLabel("Output:"))
        output_layout.addWidget(self._output_folder_edit)
        output_layout.addWidget(browse_output_button)
        root_layout.addLayout(output_layout)

        self._summary_label = QLabel("Choose input and output folders, then click Export.")
        self._summary_label.setWordWrap(True)
        root_layout.addWidget(self._summary_label)

        self._detect_peaks_checkbox = QCheckBox("Auto-detect peaks")
        self._detect_peaks_checkbox.setChecked(False)
        root_layout.addWidget(self._detect_peaks_checkbox)

        self._results_table = QTableWidget(0, 4)
        self._results_table.setHorizontalHeaderLabels(["File", "Status", "Reason", "Output PDF"])
        self._results_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._results_table.verticalHeader().setVisible(False)
        self._results_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._results_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self._results_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self._results_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents
        )
        root_layout.addWidget(self._results_table)

        buttons_layout = QHBoxLayout()
        self._export_button = QPushButton("Export")
        self._export_button.setEnabled(False)
        self._export_button.clicked.connect(self._on_export)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        buttons_layout.addStretch()
        buttons_layout.addWidget(self._export_button)
        buttons_layout.addWidget(close_button)
        root_layout.addLayout(buttons_layout)

    def _on_browse_input(self) -> None:
        """Open a folder picker for the source spectra folder."""
        folder = QFileDialog.getExistingDirectory(self, "Select Folder with SPA Files")
        if folder:
            self._set_input_folder(Path(folder))

    def _on_browse_output(self) -> None:
        """Open a folder picker for the PDF output folder."""
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder for PDF Reports")
        if folder:
            self._set_output_folder(Path(folder))

    def _set_input_folder(self, folder: Path) -> None:
        """Store the selected input folder and show how many `.spa` files were found."""
        self._input_folder_edit.setText(str(folder))
        self._results_table.setRowCount(0)
        self._update_export_button_state()
        try:
            files = self._exporter.scan_folder(folder)
        except (FileNotFoundError, NotADirectoryError) as exc:
            self._summary_label.setText(str(exc))
            self._export_button.setEnabled(False)
            return

        if files:
            self._summary_label.setText(
                f"Found {len(files)} .spa file(s) in the selected input folder."
            )
        else:
            self._summary_label.setText("No .spa files found in the selected input folder.")

    def _set_output_folder(self, folder: Path) -> None:
        """Store the selected output folder."""
        self._output_folder_edit.setText(str(folder))
        self._results_table.setRowCount(0)
        self._update_export_button_state()
        if self._input_folder_edit.text().strip():
            self._summary_label.setText("Ready to export PDF reports.")

    def _update_export_button_state(self) -> None:
        """Enable Export only when both input and output folders are selected."""
        has_input = bool(self._input_folder_edit.text().strip())
        has_output = bool(self._output_folder_edit.text().strip())
        self._export_button.setEnabled(has_input and has_output)

    def _on_export(self) -> None:
        """Run the batch PDF export for the selected folders."""
        input_text = self._input_folder_edit.text().strip()
        if not input_text:
            self._summary_label.setText("No input folder selected.")
            return

        output_text = self._output_folder_edit.text().strip()
        if not output_text:
            self._summary_label.setText("No output folder selected.")
            return

        try:
            summary = self._exporter.export_folder(
                input_text,
                output_text,
                detect_peaks=self._detect_peaks_checkbox.isChecked(),
            )
        except (FileNotFoundError, NotADirectoryError) as exc:
            self._summary_label.setText(str(exc))
            self._results_table.setRowCount(0)
            return

        self._populate_results(summary)

    def _populate_results(self, summary: BatchPDFSummary) -> None:
        """Render batch export results into the table and summary label."""
        self._results_table.setRowCount(0)
        for result in summary.results:
            row = self._results_table.rowCount()
            self._results_table.insertRow(row)
            self._results_table.setItem(row, 0, QTableWidgetItem(result.path.name))
            self._results_table.setItem(row, 1, QTableWidgetItem(result.status.value))
            self._results_table.setItem(row, 2, QTableWidgetItem(result.reason))
            output_text = str(result.output_path) if result.output_path is not None else ""
            self._results_table.setItem(row, 3, QTableWidgetItem(output_text))

        self._summary_label.setText(
            f"Total .spa files found: {summary.total_found}\n"
            f"Exported: {summary.exported} | Skipped: {summary.skipped} | Failed: {summary.failed}"
        )
