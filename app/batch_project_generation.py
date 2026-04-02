"""Application-layer batch project generation for folders of spectra."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from app.reference_import import detect_peaks_for_spectrum
from core.project import Project
from core.spectrum import Spectrum
from storage.project_serializer import ProjectSerializer


class BatchProjectStatus(StrEnum):
    """Outcome of processing a single file during batch project generation."""

    GENERATED = "generated"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True)
class BatchProjectResult:
    """Result of attempting to generate one project file from a source spectrum."""

    path: Path
    status: BatchProjectStatus
    reason: str = ""
    output_path: Path | None = None
    peak_count: int = 0


@dataclass(frozen=True)
class BatchProjectSummary:
    """Structured summary for a completed batch project generation run."""

    input_folder: Path
    output_folder: Path
    results: tuple[BatchProjectResult, ...]

    @property
    def total_found(self) -> int:
        """Total number of `.spa` files discovered in the input folder."""
        return len(self.results)

    @property
    def generated(self) -> int:
        """Count of successfully generated project files."""
        return sum(result.status == BatchProjectStatus.GENERATED for result in self.results)

    @property
    def skipped(self) -> int:
        """Count of skipped project generations."""
        return sum(result.status == BatchProjectStatus.SKIPPED for result in self.results)

    @property
    def failed(self) -> int:
        """Count of files that failed during project generation."""
        return sum(result.status == BatchProjectStatus.FAILED for result in self.results)


class BatchProjectGenerator:
    """Service for generating `.irproj` files for all `.spa` files in a folder."""

    def __init__(self, serializer: ProjectSerializer | None = None) -> None:
        self._serializer = serializer or ProjectSerializer()

    def generate_folder(
        self,
        input_folder: str | Path,
        output_folder: str | Path,
        *,
        detect_peaks: bool = False,
    ) -> BatchProjectSummary:
        """Generate project files for all `.spa` files in the input folder."""
        input_path = Path(input_folder)
        output_path = Path(output_folder)
        files = self.scan_folder(input_path)
        self._ensure_output_folder(output_path)

        results: list[BatchProjectResult] = []
        for file_path in files:
            project_path = self._output_path_for(file_path, output_path)
            try:
                spectrum = self._read_spectrum(file_path)
                project = self._project_from_spectrum(
                    file_path,
                    spectrum,
                    detect_peaks=detect_peaks,
                )
                self._save_project(project, project_path)
            except Exception as exc:  # noqa: BLE001
                results.append(
                    BatchProjectResult(
                        path=file_path,
                        status=BatchProjectStatus.FAILED,
                        reason=self._format_error(exc),
                    )
                )
                continue

            results.append(
                BatchProjectResult(
                    path=file_path,
                    status=BatchProjectStatus.GENERATED,
                    output_path=project_path,
                    peak_count=len(project.peaks),
                )
            )

        return BatchProjectSummary(
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
        """Create a Project suitable for saving as a normal `.irproj` file."""
        if spectrum.source_path is None:
            spectrum.source_path = path
        name = spectrum.title.strip() or path.stem
        peaks = list(detect_peaks_for_spectrum(spectrum)) if detect_peaks else []
        return Project(name=name, spectrum=spectrum, peaks=peaks)

    def _save_project(self, project: Project, output_path: Path) -> None:
        """Persist a project using the normal serializer pipeline."""
        self._serializer.save(project, output_path)

    @staticmethod
    def _output_path_for(source_path: Path, output_folder: Path) -> Path:
        """Return the project destination path for a given input spectrum file."""
        return output_folder / f"{source_path.stem}.irproj"

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
