"""
MetadataPanel — Panel metadat spektra.

Zodpovědnost:
- Zobrazení a editace metadat (titul, vzorek, operátor, datum)
- Synchronizace s Project.metadata objektem
- Read-only zobrazení dat extrahovaných ze SPA souboru
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFormLayout, QLabel, QLineEdit, QWidget

from core.metadata import SpectrumMetadata
from ui import theme
from ui.i18n import tr


class MetadataPanel(QWidget):
    """Displays and allows editing of spectrum metadata."""

    metadata_changed = Signal(object)  # emits SpectrumMetadata on editable-field changes

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._metadata = SpectrumMetadata()
        self._setting_metadata = False
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QFormLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setVerticalSpacing(6)
        layout.setHorizontalSpacing(10)
        # "Sample" is the OMNIC spectrum title (the sample designation printed
        # top-right in the report); "File" is the measurement file identifier
        # printed top-left.
        self._title_edit = QLineEdit()
        self._title_edit.setPlaceholderText("sample designation, e.g. LF_647")
        self._title_edit.setClearButtonEnabled(True)
        self._file_edit = QLineEdit()
        self._file_edit.setPlaceholderText("file identifier, defaults to the file name")
        self._file_edit.setClearButtonEnabled(True)
        self._operator_edit = QLineEdit()
        self._operator_edit.setClearButtonEnabled(True)
        self._instrument_edit = QLineEdit()
        self._instrument_edit.setPlaceholderText("e.g. Nicolet iS 50")
        self._instrument_edit.setClearButtonEnabled(True)
        self._title_edit.textChanged.connect(self._on_editable_fields_changed)
        self._file_edit.textChanged.connect(self._on_editable_fields_changed)
        self._operator_edit.textChanged.connect(self._on_editable_fields_changed)
        self._instrument_edit.textChanged.connect(self._on_editable_fields_changed)
        self._date_label = QLabel("\u2014")
        self._date_label.setStyleSheet(theme.READONLY_VALUE_STYLE)
        self._client_label = QLabel("\u2014")
        self._client_label.setTextFormat(Qt.TextFormat.PlainText)
        self._client_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._client_label.setStyleSheet(theme.READONLY_VALUE_STYLE)
        self._order_label = QLabel("\u2014")
        self._order_label.setTextFormat(Qt.TextFormat.PlainText)
        self._order_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._order_label.setStyleSheet(theme.READONLY_VALUE_STYLE)
        self._comment_label = QLabel("\u2014")
        self._comment_label.setTextFormat(Qt.TextFormat.PlainText)
        self._comment_label.setWordWrap(True)
        self._comment_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._comment_label.setStyleSheet(theme.READONLY_VALUE_STYLE)

        layout.addRow("Sample:", self._title_edit)
        layout.addRow("File:", self._file_edit)
        layout.addRow("Operator:", self._operator_edit)
        layout.addRow("Instrument:", self._instrument_edit)

        self._details_header = QLabel(tr("Acquisition & file details"))
        self._details_header.setStyleSheet(theme.SECTION_TITLE_STYLE)
        layout.addRow(self._details_header)

        layout.addRow("Acquired:", self._date_label)
        layout.addRow("Client:", self._client_label)
        layout.addRow("Order:", self._order_label)
        layout.addRow("Comment:", self._comment_label)

    @staticmethod
    def _set_readonly_label(label: QLabel, value: str) -> None:
        cleaned = value.strip()
        if cleaned:
            label.setText(cleaned)
            label.setStyleSheet(theme.READONLY_VALUE_STYLE)
        else:
            label.setText("\u2014")
            label.setStyleSheet(
                f"color: {theme.TEXT_FAINT}; background: {theme.SURFACE_ALT}; "
                f"border: 1px solid {theme.BORDER}; border-radius: 4px; padding: 2px 6px;"
            )

    def set_metadata(self, metadata: SpectrumMetadata) -> None:
        """Populate fields from metadata object.

        Args:
            metadata: Spectrum metadata to display.
        """
        self._metadata = SpectrumMetadata(
            title=metadata.title,
            file_name=metadata.file_name,
            operator=metadata.operator,
            instrument=metadata.instrument,
            acquired_at=metadata.acquired_at,
            resolution=metadata.resolution,
            scans=metadata.scans,
            comments=metadata.comments,
            extra=dict(metadata.extra),
        )
        self._setting_metadata = True
        self._title_edit.setText(metadata.title)
        self._file_edit.setText(metadata.file_name)
        self._operator_edit.setText(metadata.operator)
        self._instrument_edit.setText(metadata.instrument)
        date_text = metadata.acquired_at.strftime("%Y-%m-%d %H:%M") if metadata.acquired_at else ""
        self._set_readonly_label(self._date_label, date_text)
        self._set_readonly_label(self._client_label, metadata.extra.get("omnic_client", ""))
        self._set_readonly_label(self._order_label, metadata.extra.get("omnic_order", ""))
        self._set_readonly_label(self._comment_label, metadata.comments or "")
        self._setting_metadata = False

    def current_metadata(self) -> SpectrumMetadata:
        """Return the current metadata, including editable user fields."""
        return SpectrumMetadata(
            title=self._title_edit.text().strip(),
            file_name=self._file_edit.text().strip(),
            operator=self._operator_edit.text().strip(),
            instrument=self._instrument_edit.text().strip(),
            acquired_at=self._metadata.acquired_at,
            resolution=self._metadata.resolution,
            scans=self._metadata.scans,
            comments=self._metadata.comments,
            extra=dict(self._metadata.extra),
        )

    def _on_editable_fields_changed(self) -> None:
        if self._setting_metadata:
            return
        self._metadata = self.current_metadata()
        self.metadata_changed.emit(self.current_metadata())
