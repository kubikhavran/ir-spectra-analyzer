"""Dialog for generating project files from a folder of `.spa` files."""

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

from app.batch_project_generation import BatchProjectGenerator, BatchProjectSummary


class BatchProjectGenerationDialog(QDialog):
    """Dialog for generating `.irproj` files in bulk from a folder of spectra."""

    def __init__(self, generator: BatchProjectGenerator | None = None, parent=None) -> None:
        super().__init__(parent)
        self._generator = generator or BatchProjectGenerator()
        self.setWindowTitle("Batch Generate Projects")
        self.setMinimumSize(860, 560)
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
        self._output_folder_edit.setPlaceholderText("Choose a folder for generated projects")
        browse_output_button = QPushButton("Browse Output...")
        browse_output_button.clicked.connect(self._on_browse_output)
        output_layout.addWidget(QLabel("Output:"))
        output_layout.addWidget(self._output_folder_edit)
        output_layout.addWidget(browse_output_button)
        root_layout.addLayout(output_layout)

        self._detect_peaks_checkbox = QCheckBox("Auto-detect peaks")
        self._detect_peaks_checkbox.setChecked(False)
        root_layout.addWidget(self._detect_peaks_checkbox)

        self._summary_label = QLabel("Choose input and output folders, then click Generate.")
        self._summary_label.setWordWrap(True)
        root_layout.addWidget(self._summary_label)

        self._results_table = QTableWidget(0, 5)
        self._results_table.setHorizontalHeaderLabels(
            ["File", "Status", "Peak Count", "Reason", "Output Project"]
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
        self._results_table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.ResizeToContents
        )
        root_layout.addWidget(self._results_table)

        buttons_layout = QHBoxLayout()
        self._generate_button = QPushButton("Generate")
        self._generate_button.setEnabled(False)
        self._generate_button.clicked.connect(self._on_generate)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        buttons_layout.addStretch()
        buttons_layout.addWidget(self._generate_button)
        buttons_layout.addWidget(close_button)
        root_layout.addLayout(buttons_layout)

    def _on_browse_input(self) -> None:
        """Open a folder picker for the source spectra folder."""
        folder = QFileDialog.getExistingDirectory(self, "Select Folder with SPA Files")
        if folder:
            self._set_input_folder(Path(folder))

    def _on_browse_output(self) -> None:
        """Open a folder picker for the project output folder."""
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Output Folder for Generated Projects",
        )
        if folder:
            self._set_output_folder(Path(folder))

    def _set_input_folder(self, folder: Path) -> None:
        """Store the selected input folder and show how many `.spa` files were found."""
        self._input_folder_edit.setText(str(folder))
        self._results_table.setRowCount(0)
        self._update_generate_button_state()
        try:
            files = self._generator.scan_folder(folder)
        except (FileNotFoundError, NotADirectoryError) as exc:
            self._summary_label.setText(str(exc))
            self._generate_button.setEnabled(False)
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
        self._update_generate_button_state()
        if self._input_folder_edit.text().strip():
            self._summary_label.setText("Ready to generate project files.")

    def _update_generate_button_state(self) -> None:
        """Enable Generate only when both input and output folders are selected."""
        has_input = bool(self._input_folder_edit.text().strip())
        has_output = bool(self._output_folder_edit.text().strip())
        self._generate_button.setEnabled(has_input and has_output)

    def _on_generate(self) -> None:
        """Run batch project generation for the selected folders."""
        input_text = self._input_folder_edit.text().strip()
        if not input_text:
            self._summary_label.setText("No input folder selected.")
            return

        output_text = self._output_folder_edit.text().strip()
        if not output_text:
            self._summary_label.setText("No output folder selected.")
            return

        try:
            summary = self._generator.generate_folder(
                input_text,
                output_text,
                detect_peaks=self._detect_peaks_checkbox.isChecked(),
            )
        except (FileNotFoundError, NotADirectoryError) as exc:
            self._summary_label.setText(str(exc))
            self._results_table.setRowCount(0)
            return

        self._populate_results(summary)

    def _populate_results(self, summary: BatchProjectSummary) -> None:
        """Render batch project-generation results into the table and summary label."""
        self._results_table.setRowCount(0)
        for result in summary.results:
            row = self._results_table.rowCount()
            self._results_table.insertRow(row)
            self._results_table.setItem(row, 0, QTableWidgetItem(result.path.name))
            self._results_table.setItem(row, 1, QTableWidgetItem(result.status.value))
            self._results_table.setItem(row, 2, QTableWidgetItem(str(result.peak_count)))
            self._results_table.setItem(row, 3, QTableWidgetItem(result.reason))
            output_text = str(result.output_path) if result.output_path is not None else ""
            self._results_table.setItem(row, 4, QTableWidgetItem(output_text))

        self._summary_label.setText(
            f"Total .spa files found: {summary.total_found}\n"
            f"Generated: {summary.generated} | Skipped: {summary.skipped} | Failed: {summary.failed}"
        )
