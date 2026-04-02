"""QUndoCommand subclasses for peak-related actions."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtGui import QUndoCommand

from core.peak import Peak
from core.project import Project
from core.spectrum import Spectrum
from core.vibration_presets import VibrationPreset


class AddPeakCommand(QUndoCommand):
    """Adds a single peak to a project (undoable)."""

    def __init__(self, project: Project, peak: Peak) -> None:
        super().__init__(f"Add peak {peak.position:.1f} cm\u207b\u00b9")
        self._project = project
        self._peak = peak

    def redo(self) -> None:
        self._project.add_peak(self._peak)

    def undo(self) -> None:
        if self._peak in self._project.peaks:
            self._project.peaks.remove(self._peak)


class DeletePeakCommand(QUndoCommand):
    """Deletes a single peak from a project (undoable)."""

    def __init__(self, project: Project, peak: Peak) -> None:
        super().__init__(f"Delete peak {peak.position:.1f} cm\u207b\u00b9")
        self._project = project
        self._peak = peak

    def redo(self) -> None:
        if self._peak in self._project.peaks:
            self._project.peaks.remove(self._peak)

    def undo(self) -> None:
        self._project.add_peak(self._peak)


class AssignPresetCommand(QUndoCommand):
    """Assigns (or re-assigns) a vibration preset to a peak (undoable)."""

    def __init__(self, peak: Peak, preset: VibrationPreset) -> None:
        super().__init__(f'Assign "{preset.name}" to {peak.position:.1f} cm\u207b\u00b9')
        self._peak = peak
        self._preset = preset
        self._old_vibration_id = peak.vibration_id
        self._old_label = peak.label

    def redo(self) -> None:
        self._peak.vibration_id = self._preset.db_id
        self._peak.label = self._preset.name

    def undo(self) -> None:
        self._peak.vibration_id = self._old_vibration_id
        self._peak.label = self._old_label


class CorrectBaselineCommand(QUndoCommand):
    """Applies baseline correction to the project (undoable)."""

    def __init__(self, project: Project, corrected_spectrum: Spectrum) -> None:
        super().__init__("Correct Baseline")
        self._project = project
        self._corrected_spectrum = corrected_spectrum
        self._previous_spectrum = project.corrected_spectrum

    def redo(self) -> None:
        self._project.corrected_spectrum = self._corrected_spectrum
        self._project.updated_at = datetime.now()

    def undo(self) -> None:
        self._project.corrected_spectrum = self._previous_spectrum
        self._project.updated_at = datetime.now()
