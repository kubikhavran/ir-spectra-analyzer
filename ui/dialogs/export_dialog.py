"""Dialog for choosing export format and options."""
from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QVBoxLayout, QRadioButton


class ExportDialog(QDialog):
    """Dialog for selecting export format (PDF, CSV, XLSX)."""

    def __init__(self, parent=None) -> None:
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
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def selected_format(self) -> str:
        """Return selected export format string."""
        if self._pdf_radio.isChecked():
            return "pdf"
        if self._csv_radio.isChecked():
            return "csv"
        return "xlsx"
