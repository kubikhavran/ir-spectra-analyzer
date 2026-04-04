"""Dialog for choosing export format and report options."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QRadioButton, QVBoxLayout

from app.report_presets import ReportPresetManager
from reporting.pdf_generator import ReportOptions
from ui.report_options_widget import ReportOptionsWidget


class ExportDialog(QDialog):
    """Dialog for selecting export format (PDF, CSV, XLSX)."""

    def __init__(
        self,
        parent=None,
        *,
        preset_manager: ReportPresetManager | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export")
        layout = QVBoxLayout(self)
        self._pdf_radio = QRadioButton("PDF Report")
        self._pdf_radio.setChecked(True)
        self._csv_radio = QRadioButton("CSV (peaks table)")
        self._xlsx_radio = QRadioButton("Excel (.xlsx)")
        layout.addWidget(self._pdf_radio)
        layout.addWidget(self._csv_radio)
        layout.addWidget(self._xlsx_radio)

        self._report_options_widget = ReportOptionsWidget(
            preset_manager=preset_manager, parent=self
        )
        layout.addWidget(self._report_options_widget)
        self._preset_combo = self._report_options_widget._preset_combo
        self._save_preset_button = self._report_options_widget._save_preset_button
        self._delete_preset_button = self._report_options_widget._delete_preset_button
        self._include_metadata_checkbox = self._report_options_widget._include_metadata_checkbox
        self._include_peak_table_checkbox = self._report_options_widget._include_peak_table_checkbox
        self._include_structures_checkbox = self._report_options_widget._include_structures_checkbox

        self._pdf_radio.toggled.connect(self._update_pdf_option_state)
        self._update_pdf_option_state()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _update_pdf_option_state(self) -> None:
        """Enable PDF-specific option controls only when PDF export is selected."""
        self._report_options_widget.set_option_controls_enabled(self._pdf_radio.isChecked())

    @property
    def selected_format(self) -> str:
        """Return selected export format string."""
        if self._pdf_radio.isChecked():
            return "pdf"
        if self._csv_radio.isChecked():
            return "csv"
        return "xlsx"

    @property
    def report_options(self) -> ReportOptions:
        """Return the currently selected PDF report options."""
        return self._report_options_widget.report_options()

    def remember_selected_preset(self) -> None:
        """Persist the current named preset as the last used preset."""
        self._report_options_widget.remember_current_preset()
