"""Background workers for reference-library sync and similarity search."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, Signal, Slot

from app.reference_library_service import ReferenceLibraryService
from core.spectrum import Spectrum
from storage.database import Database


class ReferenceLibrarySearchWorker(QObject):
    """Run a reference-library similarity search in a worker thread."""

    completed = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(
        self,
        *,
        db_path: str | Path,
        project_root: Path,
        selected_library_folder: Path | None,
        spectrum: Spectrum,
        top_n: int | None,
        auto_import_project_library: bool,
    ) -> None:
        super().__init__()
        self._db_path = db_path
        self._project_root = project_root
        self._selected_library_folder = selected_library_folder
        self._top_n = top_n
        self._auto_import_project_library = auto_import_project_library
        self._spectrum = Spectrum(
            wavenumbers=np.asarray(spectrum.wavenumbers, dtype=np.float64).copy(),
            intensities=np.asarray(spectrum.intensities, dtype=np.float64).copy(),
            title=spectrum.title,
            source_path=spectrum.source_path,
            acquired_at=spectrum.acquired_at,
            y_unit=spectrum.y_unit,
            x_unit=spectrum.x_unit,
            comments=spectrum.comments,
            extra_metadata=dict(spectrum.extra_metadata),
        )

    @Slot()
    def run(self) -> None:
        db = Database(self._db_path)
        try:
            db.initialize()
            service = ReferenceLibraryService(db, project_root=self._project_root)
            if self._selected_library_folder is not None:
                service.set_selected_library_folder(self._selected_library_folder)
            outcome = service.search_spectrum(
                self._spectrum,
                top_n=self._top_n,
                auto_import_project_library=self._auto_import_project_library,
            )
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
        else:
            self.completed.emit(outcome)
        finally:
            db.close()
            self.finished.emit()


class ReferenceLibrarySyncWorker(QObject):
    """Run a reference-library folder sync in a worker thread."""

    completed = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(
        self,
        *,
        db_path: str | Path,
        project_root: Path,
        selected_library_folder: Path | None,
    ) -> None:
        super().__init__()
        self._db_path = db_path
        self._project_root = project_root
        self._selected_library_folder = selected_library_folder

    @Slot()
    def run(self) -> None:
        db = Database(self._db_path)
        try:
            db.initialize()
            service = ReferenceLibraryService(db, project_root=self._project_root)
            if self._selected_library_folder is not None:
                service.set_selected_library_folder(self._selected_library_folder)
            summary = service.import_project_library()
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
        else:
            self.completed.emit(summary)
        finally:
            db.close()
            self.finished.emit()
