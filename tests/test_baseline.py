"""Tests for baseline correction processing and commands."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication

from core.commands import CorrectBaselineCommand
from core.project import Project
from core.spectrum import Spectrum
from processing.baseline import rubber_band_baseline


def _app():
    return QApplication.instance() or QApplication([])


def test_rubber_band_flat_spectrum_is_zero():
    wn = np.linspace(400.0, 4000.0, 100)
    y = np.full_like(wn, 5.0)
    corrected = rubber_band_baseline(wn, y)
    assert corrected.shape == y.shape
    assert np.allclose(corrected, 0.0, atol=1e-8)


def test_rubber_band_peak_on_linear_baseline():
    wn = np.linspace(0.0, 100.0, 201)
    baseline = 0.2 + 0.001 * wn
    peak = np.exp(-0.5 * ((wn - 50.0) / 5.0) ** 2)
    y = baseline + peak

    corrected = rubber_band_baseline(wn, y)

    assert corrected.shape == y.shape
    assert np.isclose(corrected.max(), peak.max(), rtol=0.01)
    assert abs(corrected[0]) < 0.01
    assert abs(corrected[-1]) < 0.01


def test_correct_baseline_command_undo_redo():
    _app()
    wn = np.linspace(400.0, 2400.0, 100)
    y = np.ones_like(wn) * 2.0
    spectrum = Spectrum(wavenumbers=wn, intensities=y)
    project = Project(name="P", spectrum=spectrum)

    corrected = rubber_band_baseline(wn, y)
    corrected_spectrum = Spectrum(wavenumbers=wn, intensities=corrected)

    stack = QUndoStack()
    stack.push(CorrectBaselineCommand(project, corrected_spectrum))
    assert project.corrected_spectrum is not None
    assert np.allclose(project.corrected_spectrum.intensities, np.zeros_like(wn), atol=1e-8)

    stack.undo()
    assert project.corrected_spectrum is None

    stack.redo()
    assert project.corrected_spectrum is not None
