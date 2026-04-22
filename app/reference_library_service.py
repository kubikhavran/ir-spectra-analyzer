"""Reference-library discovery, import, and similarity search helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.reference_import import (
    BatchImportResult,
    BatchImportStatus,
    BatchImportSummary,
    ReferenceImportService,
)
from core.spectrum import Spectrum
from matching.feature_store import MATCH_FEATURE_VERSION, compute_search_vector
from matching.search_engine import MatchResult, SearchEngine
from storage.database import Database
from storage.settings import Settings
from utils.file_utils import normalize_source_path


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
        self._reference_spectrum_cache: dict[int, dict] = {}
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

    @property
    def project_root(self) -> Path:
        """Return the service project root used for default library discovery."""
        return self._project_root

    def set_selected_library_folder(self, folder: Path | None) -> Path | None:
        """Persist and activate the reference-library folder chosen by the user."""
        if folder is None:
            self._selected_library_folder = None
            self._persist_selected_library_folder(None)
            self.clear_search_cache()
            return None

        resolved = folder.expanduser().resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"Folder not found: {resolved}")
        if not resolved.is_dir():
            raise NotADirectoryError(f"Not a folder: {resolved}")

        self._selected_library_folder = resolved
        self._persist_selected_library_folder(resolved)
        self.clear_search_cache()
        return resolved

    def ensure_project_library_imported(self) -> BatchImportSummary | None:
        """Attempt a bundled-library sync based on missing source paths."""
        folder = self.discover_project_library_folder()
        if folder is None:
            return None

        library_files = self._import_service.scan_folder(folder)
        existing_sources = self._existing_reference_sources()
        up_to_date_results: list[BatchImportResult] = []
        needs_sync = False
        for path in library_files:
            normalized = normalize_source_path(path)
            existing = existing_sources.get(normalized)
            if existing is None:
                needs_sync = True
                break

            stat = path.stat()
            stored_mtime_ns = int(existing.get("source_mtime_ns") or 0)
            stored_size = int(existing.get("source_size") or 0)
            if (
                stored_mtime_ns != 0
                and stored_size != 0
                and (
                    stored_mtime_ns != stat.st_mtime_ns
                    or stored_size != stat.st_size
                )
            ):
                needs_sync = True
                break

            up_to_date_results.append(
                BatchImportResult(
                    path=path,
                    status=BatchImportStatus.SKIPPED,
                    reference_name=path.stem,
                    reason="source path already imported",
                )
            )

        if not needs_sync:
            return BatchImportSummary(folder=folder, results=tuple(up_to_date_results))
        return self.import_project_library()

    def import_project_library(self) -> BatchImportSummary | None:
        """Import any missing spectra from the active reference-library folder."""
        folder = self.discover_project_library_folder()
        if folder is None:
            return None

        summary = self._import_service.batch_import_folder(
            folder,
            skip_duplicates_by_filename=True,
            detect_peaks=False,
            prefer_filename=True,
        )
        self.clear_search_cache()
        return summary

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

        source_prefix = normalize_source_path(library_folder) if library_folder is not None else None
        self._refresh_missing_features(source_prefix=source_prefix)
        search_rows = self._db.get_reference_search_rows(
            source_prefix=source_prefix,
            feature_version=MATCH_FEATURE_VERSION,
        )
        self._search_engine.load_references(search_rows)
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
        self._reference_spectrum_cache.clear()

    def get_library_references(self) -> list[dict]:
        """Return reference spectra belonging to the active reference-library folder."""
        folder = self.discover_project_library_folder()
        if folder is None:
            return []

        return self._db.get_reference_metadata(source_prefix=normalize_source_path(folder))

    def get_reference_spectrum(self, ref_id: int) -> dict | None:
        """Return one fully decoded reference spectrum, cached for overlays/previews."""
        cached = self._reference_spectrum_cache.get(int(ref_id))
        if cached is not None:
            return dict(cached)

        ref = self._db.get_reference_spectrum_by_id(int(ref_id))
        if ref is None:
            return None
        self._reference_spectrum_cache[int(ref_id)] = dict(ref)
        return ref

    def _existing_reference_sources(self) -> dict[str, dict]:
        """Return normalized source paths already present in the reference DB."""
        sources: dict[str, dict] = {}
        for ref in self._db.get_reference_identity_rows():
            source = str(ref.get("source_norm", "")).strip()
            if source:
                sources[source] = dict(ref)
        return sources

    def _refresh_missing_features(self, *, source_prefix: str | None) -> None:
        """Backfill persistent search vectors for library rows missing the current feature version."""
        missing = self._db.get_references_missing_features(
            source_prefix=source_prefix,
            feature_version=MATCH_FEATURE_VERSION,
        )
        if not missing:
            return

        for ref in missing:
            self._db.upsert_reference_feature(
                int(ref["id"]),
                feature_version=MATCH_FEATURE_VERSION,
                feature_vector=compute_search_vector(
                    ref["wavenumbers"],
                    ref["intensities"],
                    y_unit=ref.get("y_unit"),
                ),
                commit=False,
            )
        self._db.commit()

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
