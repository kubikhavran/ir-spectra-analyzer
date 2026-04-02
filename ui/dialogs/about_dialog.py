"""About dialog with application info and version."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout


class AboutDialog(QDialog):
    """About dialog showing application version and credits."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About IR Spectra Analyzer")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<h2>IR Spectra Analyzer</h2>"))
        layout.addWidget(QLabel("Version 0.1.0"))
        layout.addWidget(QLabel("Professional IR spectrum analysis tool"))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
