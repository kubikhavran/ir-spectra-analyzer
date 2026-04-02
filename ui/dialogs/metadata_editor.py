"""Dialog for editing spectrum metadata fields."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QTextEdit


class MetadataEditorDialog(QDialog):
    """Dialog for editing spectrum metadata."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Metadata")
        layout = QFormLayout(self)
        self._sample_edit = QLineEdit()
        self._operator_edit = QLineEdit()
        self._comments_edit = QTextEdit()
        layout.addRow("Sample:", self._sample_edit)
        layout.addRow("Operator:", self._operator_edit)
        layout.addRow("Comments:", self._comments_edit)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)
