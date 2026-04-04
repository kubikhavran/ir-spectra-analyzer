"""Reference spectrum import helpers for single-file and batch workflows."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from core.peak import Peak
from core.spectrum import Spectrum
from storage.database import Database


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
        """Total number of `.spa` files discovered in the selected folder."""
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
        """Return non-recursive `.spa` files from a folder, sorted by filename."""
        if not folder.exists():
            raise FileNotFoundError(f"Folder not found: {folder}")
        if not folder.is_dir():
            raise NotADirectoryError(f"Not a folder: {folder}")
        return sorted(
            path for path in folder.iterdir() if path.is_file() and path.suffix.lower() == ".spa"
        )

    def import_reference_file(
        self,
        path: Path,
        *,
        name: str | None = None,
        detect_peaks: bool = False,
    ) -> ImportedReference:
        """Import a single spectral file into the reference library."""
        spectrum = self._read_spectrum(path)
        reference_name = name or self._default_reference_name(path, spectrum)
        detected_peaks = detect_peaks_for_spectrum(spectrum) if detect_peaks else ()
        description = spectrum.comments.strip()
        ref_id = self._db.add_reference_spectrum(
            name=reference_name,
            wavenumbers=spectrum.wavenumbers,
            intensities=spectrum.intensities,
            description=description,
            source=str(path),
            y_unit=spectrum.y_unit.value,
        )
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
    ) -> BatchImportSummary:
        """Import all `.spa` files from a folder and return a structured summary."""
        files = self.scan_folder(folder)
        existing_names: set[str] = set()
        existing_sources: set[str] = set()

        if skip_duplicates_by_filename:
            existing_names, existing_sources = self._existing_reference_keys()

        results: list[BatchImportResult] = []
        for path in files:
            normalized_name = path.stem.casefold()
            normalized_source = self._normalize_source_path(path)

            if skip_duplicates_by_filename:
                if normalized_source in existing_sources:
                    results.append(
                        BatchImportResult(
                            path=path,
                            status=BatchImportStatus.SKIPPED,
                            reference_name=path.stem,
                            reason="source path already imported",
                        )
                    )
                    continue
                if normalized_name in existing_names:
                    results.append(
                        BatchImportResult(
                            path=path,
                            status=BatchImportStatus.SKIPPED,
                            reference_name=path.stem,
                            reason="reference name already exists",
                        )
                    )
                    continue

            try:
                imported = self.import_reference_file(path, detect_peaks=detect_peaks)
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

            results.append(
                BatchImportResult(
                    path=path,
                    status=BatchImportStatus.IMPORTED,
                    reference_name=imported.name,
                    ref_id=imported.ref_id,
                    detected_peaks=imported.detected_peaks,
                )
            )
            existing_names.add(normalized_name)
            existing_names.add(imported.name.casefold())
            existing_sources.add(normalized_source)

        return BatchImportSummary(folder=folder, results=tuple(results))

    def _read_spectrum(self, path: Path) -> Spectrum:
        """Read a spectrum using the application's registered file-import pipeline."""
        from file_io.format_registry import FormatRegistry  # noqa: PLC0415

        return FormatRegistry().read(path)

    @staticmethod
    def _default_reference_name(path: Path, spectrum: Spectrum) -> str:
        """Prefer meaningful spectrum metadata, otherwise fall back to the filename stem."""
        title = spectrum.title.strip()
        if title and title.casefold() != path.name.casefold():
            return title
        if title:
            return title
        return path.stem

    def _existing_reference_keys(self) -> tuple[set[str], set[str]]:
        """Return normalized existing reference names and source paths for duplicate checks."""
        names: set[str] = set()
        sources: set[str] = set()
        for ref in self._db.get_reference_spectra():
            name = str(ref.get("name", "")).strip()
            if name:
                names.add(name.casefold())
            source = str(ref.get("source", "")).strip()
            if source:
                sources.add(self._normalize_source_path(Path(source)))
        return names, sources

    @staticmethod
    def _normalize_source_path(path: Path) -> str:
        """Normalize paths for duplicate comparison across repeated imports."""
        try:
            return str(path.expanduser().resolve(strict=False)).casefold()
        except OSError:
            return str(path).casefold()

    @staticmethod
    def _format_error(exc: Exception) -> str:
        """Return a concise one-line error message for UI display."""
        message = str(exc).strip()
        if not message:
            return exc.__class__.__name__
        return message.splitlines()[0]


def detect_peaks_for_spectrum(spectrum: Spectrum) -> tuple[Peak, ...]:
    """Run the application's standard peak detection on a Spectrum."""
    from processing.peak_detection import detect_peaks  # noqa: PLC0415

    return tuple(detect_peaks(spectrum.wavenumbers, spectrum.intensities))
