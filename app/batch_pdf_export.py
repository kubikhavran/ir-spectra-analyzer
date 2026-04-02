"""Application-layer bulk PDF export helpers for folders of spectra."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from app.reference_import import detect_peaks_for_spectrum
from core.peak import Peak
from core.project import Project
from core.spectrum import Spectrum
from reporting.report_builder import ReportBuilder


class BatchPDFStatus(StrEnum):
    """Outcome of processing a single file during a batch PDF export."""

    EXPORTED = "exported"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True)
class BatchPDFResult:
    """Result of attempting to export one source file to PDF."""

    path: Path
    status: BatchPDFStatus
    reason: str = ""
    output_path: Path | None = None
    detected_peaks: tuple[Peak, ...] = ()


@dataclass(frozen=True)
class BatchPDFSummary:
    """Structured summary for a completed batch PDF export run."""

    input_folder: Path
    output_folder: Path
    results: tuple[BatchPDFResult, ...]

    @property
    def total_found(self) -> int:
        """Total number of `.spa` files discovered in the input folder."""
        return len(self.results)

    @property
    def exported(self) -> int:
        """Count of successfully exported reports."""
        return sum(result.status == BatchPDFStatus.EXPORTED for result in self.results)

    @property
    def skipped(self) -> int:
        """Count of skipped exports."""
        return sum(result.status == BatchPDFStatus.SKIPPED for result in self.results)

    @property
    def failed(self) -> int:
        """Count of failed exports."""
        return sum(result.status == BatchPDFStatus.FAILED for result in self.results)


class BatchPDFExporter:
    """Service for exporting PDF reports for all `.spa` files in a folder."""

    def __init__(self, report_builder: ReportBuilder | None = None) -> None:
        self._report_builder = report_builder or ReportBuilder()

    def export_folder(
        self,
        input_folder: str | Path,
        output_folder: str | Path,
        *,
        detect_peaks: bool = False,
    ) -> BatchPDFSummary:
        """Export PDF reports for all `.spa` files in the input folder."""
        input_path = Path(input_folder)
        output_path = Path(output_folder)
        files = self.scan_folder(input_path)
        self._ensure_output_folder(output_path)

        results: list[BatchPDFResult] = []
        for file_path in files:
            pdf_path = self._output_path_for(file_path, output_path)
            try:
                spectrum = self._read_spectrum(file_path)
                project = self._project_from_spectrum(
                    file_path,
                    spectrum,
                    detect_peaks=detect_peaks,
                )
                self._export_project(project, pdf_path)
            except Exception as exc:  # noqa: BLE001
                results.append(
                    BatchPDFResult(
                        path=file_path,
                        status=BatchPDFStatus.FAILED,
                        reason=self._format_error(exc),
                    )
                )
                continue

            results.append(
                BatchPDFResult(
                    path=file_path,
                    status=BatchPDFStatus.EXPORTED,
                    output_path=pdf_path,
                    detected_peaks=tuple(project.peaks),
                )
            )

        return BatchPDFSummary(
            input_folder=input_path,
            output_folder=output_path,
            results=tuple(results),
        )

    def scan_folder(self, folder: Path) -> list[Path]:
        """Return non-recursive `.spa` files from a folder, sorted by filename."""
        if not folder.exists():
            raise FileNotFoundError(f"Input folder not found: {folder}")
        if not folder.is_dir():
            raise NotADirectoryError(f"Input folder is not a directory: {folder}")
        return sorted(
            path for path in folder.iterdir() if path.is_file() and path.suffix.lower() == ".spa"
        )

    def _read_spectrum(self, path: Path) -> Spectrum:
        """Read a spectrum using the application's registered file-import pipeline."""
        from io.format_registry import FormatRegistry  # noqa: PLC0415

        return FormatRegistry().read(path)

    def _project_from_spectrum(
        self,
        path: Path,
        spectrum: Spectrum,
        *,
        detect_peaks: bool = False,
    ) -> Project:
        """Create a minimal Project suitable for PDF report export."""
        name = spectrum.title.strip() or path.stem
        peaks = list(detect_peaks_for_spectrum(spectrum)) if detect_peaks else []
        return Project(name=name, spectrum=spectrum, peaks=peaks)

    def _export_project(self, project: Project, output_path: Path) -> None:
        """Render and save a PDF report for a single project."""
        self._report_builder.build(project, output_path)

    @staticmethod
    def _output_path_for(source_path: Path, output_folder: Path) -> Path:
        """Return the PDF destination path for a given input spectrum file."""
        return output_folder / f"{source_path.stem}.pdf"

    @staticmethod
    def _ensure_output_folder(folder: Path) -> None:
        """Create the output folder if needed and validate it is a directory."""
        if folder.exists() and not folder.is_dir():
            raise NotADirectoryError(f"Output folder is not a directory: {folder}")
        folder.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _format_error(exc: Exception) -> str:
        """Return a concise one-line error message for UI display."""
        message = str(exc).strip()
        if not message:
            return exc.__class__.__name__
        return message.splitlines()[0]
