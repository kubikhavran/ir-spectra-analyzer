"""Background worker for batch PDF export from saved projects."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from app.batch_project_pdf_export import BatchProjectPDFExporter
from reporting.pdf_generator import ReportOptions


class BatchProjectPDFExportWorker(QObject):
    """Run bulk project-PDF export on a worker thread."""

    completed = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(
        self,
        *,
        input_folder: str | Path,
        output_folder: str | Path,
        report_options: ReportOptions,
        overwrite_mode: str,
    ) -> None:
        super().__init__()
        self._input_folder = input_folder
        self._output_folder = output_folder
        self._report_options = report_options
        self._overwrite_mode = overwrite_mode

    @Slot()
    def run(self) -> None:
        exporter = BatchProjectPDFExporter()
        try:
            summary = exporter.export_folder(
                self._input_folder,
                self._output_folder,
                report_options=self._report_options,
                overwrite_mode=self._overwrite_mode,
            )
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
        else:
            self.completed.emit(summary)
        finally:
            self.finished.emit()
