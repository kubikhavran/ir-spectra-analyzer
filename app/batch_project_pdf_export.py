"""Application-layer batch PDF export for saved project files."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from app.output_path_policy import resolve_output_path
from core.project import Project
from reporting.pdf_generator import ReportOptions
from reporting.report_builder import ReportBuilder
from storage.project_serializer import ProjectSerializer


class BatchProjectPDFStatus(StrEnum):
    """Outcome of processing a single file during batch project PDF export."""

    EXPORTED = "exported"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True)
class BatchProjectPDFResult:
    """Result of attempting to export one project file to PDF."""

    path: Path
    status: BatchProjectPDFStatus
    reason: str = ""
    output_path: Path | None = None


@dataclass(frozen=True)
class BatchProjectPDFSummary:
    """Structured summary for a completed batch project PDF export run."""

    input_folder: Path
    output_folder: Path
    results: tuple[BatchProjectPDFResult, ...]

    @property
    def total_found(self) -> int:
        """Total number of `.irproj` files discovered in the input folder."""
        return len(self.results)

    @property
    def exported(self) -> int:
        """Count of successfully exported project PDFs."""
        return sum(result.status == BatchProjectPDFStatus.EXPORTED for result in self.results)

    @property
    def skipped(self) -> int:
        """Count of skipped project PDF exports."""
        return sum(result.status == BatchProjectPDFStatus.SKIPPED for result in self.results)

    @property
    def failed(self) -> int:
        """Count of failed project PDF exports."""
        return sum(result.status == BatchProjectPDFStatus.FAILED for result in self.results)


class BatchProjectPDFExporter:
    """Service for exporting PDF reports from saved `.irproj` files."""

    def __init__(
        self,
        serializer: ProjectSerializer | None = None,
        report_builder: ReportBuilder | None = None,
    ) -> None:
        self._serializer = serializer or ProjectSerializer()
        self._report_builder = report_builder or ReportBuilder()

    def export_folder(
        self,
        input_folder: str | Path,
        output_folder: str | Path,
        *,
        report_options: ReportOptions | None = None,
        overwrite_mode: str = "skip",
    ) -> BatchProjectPDFSummary:
        """Export PDF reports for all `.irproj` files in the input folder."""
        input_path = Path(input_folder)
        output_path = Path(output_folder)
        files = self.scan_folder(input_path)
        self._ensure_output_folder(output_path)

        results: list[BatchProjectPDFResult] = []
        for file_path in files:
            pdf_path = self._output_path_for(file_path, output_path)
            action, resolved_path = resolve_output_path(pdf_path, overwrite_mode)
            if action == "skip":
                results.append(
                    BatchProjectPDFResult(
                        path=file_path,
                        status=BatchProjectPDFStatus.SKIPPED,
                        reason="output file already exists",
                        output_path=pdf_path,
                    )
                )
                continue

            if resolved_path is None:
                raise AssertionError("resolve_output_path returned no destination for write action")

            try:
                project = self._load_project(file_path)
                self._export_project(project, resolved_path, report_options=report_options)
            except Exception as exc:  # noqa: BLE001
                results.append(
                    BatchProjectPDFResult(
                        path=file_path,
                        status=BatchProjectPDFStatus.FAILED,
                        reason=self._format_error(exc),
                        output_path=resolved_path,
                    )
                )
                continue

            results.append(
                BatchProjectPDFResult(
                    path=file_path,
                    status=BatchProjectPDFStatus.EXPORTED,
                    output_path=resolved_path,
                )
            )

        return BatchProjectPDFSummary(
            input_folder=input_path,
            output_folder=output_path,
            results=tuple(results),
        )

    def scan_folder(self, folder: Path) -> list[Path]:
        """Return non-recursive `.irproj` files from a folder, sorted by filename."""
        if not folder.exists():
            raise FileNotFoundError(f"Input folder not found: {folder}")
        if not folder.is_dir():
            raise NotADirectoryError(f"Input folder is not a directory: {folder}")
        return sorted(
            path for path in folder.iterdir() if path.is_file() and path.suffix.lower() == ".irproj"
        )

    def _load_project(self, path: Path) -> Project:
        """Load a saved project using the normal serializer pipeline."""
        return self._serializer.load(path)

    def _export_project(
        self,
        project: Project,
        output_path: Path,
        *,
        report_options: ReportOptions | None = None,
    ) -> None:
        """Render and save a PDF report for a single loaded project."""
        if report_options is None:
            self._report_builder.build(project, output_path)
            return
        self._report_builder.build_with_options(project, output_path, report_options)

    @staticmethod
    def _output_path_for(source_path: Path, output_folder: Path) -> Path:
        """Return the PDF destination path for a given input project file."""
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
