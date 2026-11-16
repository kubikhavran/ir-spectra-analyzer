"""Dialog for choosing export format and report options."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from app.report_presets import ReportPresetManager
from file_io.csv_exporter import MODE_COMBINED, MODE_PEAKS_ONLY, MODE_SPECTRUM_ONLY
from reporting.pdf_generator import ReportOptions
from ui import i18n
from ui.i18n import tr
from ui.report_options_widget import ReportOptionsWidget

_CSV_MODES: tuple[tuple[str, str], ...] = (
    (MODE_COMBINED, "Whole analysis: metadata, peaks and spectrum"),
    (MODE_PEAKS_ONLY, "Peak table only"),
    (MODE_SPECTRUM_ONLY, "Spectrum data only (wavenumber, intensity)"),
)
_DECIMALS: tuple[tuple[str, str], ...] = (
    (".", "Decimal point (1.5)"),
    (",", "Decimal comma (1,5)"),
)


class ExportDialog(QDialog):
    """Dialog for selecting export format (PDF, CSV, XLSX)."""

    def __init__(
        self,
        parent=None,
        *,
        preset_manager: ReportPresetManager | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Export"))
        layout = QVBoxLayout(self)
        self._pdf_radio = QRadioButton(tr("PDF Report"))
        self._pdf_radio.setChecked(True)
        self._csv_radio = QRadioButton(tr("CSV (text table)"))
        self._xlsx_radio = QRadioButton(tr("Excel (.xlsx)"))
        layout.addWidget(self._pdf_radio)
        layout.addWidget(self._csv_radio)
        layout.addWidget(self._xlsx_radio)

        self._include_unassigned_checkbox = QCheckBox(tr("Include peaks without assignment"))
        layout.addWidget(self._include_unassigned_checkbox)

        # CSV: what goes in the file, and how decimals are written.
        self._csv_options = QWidget(self)
        csv_form = QFormLayout(self._csv_options)
        csv_form.setContentsMargins(20, 0, 0, 0)
        self._csv_mode_combo = QComboBox()
        for value, label in _CSV_MODES:
            self._csv_mode_combo.addItem(tr(label), value)
        csv_form.addRow(tr("Contents:"), self._csv_mode_combo)
        self._decimal_combo = QComboBox()
        for value, label in _DECIMALS:
            self._decimal_combo.addItem(tr(label), value)
        # A Czech Excel reads "1.5" as text; offer the comma first there.
        default_decimal = "," if i18n.language() == i18n.CZECH else "."
        self._decimal_combo.setCurrentIndex(self._decimal_combo.findData(default_decimal))
        self._decimal_combo.setToolTip(
            tr("Use the decimal comma for a Czech Excel, the decimal point for other software")
        )
        csv_form.addRow(tr("Numbers:"), self._decimal_combo)
        layout.addWidget(self._csv_options)

        # Excel: optional chart of the spectrum.
        self._include_chart_checkbox = QCheckBox(tr("Include spectrum chart in Excel"))
        self._include_chart_checkbox.setChecked(True)
        self._include_chart_checkbox.setToolTip(
            tr("Adds a chart of the spectrum to the Spectrum sheet, wavenumbers from 4000 to 400")
        )
        layout.addWidget(self._include_chart_checkbox)

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
        # One "peaks without assignment" box for every format: the dialog's own,
        # kept in step with the report widget's so a PDF preset still records it.
        report_box = self._report_options_widget._include_unassigned_checkbox
        report_box.setVisible(False)
        self._include_unassigned_checkbox.setChecked(report_box.isChecked())
        self._include_unassigned_checkbox.toggled.connect(report_box.setChecked)
        report_box.toggled.connect(self._include_unassigned_checkbox.setChecked)

        self._pdf_radio.toggled.connect(self._update_pdf_option_state)
        self._csv_radio.toggled.connect(self._update_unassigned_checkbox_state)
        self._xlsx_radio.toggled.connect(self._update_unassigned_checkbox_state)
        self._csv_mode_combo.currentIndexChanged.connect(
            lambda _index: self._update_unassigned_checkbox_state()
        )
        self._update_pdf_option_state()
        self._update_unassigned_checkbox_state()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _update_pdf_option_state(self) -> None:
        """Enable PDF-specific option controls only when PDF export is selected."""
        self._report_options_widget.set_option_controls_enabled(self._pdf_radio.isChecked())

    def _update_unassigned_checkbox_state(self) -> None:
        """Show each option only for the format it applies to."""
        csv = self._csv_radio.isChecked()
        xlsx = self._xlsx_radio.isChecked()
        spectrum_only = csv and self.csv_mode == MODE_SPECTRUM_ONLY
        self._include_unassigned_checkbox.setVisible(not spectrum_only)
        self._csv_options.setVisible(csv)
        self._include_chart_checkbox.setVisible(xlsx)

    @property
    def include_unassigned(self) -> bool:
        """Return True when the user wants unassigned peaks included."""
        return bool(self._include_unassigned_checkbox.isChecked())

    @property
    def csv_mode(self) -> str:
        """What a CSV export contains (see file_io.csv_exporter modes)."""
        return str(self._csv_mode_combo.currentData() or MODE_COMBINED)

    @property
    def decimal_separator(self) -> str:
        """``"."`` or ``","`` for CSV numbers."""
        return str(self._decimal_combo.currentData() or ".")

    @property
    def include_chart(self) -> bool:
        """True when the Excel workbook should carry a chart of the spectrum."""
        return bool(self._include_chart_checkbox.isChecked())

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
