"""Tests for QUndoCommand peak operations."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication


def _app():
    return QApplication.instance() or QApplication([])


def _make_project():
    from core.project import Project
    from core.spectrum import Spectrum

    wn = np.linspace(400.0, 4000.0, 100)
    sp = Spectrum(wavenumbers=wn, intensities=np.ones(100), title="T")
    return Project(name="T", spectrum=sp)


def test_add_peak_command_redo_undo():
    _app()
    from core.commands import AddPeakCommand
    from core.peak import Peak

    project = _make_project()
    stack = QUndoStack()
    peak = Peak(position=1000.0, intensity=0.5)
    cmd = AddPeakCommand(project, peak)
    stack.push(cmd)
    assert peak in project.peaks
    stack.undo()
    assert peak not in project.peaks
    stack.redo()
    assert peak in project.peaks


def test_delete_peak_command_redo_undo():
    _app()
    from core.commands import AddPeakCommand, DeletePeakCommand
    from core.peak import Peak

    project = _make_project()
    stack = QUndoStack()
    peak = Peak(position=1000.0, intensity=0.5)
    stack.push(AddPeakCommand(project, peak))
    stack.push(DeletePeakCommand(project, peak))
    assert peak not in project.peaks
    stack.undo()
    assert peak in project.peaks


def test_assign_preset_command_redo_undo():
    _app()
    from core.commands import AssignPresetCommand
    from core.peak import Peak
    from core.vibration_presets import VibrationPreset

    peak = Peak(position=2900.0, intensity=0.8)
    preset = VibrationPreset(
        name="C-H stretch", typical_range_min=2800, typical_range_max=3000, db_id=42
    )
    stack = QUndoStack()
    stack.push(AssignPresetCommand(peak, preset))
    assert peak.display_label == "C-H stretch"
    assert 42 in peak.vibration_ids
    stack.undo()
    assert peak.display_label == "2900"
    assert 42 not in peak.vibration_ids


def test_set_peak_vibrations_command_redo_undo():
    _app()
    from core.commands import SetPeakVibrationsCommand
    from core.peak import Peak

    peak = Peak(
        position=2900.0,
        intensity=0.8,
        vibration_ids=[42],
        vibration_labels=["C-H stretch"],
    )
    stack = QUndoStack()

    stack.push(
        SetPeakVibrationsCommand(
            peak,
            vibration_labels=["νas(CH₃) –CH₃–"],
            vibration_ids=[None],
        )
    )

    assert peak.display_label == "νas(CH₃) –CH₃–"
    assert peak.vibration_labels == ["νas(CH₃) –CH₃–"]
    assert peak.vibration_ids == [None]

    stack.undo()

    assert peak.display_label == "C-H stretch"
    assert peak.vibration_labels == ["C-H stretch"]
    assert peak.vibration_ids == [42]


def test_detect_peaks_macro_is_single_undo():
    _app()
    from core.commands import AddPeakCommand
    from core.peak import Peak

    project = _make_project()
    stack = QUndoStack()
    # Simulate detect: clear + add 3 peaks as a macro
    stack.beginMacro("Detect peaks")
    for pos in [1000.0, 1500.0, 2000.0]:
        stack.push(AddPeakCommand(project, Peak(position=pos, intensity=0.5)))
    stack.endMacro()
    assert len(project.peaks) == 3
    stack.undo()  # one undo should remove all 3
    assert len(project.peaks) == 0
