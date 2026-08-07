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
        for i, p in enumerate(self._project.peaks):
            if p is self._peak:
                self._project.peaks.pop(i)
                return
        self.setObsolete(True)

    def undo(self) -> None:
        if not any(p is self._peak for p in self._project.peaks):
            self._project.add_peak(self._peak)


class AssignPresetCommand(QUndoCommand):
    """Appends a vibration preset assignment to a peak (undoable)."""

    def __init__(self, peak: Peak, preset: VibrationPreset) -> None:
        super().__init__(f'Assign "{preset.name}" to {peak.position:.1f} cm\u207b\u00b9')
        self._peak = peak
        self._preset = preset
        self._added_idx = -1
        self._old_vibration_id = peak.vibration_id

    def redo(self) -> None:
        # ID-less/manual presets are distinct by label. Treating all ``None``
        # IDs as the same preset used to reject every manual label after the
        # first one and made a no-op command unsafe to undo.
        if self._preset.db_id is None:
            duplicate = any(
                label == self._preset.name
                and (idx >= len(self._peak.vibration_ids) or self._peak.vibration_ids[idx] is None)
                for idx, label in enumerate(self._peak.vibration_labels)
            )
        else:
            duplicate = self._preset.db_id in self._peak.vibration_ids
        if duplicate:
            self._added_idx = -1
            self.setObsolete(True)
            return
        self._added_idx = len(self._peak.vibration_ids)
        self._peak.vibration_ids.append(self._preset.db_id)
        self._peak.vibration_labels.append(self._preset.name)
        self._sync_legacy_id()

    def undo(self) -> None:
        if self._added_idx < 0:
            return
        idx = self._added_idx
        if idx < len(self._peak.vibration_ids):
            self._peak.vibration_ids.pop(idx)
        if idx < len(self._peak.vibration_labels):
            self._peak.vibration_labels.pop(idx)
        self._peak.vibration_id = self._old_vibration_id
        self._added_idx = -1

    def _sync_legacy_id(self) -> None:
        self._peak.vibration_id = next(
            (db_id for db_id in self._peak.vibration_ids if db_id is not None),
            None,
        )


class RemovePresetCommand(QUndoCommand):
    """Removes one vibration assignment from a peak (undoable)."""

    def __init__(self, peak: Peak, preset: VibrationPreset) -> None:
        super().__init__(f'Remove "{preset.name}" from {peak.position:.1f} cm\u207b\u00b9')
        self._peak = peak
        self._preset = preset
        self._removed_idx: int = -1
        self._removed_id: int | None = None
        self._removed_label: str = preset.name
        self._old_vibration_id = peak.vibration_id

    def redo(self) -> None:
        self._removed_idx = -1
        if self._preset.db_id is None:
            for idx, label in enumerate(self._peak.vibration_labels):
                candidate_id = (
                    self._peak.vibration_ids[idx] if idx < len(self._peak.vibration_ids) else None
                )
                if label == self._preset.name and candidate_id is None:
                    self._removed_idx = idx
                    break
        elif self._preset.db_id in self._peak.vibration_ids:
            self._removed_idx = self._peak.vibration_ids.index(self._preset.db_id)

        if self._removed_idx < 0:
            self.setObsolete(True)
            return
        idx = self._removed_idx
        self._removed_id = (
            self._peak.vibration_ids.pop(idx)
            if idx < len(self._peak.vibration_ids)
            else self._preset.db_id
        )
        self._removed_label = (
            self._peak.vibration_labels.pop(idx)
            if idx < len(self._peak.vibration_labels)
            else self._preset.name
        )
        self._sync_legacy_id()

    def undo(self) -> None:
        if self._removed_idx >= 0:
            self._peak.vibration_ids.insert(self._removed_idx, self._removed_id)
            self._peak.vibration_labels.insert(self._removed_idx, self._removed_label)
            self._peak.vibration_id = self._old_vibration_id

    def _sync_legacy_id(self) -> None:
        self._peak.vibration_id = next(
            (db_id for db_id in self._peak.vibration_ids if db_id is not None),
            None,
        )


class SetPeakVibrationsCommand(QUndoCommand):
    """Replaces the full vibration label list on a peak (undoable)."""

    def __init__(
        self,
        peak: Peak,
        vibration_labels: list[str],
        vibration_ids: list[int | None],
    ) -> None:
        super().__init__(f"Edit vibration text for {peak.position:.1f} cm\u207b\u00b9")
        self._peak = peak
        self._new_labels = list(vibration_labels)
        self._new_ids = list(vibration_ids)
        self._old_labels = list(peak.vibration_labels)
        self._old_ids = list(peak.vibration_ids)
        self._old_vibration_id = peak.vibration_id
        self._new_vibration_id = next((db_id for db_id in self._new_ids if db_id is not None), None)

    def redo(self) -> None:
        if (
            self._peak.vibration_labels == self._new_labels
            and self._peak.vibration_ids == self._new_ids
            and self._peak.vibration_id == self._new_vibration_id
        ):
            self.setObsolete(True)
            return
        self._peak.vibration_labels = list(self._new_labels)
        self._peak.vibration_ids = list(self._new_ids)
        self._peak.vibration_id = self._new_vibration_id

    def undo(self) -> None:
        self._peak.vibration_labels = list(self._old_labels)
        self._peak.vibration_ids = list(self._old_ids)
        self._peak.vibration_id = self._old_vibration_id


class SetPeakLabelPlacementsCommand(QUndoCommand):
    """Updates peak label offsets in bulk (undoable)."""

    def __init__(
        self,
        placements: list[tuple[Peak, float, float]],
    ) -> None:
        super().__init__("Arrange peak labels")
        self._new_placements = [
            (peak, offset_x, offset_y) for peak, offset_x, offset_y in placements
        ]
        self._old_placements = [
            (peak, peak.label_offset_x, peak.label_offset_y, peak.manual_placement)
            for peak, _offset_x, _offset_y in placements
        ]

    def redo(self) -> None:
        if all(
            peak.label_offset_x == offset_x
            and peak.label_offset_y == offset_y
            and peak.manual_placement
            for peak, offset_x, offset_y in self._new_placements
        ):
            self.setObsolete(True)
            return
        for peak, offset_x, offset_y in self._new_placements:
            peak.label_offset_x = offset_x
            peak.label_offset_y = offset_y
            peak.manual_placement = True

    def undo(self) -> None:
        for peak, offset_x, offset_y, manual_placement in self._old_placements:
            peak.label_offset_x = offset_x
            peak.label_offset_y = offset_y
            peak.manual_placement = manual_placement


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
