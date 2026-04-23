"""Dialog for importing a single web-hosted IR reference into the local library."""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from app.providers.nist_webbook import NISTWebBookClient, NISTWebBookReference
from app.web_reference_import import WebReferenceImportService


class WebReferenceImportDialog(QDialog):
    """Preview and import a single NIST WebBook IR reference."""

    reference_imported = Signal(int)

    def __init__(
        self,
        service: WebReferenceImportService,
        parent=None,
        *,
        preview_client: NISTWebBookClient | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._preview_client = preview_client or NISTWebBookClient()
        self._preview_reference: NISTWebBookReference | None = None
        self.setWindowTitle("Import Web Reference")
        self.setMinimumWidth(560)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        form = QFormLayout()

        self._provider_combo = QComboBox()
        self._provider_combo.addItem("NIST WebBook", "nist_webbook")
        self._provider_combo.setEnabled(False)
        form.addRow("Provider:", self._provider_combo)

        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText(
            "https://webbook.nist.gov/cgi/cbook.cgi?ID=...&Index=...&Type=IR-SPEC"
        )
        self._url_edit.textChanged.connect(self._on_url_changed)
        form.addRow("URL:", self._url_edit)

        layout.addLayout(form)

        self._status_label = QLabel("Paste a NIST WebBook IR URL and click Preview.")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        self._preview_label = QLabel("No preview loaded.")
        self._preview_label.setWordWrap(True)
        self._preview_label.setTextInteractionFlags(
            self._preview_label.textInteractionFlags() | Qt.TextInteractionFlag.TextBrowserInteraction
        )
        self._preview_label.setOpenExternalLinks(True)
        layout.addWidget(self._preview_label)

        buttons = QHBoxLayout()
        self._open_source_btn = QPushButton("Open Source Page")
        self._open_source_btn.setEnabled(False)
        self._open_source_btn.clicked.connect(self._on_open_source_page)

        self._preview_btn = QPushButton("Preview")
        self._preview_btn.clicked.connect(self._on_preview)

        self._import_btn = QPushButton("Import")
        self._import_btn.setEnabled(False)
        self._import_btn.clicked.connect(self._on_import)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)

        buttons.addWidget(self._open_source_btn)
        buttons.addStretch()
        buttons.addWidget(self._preview_btn)
        buttons.addWidget(self._import_btn)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

    def _on_url_changed(self) -> None:
        """Invalidate the current preview when the URL changes."""
        self._preview_reference = None
        self._import_btn.setEnabled(False)
        self._open_source_btn.setEnabled(False)
        if self._url_edit.text().strip():
            self._status_label.setText("Click Preview to fetch NIST metadata and JCAMP data.")
        else:
            self._status_label.setText("Paste a NIST WebBook IR URL and click Preview.")
        self._preview_label.setText("No preview loaded.")

    def _on_preview(self) -> None:
        """Fetch and display metadata for the requested web reference."""
        url = self._url_edit.text().strip()
        if not url:
            self._status_label.setText("Enter a NIST WebBook URL first.")
            return
        self._set_busy(True, "Fetching NIST reference preview…")
        try:
            reference = self._preview_client.fetch_reference(url)
        except Exception as exc:  # noqa: BLE001
            self._preview_reference = None
            self._import_btn.setEnabled(False)
            self._open_source_btn.setEnabled(False)
            self._status_label.setText(f"Preview failed: {exc}")
            self._preview_label.setText("No preview loaded.")
            return
        finally:
            self._set_busy(False)

        self._preview_reference = reference
        self._open_source_btn.setEnabled(True)
        self._import_btn.setEnabled(True)
        self._status_label.setText("Preview loaded. Import will store this reference locally.")
        self._preview_label.setText(self._format_preview(reference))

    def _on_import(self) -> None:
        """Store the previewed NIST reference in the local database."""
        if self._preview_reference is None:
            self._status_label.setText("Preview the reference before importing it.")
            return
        self._set_busy(True, "Importing NIST reference…")
        try:
            imported = self._service.store_nist_reference(self._preview_reference)
        except Exception as exc:  # noqa: BLE001
            self._status_label.setText(f"Import failed: {exc}")
            return
        finally:
            self._set_busy(False)

        self._status_label.setText(f"Imported: {imported.name}")
        self.reference_imported.emit(imported.ref_id)
        self.accept()

    def _on_open_source_page(self) -> None:
        """Open the previewed NIST page in the user's browser."""
        if self._preview_reference is None:
            return
        QDesktopServices.openUrl(QUrl(self._preview_reference.page_url))

    def _set_busy(self, busy: bool, message: str = "") -> None:
        """Toggle controls during a blocking network call."""
        if message:
            self._status_label.setText(message)
        self._url_edit.setEnabled(not busy)
        self._preview_btn.setEnabled(not busy)
        self._import_btn.setEnabled(not busy and self._preview_reference is not None)
        self._open_source_btn.setEnabled(not busy and self._preview_reference is not None)
        if busy:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        else:
            QApplication.restoreOverrideCursor()
        QApplication.processEvents()

    @staticmethod
    def _format_preview(reference: NISTWebBookReference) -> str:
        metadata = reference.metadata
        lines = [
            f"Name: {reference.name}",
            f"State: {metadata.get('state', '—') or '—'}",
            f"Sampling: {metadata.get('sampling_procedure', '—') or '—'}",
            f"Path length: {metadata.get('path_length', '—') or '—'}",
            f"Resolution: {metadata.get('resolution', '—') or '—'}",
            f"Origin: {metadata.get('origin', '—') or '—'}",
            f"Owner: {metadata.get('owner', '—') or '—'}",
            f"Y Unit: {reference.spectrum.y_unit.value}",
            f"Points: {reference.spectrum.n_points}",
            f"Source: {reference.page_url}",
        ]
        return "\n".join(lines)
