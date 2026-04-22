"""Background worker for batch project generation from raw spectra."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from app.batch_project_generation import BatchProjectGenerator


class BatchProjectGenerationWorker(QObject):
    """Run bulk project generation on a worker thread."""

    completed = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(
        self,
        *,
        input_folder: str | Path,
        output_folder: str | Path,
        detect_peaks: bool,
        overwrite_mode: str,
    ) -> None:
        super().__init__()
        self._input_folder = input_folder
        self._output_folder = output_folder
        self._detect_peaks = detect_peaks
        self._overwrite_mode = overwrite_mode

    @Slot()
    def run(self) -> None:
        generator = BatchProjectGenerator()
        try:
            summary = generator.generate_folder(
                self._input_folder,
                self._output_folder,
                detect_peaks=self._detect_peaks,
                overwrite_mode=self._overwrite_mode,
            )
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
        else:
            self.completed.emit(summary)
        finally:
            self.finished.emit()
