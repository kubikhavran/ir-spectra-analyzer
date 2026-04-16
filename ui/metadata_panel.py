"""
MetadataPanel — Panel metadat spektra.

Zodpovědnost:
- Zobrazení a editace metadat (titul, vzorek, operátor, datum)
- Synchronizace s Project.metadata objektem
- Read-only zobrazení dat extrahovaných ze SPA souboru
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QLabel, QLineEdit, QWidget

from core.metadata import SpectrumMetadata


class MetadataPanel(QWidget):
    """Displays and allows editing of spectrum metadata."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QFormLayout(self)
        self._title_edit = QLineEdit()
        self._sample_edit = QLineEdit()
        self._operator_edit = QLineEdit()
        self._instrument_label = QLabel()
        self._date_label = QLabel()
        self._client_label = QLabel()
        self._client_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._order_label = QLabel()
        self._order_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._comment_label = QLabel()
        self._comment_label.setWordWrap(True)
        self._comment_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        layout.addRow("Title:", self._title_edit)
        layout.addRow("Sample:", self._sample_edit)
        layout.addRow("Operator:", self._operator_edit)
        layout.addRow("Instrument:", self._instrument_label)
        layout.addRow("Acquired:", self._date_label)
        layout.addRow("Client:", self._client_label)
        layout.addRow("Order:", self._order_label)
        layout.addRow("Comment:", self._comment_label)

    def set_metadata(self, metadata: SpectrumMetadata) -> None:
        """Populate fields from metadata object.

        Args:
            metadata: Spectrum metadata to display.
        """
        self._title_edit.setText(metadata.title)
        self._sample_edit.setText(metadata.sample_name)
        self._operator_edit.setText(metadata.operator)
        self._instrument_label.setText(metadata.instrument)
        if metadata.acquired_at:
            self._date_label.setText(metadata.acquired_at.strftime("%Y-%m-%d %H:%M"))
        self._client_label.setText(metadata.extra.get("omnic_client", ""))
        self._order_label.setText(metadata.extra.get("omnic_order", ""))
        self._comment_label.setText(metadata.comments or "")
