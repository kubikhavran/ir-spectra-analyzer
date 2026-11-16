"""Background workers for reference-library sync and similarity search."""

from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, Signal, Slot

from app.reference_library_service import ReferenceLibraryService
from core.spectrum import Spectrum
from storage.database import Database

_WORKER_CACHE_LOCK = threading.Lock()
_WORKER_SERVICE_CACHE: dict[tuple[str, str], tuple[tuple[int, int], ReferenceLibraryService]] = {}


def _db_file_fingerprint(db_path: str | Path) -> tuple[int, int] | None:
    """Return (mtime_ns, size) for a file-backed SQLite database, or None."""
    try:
        stat = Path(db_path).stat()
    except OSError:
        return None
    return (int(stat.st_mtime_ns), int(stat.st_size))


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
        name_filter: str | None = None,
    ) -> None:
        super().__init__()
        self._db_path = db_path
        self._project_root = project_root
        self._selected_library_folder = selected_library_folder
        self._top_n = top_n
        self._auto_import_project_library = auto_import_project_library
        self._name_filter = name_filter
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
        cache_key = (
            str(Path(self._db_path).resolve()),
            str(self._project_root.resolve()),
        )
        service: ReferenceLibraryService | None = None
        try:
            db.initialize()
            fingerprint = _db_file_fingerprint(self._db_path)
            with _WORKER_CACHE_LOCK:
                cached = _WORKER_SERVICE_CACHE.pop(cache_key, None)
            if cached is not None and fingerprint is not None and cached[0] == fingerprint:
                service = cached[1]
                service._db = db
                service._import_service._db = db
            else:
                service = ReferenceLibraryService(db, project_root=self._project_root)
            if self._selected_library_folder is not None:
                resolved_folder = self._selected_library_folder.expanduser().resolve()
                if service._selected_library_folder != resolved_folder:
                    service.set_selected_library_folder(self._selected_library_folder)
            elif service._selected_library_folder is not None:
                service.set_selected_library_folder(None)
            outcome = service.search_spectrum(
                self._spectrum,
                top_n=self._top_n,
                auto_import_project_library=self._auto_import_project_library,
                name_filter=self._name_filter,
            )
            post_fingerprint = _db_file_fingerprint(self._db_path)
            if post_fingerprint is not None:
                with _WORKER_CACHE_LOCK:
                    _WORKER_SERVICE_CACHE[cache_key] = (post_fingerprint, service)
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
            with _WORKER_CACHE_LOCK:
                _WORKER_SERVICE_CACHE.clear()
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
