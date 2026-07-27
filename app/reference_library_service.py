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

# Provider tag for references that come from an analysed project rather than
# from a file inside the selected library folder. Search scoping treats any
# non-"local" provider as always in scope (same mechanism as web references),
# so an analysed spectrum stays matchable no matter which library folder is
# selected and without copying the source file into it.
PROJECT_SOURCE_PROVIDER = "project"


@dataclass(frozen=True)
class ProjectReferenceRegistration:
    """Outcome of registering an analysed project as a searchable reference."""

    name: str
    status: str  # "added" | "updated" | "skipped"
    ref_id: int | None = None
    reason: str = ""


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
    _RERANK_CANDIDATE_COUNT = 25

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
        # (source_prefix, include_web_refs, (count, max_id)) of the currently
        # loaded search matrix — lets repeated searches skip the BLOB reload.
        self._loaded_search_state: tuple | None = None
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
                and (stored_mtime_ns != stat.st_mtime_ns or stored_size != stat.st_size)
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
        name_filter: str | None = None,
    ) -> ReferenceSearchOutcome:
        """Search the reference library for spectra similar to the given query spectrum.

        When ``name_filter`` is set, only references whose name contains that
        substring are searched — a fast way to scope a huge library to one
        client/series (e.g. "NIT") without loading every feature vector.
        """
        imported_summary = None
        library_folder = self.discover_project_library_folder()
        source_prefix = (
            normalize_source_path(library_folder) if library_folder is not None else None
        )
        include_web_refs = library_folder is not None
        name_filter = (name_filter or "").strip() or None

        # Whether the folder needs first-time population is decided on the whole
        # scope, independent of any name filter.
        full_state = self._db.get_reference_library_state(
            source_prefix=source_prefix,
            include_web_refs=include_web_refs,
            feature_version=MATCH_FEATURE_VERSION,
        )

        # Auto-import walks the whole library folder (recursive scan + stat of
        # every file), which is very slow for large libraries. Only do it when
        # the scope is still empty (first-time population) — once the library is
        # filled, matching skips the folder walk and the user refreshes it
        # explicitly via "Sync Folder".
        if auto_import_project_library and library_folder is not None and full_state[0] == 0:
            imported_summary = self.ensure_project_library_imported()

        if full_state[0] == 0 and not self._db.get_reference_identity_rows():
            return ReferenceSearchOutcome(
                results=(),
                references=(),
                imported_summary=imported_summary,
                library_folder=library_folder,
            )

        self._refresh_missing_features(
            source_prefix=source_prefix,
            include_web_refs=include_web_refs,
        )
        # Re-fetching every feature BLOB and rebuilding the reference matrix is
        # the dominant per-search cost on large libraries. Skip it entirely
        # when the searchable (name-filtered) library has not changed since the
        # last load.
        library_state = self._db.get_reference_library_state(
            source_prefix=source_prefix,
            include_web_refs=include_web_refs,
            feature_version=MATCH_FEATURE_VERSION,
            name_filter=name_filter,
        )
        search_state_key = (source_prefix, include_web_refs, name_filter, library_state)
        if search_state_key != self._loaded_search_state or self._search_engine.n_references == 0:
            search_rows = self._db.get_reference_search_rows(
                source_prefix=source_prefix,
                include_web_refs=include_web_refs,
                feature_version=MATCH_FEATURE_VERSION,
                name_filter=name_filter,
            )
            self._search_engine.load_references(search_rows)
            self._loaded_search_state = search_state_key
        coarse_top_n = None if top_n is None else max(int(top_n), self._RERANK_CANDIDATE_COUNT)
        coarse_results = tuple(
            self._search_engine.search(
                spectrum.wavenumbers,
                spectrum.intensities,
                top_n=coarse_top_n,
                query_y_unit=spectrum.y_unit,
            )
        )
        results = tuple(self._rerank_results(spectrum, coarse_results=coarse_results, top_n=top_n))
        return ReferenceSearchOutcome(
            results=results,
            references=tuple(self.get_library_references()),
            imported_summary=imported_summary,
            library_folder=library_folder,
        )

    def register_project_spectrum(
        self,
        *,
        name: str,
        spectrum: Spectrum,
        source_path: Path | str,
        description: str = "",
    ) -> ProjectReferenceRegistration:
        """Make an analysed project's spectrum searchable by Match Spectrum.

        The spectrum is stored in the reference library under ``name`` — use the
        saved project's file stem, so "Apply assignments from match" finds the
        matching ``.irproj`` afterwards. Re-registering the same project updates
        its row instead of adding a second one.

        A spectrum already present as a plain library file is left alone: it is
        matchable already, and a second row would only duplicate the hit list.
        """
        clean_name = name.strip()
        if not clean_name:
            return ProjectReferenceRegistration(
                name=name, status="skipped", reason="empty reference name"
            )

        normalized_source = normalize_source_path(str(source_path))
        rows = self._db.get_reference_identity_rows()
        same_source = next(
            (row for row in rows if str(row.get("source_norm", "")) == normalized_source),
            None,
        )
        same_name = next(
            (
                row
                for row in rows
                if str(row.get("name", "")).strip().casefold() == clean_name.casefold()
            ),
            None,
        )
        existing = same_source or same_name
        if (
            existing is not None
            and existing is not same_source
            and str(existing.get("source_provider") or "local") == "local"
        ):
            return ProjectReferenceRegistration(
                name=clean_name,
                status="skipped",
                ref_id=int(existing["id"]),
                reason="already in the reference library as a library file",
            )

        y_unit = spectrum.y_unit.value
        if existing is None:
            ref_id = self._db.add_reference_spectrum(
                name=clean_name,
                wavenumbers=spectrum.wavenumbers,
                intensities=spectrum.intensities,
                description=description,
                source=str(source_path),
                y_unit=y_unit,
                source_provider=PROJECT_SOURCE_PROVIDER,
                commit=False,
            )
            status = "added"
        else:
            ref_id = int(existing["id"])
            self._db.update_reference_spectrum(
                ref_id,
                name=clean_name,
                wavenumbers=spectrum.wavenumbers,
                intensities=spectrum.intensities,
                description=description,
                source=str(source_path),
                y_unit=y_unit,
                source_provider=PROJECT_SOURCE_PROVIDER,
                commit=False,
            )
            status = "updated"

        self._db.upsert_reference_feature(
            ref_id,
            feature_version=MATCH_FEATURE_VERSION,
            feature_vector=compute_search_vector(
                spectrum.wavenumbers,
                spectrum.intensities,
                y_unit=spectrum.y_unit,
            ),
            commit=False,
        )
        self._db.commit()
        self.clear_search_cache()
        return ProjectReferenceRegistration(name=clean_name, status=status, ref_id=ref_id)

    def clear_search_cache(self) -> None:
        """Clear cached preprocessed reference vectors."""
        self._search_engine.clear_cache()
        self._reference_spectrum_cache.clear()
        self._loaded_search_state = None

    def get_library_references(self) -> list[dict]:
        """Return reference spectra belonging to the active reference-library folder."""
        folder = self.discover_project_library_folder()
        if folder is None:
            return self._db.get_reference_metadata()

        return self._db.get_reference_metadata(
            source_prefix=normalize_source_path(folder),
            include_web_refs=True,
        )

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

    def _refresh_missing_features(
        self,
        *,
        source_prefix: str | None,
        include_web_refs: bool,
    ) -> None:
        """Backfill persistent search vectors for library rows missing the current feature version."""
        missing = self._db.get_references_missing_features(
            source_prefix=source_prefix,
            include_web_refs=include_web_refs,
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

    def _rerank_results(
        self,
        spectrum: Spectrum,
        *,
        coarse_results: tuple[MatchResult, ...],
        top_n: int | None,
    ) -> list[MatchResult]:
        """Refine the top coarse candidates on a finer 1 cm⁻¹ grid."""
        if not coarse_results:
            return []

        shortlist_size = min(len(coarse_results), self._RERANK_CANDIDATE_COUNT)
        hydrated_candidates: list[dict] = []
        coarse_scores: dict[int, float] = {}
        for result in coarse_results[:shortlist_size]:
            ref = self.get_reference_spectrum(result.ref_id)
            if ref is None:
                continue
            hydrated_candidates.append(ref)
            coarse_scores[result.ref_id] = result.score

        if not hydrated_candidates:
            return list(coarse_results if top_n is None else coarse_results[:top_n])

        reranked = self._search_engine.rerank_candidates(
            spectrum.wavenumbers,
            spectrum.intensities,
            hydrated_candidates,
            query_y_unit=spectrum.y_unit,
            coarse_scores=coarse_scores,
        )
        reranked_ids = {result.ref_id for result in reranked}

        combined: list[MatchResult] = list(reranked)
        for result in coarse_results:
            if result.ref_id in reranked_ids:
                continue
            combined.append(result)

        combined.sort(key=lambda result: result.score, reverse=True)
        if top_n is None:
            return combined
        return combined[:top_n]

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
