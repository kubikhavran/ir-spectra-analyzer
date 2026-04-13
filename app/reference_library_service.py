"""Reference-library discovery, import, and similarity search helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.reference_import import BatchImportSummary, ReferenceImportService
from core.spectrum import Spectrum
from matching.search_engine import MatchResult, SearchEngine
from storage.database import Database
from storage.settings import Settings


@dataclass(frozen=True)
class ReferenceSearchOutcome:
    """Structured outcome for a similarity search against the reference library."""

    results: tuple[MatchResult, ...]
    references: tuple[dict, ...]
    imported_summary: BatchImportSummary | None = None
    library_folder: Path | None = None

    @property
    def reference_count(self) -> int:
        """Number of reference spectra available for searching."""
        return len(self.references)


class ReferenceLibraryService:
    """Application-layer service for project reference library workflows."""

    _DEFAULT_LIBRARY_CANDIDATES = (Path("reference library_1"),)

    def __init__(
        self,
        db: Database,
        *,
        settings: Settings | None = None,
        project_root: Path | None = None,
        import_service: ReferenceImportService | None = None,
    ) -> None:
        self._db = db
        self._settings = settings
        self._project_root = project_root or Path(__file__).resolve().parents[1]
        self._import_service = import_service or ReferenceImportService(db)
        self._search_engine = SearchEngine()
        self._selected_library_folder = self._load_selected_library_folder()

    def discover_project_library_folder(self) -> Path | None:
        """Return the currently active reference-library folder."""
        if self._selected_library_folder is not None and self._selected_library_folder.is_dir():
            return self._selected_library_folder
        for candidate in self._DEFAULT_LIBRARY_CANDIDATES:
            folder = (self._project_root / candidate).resolve()
            if folder.is_dir():
                return folder
        return None

    def selected_library_folder(self) -> Path | None:
        """Return the configured active reference-library folder, if any."""
        return self.discover_project_library_folder()

    def set_selected_library_folder(self, folder: Path | None) -> Path | None:
        """Persist and activate the reference-library folder chosen by the user."""
        if folder is None:
            self._selected_library_folder = None
            self._persist_selected_library_folder(None)
            return None

        resolved = folder.expanduser().resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"Folder not found: {resolved}")
        if not resolved.is_dir():
            raise NotADirectoryError(f"Not a folder: {resolved}")

        self._selected_library_folder = resolved
        self._persist_selected_library_folder(resolved)
        return resolved

    def ensure_project_library_imported(self) -> BatchImportSummary | None:
        """Attempt a bundled-library sync based on missing source paths."""
        folder = self.discover_project_library_folder()
        if folder is None:
            return None

        library_files = self._import_service.scan_folder(folder)
        existing_sources = self._existing_reference_sources()
        _missing_files = [
            path
            for path in library_files
            if self._normalize_source_path(path) not in existing_sources
        ]
        return self.import_project_library()

    def import_project_library(self) -> BatchImportSummary | None:
        """Import any missing spectra from the active reference-library folder."""
        folder = self.discover_project_library_folder()
        if folder is None:
            return None

        return self._import_service.batch_import_folder(
            folder,
            skip_duplicates_by_filename=True,
            detect_peaks=False,
            prefer_filename=True,
        )

    def search_spectrum(
        self,
        spectrum: Spectrum,
        *,
        top_n: int | None = 10,
        auto_import_project_library: bool = True,
    ) -> ReferenceSearchOutcome:
        """Search the reference library for spectra similar to the given query spectrum."""
        imported_summary = None
        library_folder = self.discover_project_library_folder()

        if auto_import_project_library and library_folder is not None:
            imported_summary = self.ensure_project_library_imported()

        references = tuple(self.get_library_references())
        if not references:
            return ReferenceSearchOutcome(
                results=(),
                references=(),
                imported_summary=imported_summary,
                library_folder=library_folder,
            )

        self._search_engine.load_references(list(references))
        results = tuple(
            self._search_engine.search(
                spectrum.wavenumbers,
                spectrum.intensities,
                top_n=top_n,
                query_y_unit=spectrum.y_unit,
            )
        )
        return ReferenceSearchOutcome(
            results=results,
            references=references,
            imported_summary=imported_summary,
            library_folder=library_folder,
        )

    def clear_search_cache(self) -> None:
        """Clear cached preprocessed reference vectors."""
        self._search_engine.clear_cache()

    def get_library_references(self) -> list[dict]:
        """Return reference spectra belonging to the active reference-library folder."""
        folder = self.discover_project_library_folder()
        if folder is None:
            return []

        folder_prefix = self._normalize_source_path(folder)
        folder_prefix_with_sep = folder_prefix.rstrip("/\\") + "/"
        references: list[dict] = []
        for ref in self._db.get_reference_spectra():
            source = str(ref.get("source", "")).strip()
            if not source:
                continue
            normalized_source = self._normalize_source_path(Path(source))
            if normalized_source == folder_prefix or normalized_source.startswith(
                folder_prefix_with_sep
            ):
                references.append(ref)
        return references

    def _existing_reference_sources(self) -> set[str]:
        """Return normalized source paths already present in the reference DB."""
        sources: set[str] = set()
        for ref in self._db.get_reference_spectra():
            source = str(ref.get("source", "")).strip()
            if source:
                sources.add(self._normalize_source_path(Path(source)))
        return sources

    @staticmethod
    def _normalize_source_path(path: Path) -> str:
        """Normalize paths for duplicate comparison across repeated syncs."""
        try:
            return str(path.expanduser().resolve(strict=False)).replace("\\", "/").casefold()
        except OSError:
            return str(path).replace("\\", "/").casefold()

    def _load_selected_library_folder(self) -> Path | None:
        """Load the persisted active library folder from settings, if available."""
        if self._settings is None:
            return None
        raw_path = self._settings.get("reference_library_folder")
        if not raw_path:
            return None
        path = Path(str(raw_path)).expanduser()
        return path.resolve() if path.exists() else None

    def _persist_selected_library_folder(self, folder: Path | None) -> None:
        """Persist the active library folder back into user settings."""
        if self._settings is None:
            return
        self._settings.set("reference_library_folder", None if folder is None else str(folder))
