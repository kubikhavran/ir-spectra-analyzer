"""Background worker for batch PDF export from raw spectra."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from app.batch_pdf_export import BatchPDFExporter
from reporting.pdf_generator import ReportOptions


class BatchPDFExportWorker(QObject):
    """Run bulk PDF export on a worker thread."""

    completed = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(
        self,
        *,
        input_folder: str | Path,
        output_folder: str | Path,
        detect_peaks: bool,
        report_options: ReportOptions,
        overwrite_mode: str,
    ) -> None:
        super().__init__()
        self._input_folder = input_folder
        self._output_folder = output_folder
        self._detect_peaks = detect_peaks
        self._report_options = report_options
        self._overwrite_mode = overwrite_mode

    @Slot()
    def run(self) -> None:
        exporter = BatchPDFExporter()
        try:
            summary = exporter.export_folder(
                self._input_folder,
                self._output_folder,
                detect_peaks=self._detect_peaks,
                report_options=self._report_options,
                overwrite_mode=self._overwrite_mode,
            )
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
        else:
            self.completed.emit(summary)
        finally:
            self.finished.emit()
