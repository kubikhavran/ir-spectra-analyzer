"""About dialog with application info and version."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout

from app.config import APP_NAME, APP_VERSION


class AboutDialog(QDialog):
    """About dialog showing application version and credits."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"About {APP_NAME}")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"<h2>{APP_NAME}</h2>"))
        layout.addWidget(QLabel(f"Version {APP_VERSION}"))
        layout.addWidget(QLabel("Professional IR spectrum analysis tool"))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
