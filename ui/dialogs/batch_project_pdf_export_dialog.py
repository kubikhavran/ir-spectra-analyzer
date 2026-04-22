"""Dialog for bulk PDF export from saved `.irproj` files."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMetaObject, Qt, QThread
from PySide6.QtWidgets import (
    QComboBox,
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

from app.batch_project_pdf_export import BatchProjectPDFExporter, BatchProjectPDFSummary
from app.output_path_policy import OVERWRITE_MODE_OPTIONS
from app.report_presets import ReportPresetManager
from reporting.pdf_generator import ReportOptions
from ui.report_options_widget import ReportOptionsWidget


class BatchProjectPDFExportDialog(QDialog):
    """Dialog for exporting PDF reports from saved `.irproj` files."""

    def __init__(
        self,
        exporter: BatchProjectPDFExporter | None = None,
        parent=None,
        *,
        preset_manager: ReportPresetManager | None = None,
    ) -> None:
        super().__init__(parent)
        self._exporter = exporter or BatchProjectPDFExporter()
        self._preset_manager = preset_manager
        self._export_thread: QThread | None = None
        self.setWindowTitle("Batch Export Project PDFs")
        self.setMinimumSize(860, 560)
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Build the dialog layout."""
        root_layout = QVBoxLayout(self)

        input_layout = QHBoxLayout()
        self._input_folder_edit = QLineEdit()
        self._input_folder_edit.setReadOnly(True)
        self._input_folder_edit.setPlaceholderText("Choose a folder containing .irproj files")
        self._browse_input_button = QPushButton("Browse Input...")
        self._browse_input_button.clicked.connect(self._on_browse_input)
        input_layout.addWidget(QLabel("Input:"))
        input_layout.addWidget(self._input_folder_edit)
        input_layout.addWidget(self._browse_input_button)
        root_layout.addLayout(input_layout)

        output_layout = QHBoxLayout()
        self._output_folder_edit = QLineEdit()
        self._output_folder_edit.setReadOnly(True)
        self._output_folder_edit.setPlaceholderText("Choose a folder for exported PDFs")
        self._browse_output_button = QPushButton("Browse Output...")
        self._browse_output_button.clicked.connect(self._on_browse_output)
        output_layout.addWidget(QLabel("Output:"))
        output_layout.addWidget(self._output_folder_edit)
        output_layout.addWidget(self._browse_output_button)
        root_layout.addLayout(output_layout)

        overwrite_layout = QHBoxLayout()
        self._overwrite_mode_combo = QComboBox()
        for label, value in OVERWRITE_MODE_OPTIONS:
            self._overwrite_mode_combo.addItem(label, value)
        overwrite_layout.addWidget(QLabel("When output exists:"))
        overwrite_layout.addWidget(self._overwrite_mode_combo)
        overwrite_layout.addStretch()
        root_layout.addLayout(overwrite_layout)

        self._report_options_widget = ReportOptionsWidget(
            preset_manager=self._preset_manager,
            parent=self,
        )
        self._preset_combo = self._report_options_widget._preset_combo
        self._save_preset_button = self._report_options_widget._save_preset_button
        self._delete_preset_button = self._report_options_widget._delete_preset_button
        self._include_metadata_checkbox = self._report_options_widget._include_metadata_checkbox
        self._include_peak_table_checkbox = self._report_options_widget._include_peak_table_checkbox
        self._include_structures_checkbox = self._report_options_widget._include_structures_checkbox
        root_layout.addWidget(self._report_options_widget)

        self._summary_label = QLabel("Choose input and output folders, then click Export.")
        self._summary_label.setWordWrap(True)
        root_layout.addWidget(self._summary_label)

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
        """Open a folder picker for the saved-project folder."""
        folder = QFileDialog.getExistingDirectory(self, "Select Folder with Project Files")
        if folder:
            self._set_input_folder(Path(folder))

    def _on_browse_output(self) -> None:
        """Open a folder picker for the PDF output folder."""
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder for PDF Reports")
        if folder:
            self._set_output_folder(Path(folder))

    def _set_input_folder(self, folder: Path) -> None:
        """Store the selected input folder and show how many `.irproj` files were found."""
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
                f"Found {len(files)} .irproj file(s) in the selected input folder."
            )
        else:
            self._summary_label.setText("No .irproj files found in the selected input folder.")

    def _set_output_folder(self, folder: Path) -> None:
        """Store the selected output folder."""
        self._output_folder_edit.setText(str(folder))
        self._results_table.setRowCount(0)
        self._update_export_button_state()
        if self._input_folder_edit.text().strip():
            self._summary_label.setText("Ready to export project PDFs.")

    def _update_export_button_state(self) -> None:
        """Enable Export only when both input and output folders are selected."""
        has_input = bool(self._input_folder_edit.text().strip())
        has_output = bool(self._output_folder_edit.text().strip())
        self._export_button.setEnabled(has_input and has_output)

    def _on_export(self) -> None:
        """Run batch project-PDF export for the selected folders."""
        input_text = self._input_folder_edit.text().strip()
        if not input_text:
            self._summary_label.setText("No input folder selected.")
            return

        output_text = self._output_folder_edit.text().strip()
        if not output_text:
            self._summary_label.setText("No output folder selected.")
            return

        if self._export_thread is not None:
            return

        report_options = self._current_report_options()
        overwrite_mode = str(self._overwrite_mode_combo.currentData())
        if isinstance(self._exporter, BatchProjectPDFExporter):
            self._start_background_export(
                input_text,
                output_text,
                report_options=report_options,
                overwrite_mode=overwrite_mode,
            )
            return

        try:
            summary = self._exporter.export_folder(
                input_text,
                output_text,
                report_options=report_options,
                overwrite_mode=overwrite_mode,
            )
        except (FileNotFoundError, NotADirectoryError) as exc:
            self._summary_label.setText(str(exc))
            self._results_table.setRowCount(0)
            return

        self._report_options_widget.remember_current_preset()
        self._populate_results(summary)

    def _start_background_export(
        self,
        input_folder: str,
        output_folder: str,
        *,
        report_options: ReportOptions,
        overwrite_mode: str,
    ) -> None:
        """Run batch project-PDF export in a worker thread for the default exporter path."""
        from ui.workers.batch_project_pdf_export_worker import (  # noqa: PLC0415
            BatchProjectPDFExportWorker,
        )

        worker = BatchProjectPDFExportWorker(
            input_folder=input_folder,
            output_folder=output_folder,
            report_options=report_options,
            overwrite_mode=overwrite_mode,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        worker.completed.connect(self._on_background_export_completed)
        worker.failed.connect(self._on_background_export_failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(self._on_export_worker_finished)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.started.connect(
            lambda: QMetaObject.invokeMethod(worker, "run", Qt.ConnectionType.QueuedConnection)
        )
        self._export_thread = thread
        self._set_export_busy(True)
        thread.start()

    def _on_background_export_completed(self, summary: BatchProjectPDFSummary) -> None:
        """Apply background export results to the dialog."""
        self._report_options_widget.remember_current_preset()
        self._populate_results(summary)

    def _on_background_export_failed(self, message: str) -> None:
        """Show a batch project-PDF export failure."""
        self._summary_label.setText(message)
        self._results_table.setRowCount(0)

    def _on_export_worker_finished(self) -> None:
        """Reset UI state after the worker finishes."""
        self._export_thread = None
        self._set_export_busy(False)

    def _set_export_busy(self, busy: bool) -> None:
        """Enable or disable interactive controls while export is running."""
        self._browse_input_button.setEnabled(not busy)
        self._browse_output_button.setEnabled(not busy)
        self._overwrite_mode_combo.setEnabled(not busy)
        self._report_options_widget.setEnabled(not busy)
        self._export_button.setEnabled(
            not busy
            and bool(self._input_folder_edit.text().strip())
            and bool(self._output_folder_edit.text().strip())
        )
        if busy:
            self._summary_label.setText("Exporting project PDFs…")

    def _current_report_options(self) -> ReportOptions:
        """Return the report content options selected in the dialog."""
        return self._report_options_widget.report_options()

    def _populate_results(self, summary: BatchProjectPDFSummary) -> None:
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
            f"Total .irproj files found: {summary.total_found}\n"
            f"Exported: {summary.exported} | Skipped: {summary.skipped} | Failed: {summary.failed}"
        )
