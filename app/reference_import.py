"""Reference spectrum import helpers for single-file and batch workflows."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from core.peak import Peak
from core.spectrum import Spectrum
from matching.feature_store import MATCH_FEATURE_VERSION, compute_search_vector
from storage.database import Database
from utils.file_utils import normalize_source_path


class BatchImportStatus(StrEnum):
    """Outcome of processing a single file in a batch import run."""

    IMPORTED = "imported"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True)
class ImportedReference:
    """Metadata about a successfully imported reference spectrum."""

    ref_id: int
    name: str
    path: Path
    detected_peaks: tuple[Peak, ...] = ()


@dataclass(frozen=True)
class BatchImportResult:
    """Outcome for a single file processed during batch import."""

    path: Path
    status: BatchImportStatus
    reference_name: str = ""
    reason: str = ""
    ref_id: int | None = None
    detected_peaks: tuple[Peak, ...] = ()


@dataclass(frozen=True)
class BatchImportSummary:
    """Structured batch import results suitable for UI summaries and future export flows."""

    folder: Path
    results: tuple[BatchImportResult, ...]

    @property
    def total_found(self) -> int:
        """Total number of supported spectrum files discovered in the selected folder."""
        return len(self.results)

    @property
    def imported(self) -> int:
        """Count of successfully imported files."""
        return sum(result.status == BatchImportStatus.IMPORTED for result in self.results)

    @property
    def skipped(self) -> int:
        """Count of files skipped as duplicates or by policy."""
        return sum(result.status == BatchImportStatus.SKIPPED for result in self.results)

    @property
    def failed(self) -> int:
        """Count of files that failed to import."""
        return sum(result.status == BatchImportStatus.FAILED for result in self.results)


class ReferenceImportService:
    """Application-layer helper for importing reference spectra into the database."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def scan_folder(self, folder: Path) -> list[Path]:
        """Return all readable spectrum files under a folder (recursively), sorted.

        Scans subfolders as well and accepts every format the app can read
        (``.spa`` plus JCAMP ``.jdx``/``.dx``), so a whole library tree — not
        just top-level ``.spa`` files — is discovered.
        """
        if not folder.exists():
            raise FileNotFoundError(f"Folder not found: {folder}")
        if not folder.is_dir():
            raise NotADirectoryError(f"Not a folder: {folder}")

        from file_io.format_registry import FormatRegistry  # noqa: PLC0415

        extensions = FormatRegistry().supported_extensions()
        return sorted(
            path
            for path in folder.rglob("*")
            if path.is_file() and path.suffix.lower() in extensions
        )

    @staticmethod
    def _unique_name(base: str, used: set[str]) -> str:
        """Return a name not already present in ``used`` (case-insensitive).

        Distinct files that happen to share a filename (common in large
        libraries organised into subfolders) must all be imported, so a
        colliding name is disambiguated as ``name (2)``, ``name (3)``, … rather
        than dropping the file.
        """
        if base.casefold() not in used:
            return base
        index = 2
        while f"{base} ({index})".casefold() in used:
            index += 1
        return f"{base} ({index})"

    def import_reference_file(
        self,
        path: Path,
        *,
        name: str | None = None,
        detect_peaks: bool = False,
        prefer_filename: bool = False,
        commit: bool = True,
        used_names: set[str] | None = None,
    ) -> ImportedReference:
        """Import a single spectral file into the reference library."""
        spectrum = self._read_spectrum(path)
        reference_name = name or self._default_reference_name(
            path,
            spectrum,
            prefer_filename=prefer_filename,
        )
        if used_names is not None:
            reference_name = self._unique_name(reference_name, used_names)
        detected_peaks = detect_peaks_for_spectrum(spectrum) if detect_peaks else ()
        description = spectrum.comments.strip()
        stat = path.stat()
        with self._db.savepoint():
            ref_id = self._db.add_reference_spectrum(
                name=reference_name,
                wavenumbers=spectrum.wavenumbers,
                intensities=spectrum.intensities,
                description=description,
                source=str(path),
                y_unit=spectrum.y_unit.value,
                source_mtime_ns=stat.st_mtime_ns,
                source_size=stat.st_size,
                commit=False,
            )
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
        if used_names is not None:
            used_names.add(reference_name.casefold())
        if commit:
            self._db.commit()
        return ImportedReference(
            ref_id=ref_id,
            name=reference_name,
            path=path,
            detected_peaks=detected_peaks,
        )

    def batch_import_folder(
        self,
        folder: Path,
        *,
        skip_duplicates_by_filename: bool = True,
        detect_peaks: bool = False,
        prefer_filename: bool = False,
    ) -> BatchImportSummary:
        """Import all supported spectrum files from a folder and return a summary."""
        files = self.scan_folder(folder)
        existing_names: set[str] = set()
        existing_sources: dict[str, dict] = {}

        if skip_duplicates_by_filename:
            existing_names, existing_sources = self._existing_reference_keys()

        results: list[BatchImportResult] = []
        wrote_changes = False
        # Every distinct file must be imported. Deduplication is therefore keyed
        # on the SOURCE PATH (the same file already stored), never on the display
        # name — many spectra legitimately share a name (identical filename in
        # different subfolders, or a shared embedded title), and those used to be
        # silently skipped, so a large library only partially imported.
        used_names = existing_names if skip_duplicates_by_filename else None
        for path in files:
            try:
                normalized_source = normalize_source_path(path)
                stat = path.stat()
            except Exception as exc:  # noqa: BLE001
                results.append(
                    BatchImportResult(
                        path=path,
                        status=BatchImportStatus.FAILED,
                        reference_name=path.stem,
                        reason=self._format_error(exc),
                    )
                )
                continue
            existing_source_row = existing_sources.get(normalized_source)

            if skip_duplicates_by_filename and existing_source_row is not None:
                stored_mtime_ns = int(existing_source_row.get("source_mtime_ns") or 0)
                stored_size = int(existing_source_row.get("source_size") or 0)
                if (stored_mtime_ns == 0 and stored_size == 0) or (
                    stored_mtime_ns == stat.st_mtime_ns and stored_size == stat.st_size
                ):
                    results.append(
                        BatchImportResult(
                            path=path,
                            status=BatchImportStatus.SKIPPED,
                            reference_name=path.stem,
                            reason="source path already imported",
                        )
                    )
                    continue

            try:
                if existing_source_row is not None:
                    imported = self._update_reference_file(
                        int(existing_source_row["id"]),
                        path,
                        detect_peaks=detect_peaks,
                        prefer_filename=prefer_filename,
                    )
                else:
                    imported = self.import_reference_file(
                        path,
                        detect_peaks=detect_peaks,
                        prefer_filename=prefer_filename,
                        commit=False,
                        used_names=used_names,
                    )
            except Exception as exc:  # noqa: BLE001
                results.append(
                    BatchImportResult(
                        path=path,
                        status=BatchImportStatus.FAILED,
                        reference_name=path.stem,
                        reason=self._format_error(exc),
                    )
                )
                continue

            wrote_changes = True
            results.append(
                BatchImportResult(
                    path=path,
                    status=BatchImportStatus.IMPORTED,
                    reference_name=imported.name,
                    ref_id=imported.ref_id,
                    detected_peaks=imported.detected_peaks,
                )
            )
            # import_reference_file already registered the final (possibly
            # disambiguated) name in used_names; just track the source path.
            existing_sources[normalized_source] = {
                "id": imported.ref_id,
                "source_mtime_ns": stat.st_mtime_ns,
                "source_size": stat.st_size,
            }

        if wrote_changes:
            self._db.commit()

        return BatchImportSummary(folder=folder, results=tuple(results))

    def _read_spectrum(self, path: Path) -> Spectrum:
        """Read a spectrum using the fast library-import path.

        For reference-library indexing, prefer the lightweight binary parser and
        only fall back to the general format-registry path when necessary.
        """
        if path.suffix.lower() == ".spa":
            try:
                from file_io.spa_binary import SPABinaryReader  # noqa: PLC0415

                return SPABinaryReader().read(path)
            except Exception:  # noqa: BLE001
                pass

        from file_io.format_registry import FormatRegistry  # noqa: PLC0415

        return FormatRegistry().read(path)

    @staticmethod
    def _default_reference_name(
        path: Path,
        spectrum: Spectrum,
        *,
        prefer_filename: bool = False,
    ) -> str:
        """Return the preferred stored reference name for an imported spectrum."""
        if prefer_filename:
            return path.stem
        title = spectrum.title.strip()
        if title and title.casefold() != path.name.casefold():
            return title
        if title:
            return title
        return path.stem

    def _existing_reference_keys(self) -> tuple[set[str], dict[str, dict]]:
        """Return normalized existing reference names and source paths for duplicate checks."""
        names: set[str] = set()
        sources: dict[str, dict] = {}
        for ref in self._db.get_reference_identity_rows():
            name = str(ref.get("name", "")).strip()
            if name:
                names.add(name.casefold())
            source_norm = str(ref.get("source_norm", "")).strip()
            if source_norm:
                sources[source_norm] = dict(ref)
        return names, sources

    def _update_reference_file(
        self,
        ref_id: int,
        path: Path,
        *,
        detect_peaks: bool,
        prefer_filename: bool,
    ) -> ImportedReference:
        """Refresh an existing reference row from a changed source file."""
        spectrum = self._read_spectrum(path)
        reference_name = self._default_reference_name(
            path,
            spectrum,
            prefer_filename=prefer_filename,
        )
        detected_peaks = detect_peaks_for_spectrum(spectrum) if detect_peaks else ()
        stat = path.stat()
        with self._db.savepoint():
            self._db.update_reference_spectrum(
                ref_id,
                name=reference_name,
                wavenumbers=spectrum.wavenumbers,
                intensities=spectrum.intensities,
                description=spectrum.comments.strip(),
                source=str(path),
                y_unit=spectrum.y_unit.value,
                source_mtime_ns=stat.st_mtime_ns,
                source_size=stat.st_size,
                commit=False,
            )
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
        return ImportedReference(
            ref_id=ref_id,
            name=reference_name,
            path=path,
            detected_peaks=detected_peaks,
        )

    @staticmethod
    def _format_error(exc: Exception) -> str:
        """Return a concise one-line error message for UI display."""
        message = str(exc).strip()
        if not message:
            return exc.__class__.__name__
        return message.splitlines()[0]


def detect_peaks_for_spectrum(spectrum: Spectrum) -> tuple[Peak, ...]:
    """Run the application's standard peak detection on a Spectrum."""
    from processing.peak_detection import default_prominence, detect_peaks  # noqa: PLC0415

    return tuple(
        detect_peaks(
            spectrum.wavenumbers,
            spectrum.intensities,
            prominence=default_prominence(spectrum),
            invert=spectrum.is_dip_spectrum,
        )
    )
