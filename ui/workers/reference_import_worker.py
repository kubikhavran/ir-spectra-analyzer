"""Background workers for batch reference import."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from app.reference_import import ReferenceImportService
from storage.database import Database


class ReferenceBatchImportWorker(QObject):
    """Run batch reference import in a worker thread."""

    completed = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(
        self,
        *,
        db_path: str | Path,
        folder: Path,
        skip_duplicates_by_filename: bool,
        detect_peaks: bool,
    ) -> None:
        super().__init__()
        self._db_path = db_path
        self._folder = folder
        self._skip_duplicates_by_filename = skip_duplicates_by_filename
        self._detect_peaks = detect_peaks

    @Slot()
    def run(self) -> None:
        db = Database(self._db_path)
        try:
            db.initialize()
            service = ReferenceImportService(db)
            summary = service.batch_import_folder(
                self._folder,
                skip_duplicates_by_filename=self._skip_duplicates_by_filename,
                detect_peaks=self._detect_peaks,
            )
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
        else:
            self.completed.emit(summary)
        finally:
            db.close()
            self.finished.emit()
