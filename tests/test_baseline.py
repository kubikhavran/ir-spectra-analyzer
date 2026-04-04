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


# ---------------------------------------------------------------------------
# Absorbance (lower-hull, upper=False) — existing behaviour preserved
# ---------------------------------------------------------------------------


def test_rubber_band_flat_spectrum_is_zero():
    """Flat absorbance spectrum → corrected values are all zero."""
    wn = np.linspace(400.0, 4000.0, 100)
    y = np.full_like(wn, 5.0)
    corrected = rubber_band_baseline(wn, y)
    assert corrected.shape == y.shape
    assert np.allclose(corrected, 0.0, atol=1e-8)


def test_rubber_band_peak_on_linear_baseline():
    """Absorbance peak on sloped baseline: peak preserved, endpoints near zero."""
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
    """CorrectBaselineCommand undo/redo cycle leaves corrected_spectrum in expected state."""
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


# ---------------------------------------------------------------------------
# %Transmittance (upper-hull, upper=True) — new behaviour
# ---------------------------------------------------------------------------


def test_rubber_band_upper_flat_spectrum_is_zero():
    """Flat %T spectrum with upper=True → corrected values are all zero."""
    wn = np.linspace(400.0, 4000.0, 100)
    y = np.full_like(wn, 100.0)  # pure 100 %T baseline
    corrected = rubber_band_baseline(wn, y, upper=True)
    assert corrected.shape == y.shape
    assert np.allclose(corrected, 0.0, atol=1e-8)


def test_rubber_band_upper_dip_becomes_positive():
    """%T dip (Gaussian absorption band) is positive after upper-hull correction."""
    wn = np.linspace(400.0, 4000.0, 3601)
    # Flat 100 %T baseline with a Gaussian absorption dip at 1700 cm-1 going to 60 %T.
    dip = 40.0 * np.exp(-((wn - 1700.0) ** 2) / (2 * 30.0**2))
    transmittance = 100.0 - dip  # dip minimum ≈ 60 %T

    corrected = rubber_band_baseline(wn, transmittance, upper=True)

    # Baseline regions are near zero.
    assert abs(corrected[0]) < 1.0
    assert abs(corrected[-1]) < 1.0
    # Absorption band appears as a positive peak.
    assert corrected.max() > 30.0
    # The peak maximum is near the dip position.
    peak_wn = wn[np.argmax(corrected)]
    assert abs(peak_wn - 1700.0) < 20.0


def test_rubber_band_upper_baseline_not_anchored_to_dip_bottoms():
    """Upper-hull correction must NOT use the dip bottoms as baseline reference.

    Specifically: if two deep dips flank a flat 100 %T region, the corrected
    value in that flat region must remain near zero (it is part of the
    transmission baseline, not an absorption band).
    """
    wn = np.linspace(400.0, 4000.0, 3601)
    dip1 = 50.0 * np.exp(-((wn - 1000.0) ** 2) / (2 * 30.0**2))  # at 1000 cm-1
    dip2 = 50.0 * np.exp(-((wn - 3000.0) ** 2) / (2 * 30.0**2))  # at 3000 cm-1
    transmittance = 100.0 - dip1 - dip2

    corrected = rubber_band_baseline(wn, transmittance, upper=True)

    # Mid-point between the two dips should be near baseline (corrected ≈ 0).
    mid_idx = np.argmin(np.abs(wn - 2000.0))
    assert abs(corrected[mid_idx]) < 5.0  # within 5 %T of zero (tolerance for interpolation)


def test_rubber_band_upper_output_all_nonnegative():
    """upper=True correction should produce non-negative values for clean %T data."""
    wn = np.linspace(400.0, 4000.0, 1001)
    dip = 30.0 * np.exp(-((wn - 2000.0) ** 2) / (2 * 50.0**2))
    transmittance = 100.0 - dip
    corrected = rubber_band_baseline(wn, transmittance, upper=True)
    assert np.all(corrected >= -1e-8)  # allow tiny floating-point error


def test_rubber_band_upper_vs_lower_direction():
    """Confirm that upper=True and upper=False produce opposite correction directions."""
    wn = np.linspace(400.0, 4000.0, 1001)
    # Absorbance peak at 2000 cm-1.
    peak = 0.5 * np.exp(-((wn - 2000.0) ** 2) / (2 * 50.0**2))
    absorbance = 0.05 + peak  # baseline ≈ 0.05, peak at 0.55

    corrected_abs = rubber_band_baseline(wn, absorbance, upper=False)
    # For absorbance (lower hull): peak stays positive.
    assert corrected_abs.max() > 0.4

    # For a %T dip: upper hull correction.
    transmittance = 100.0 - 50.0 * np.exp(-((wn - 2000.0) ** 2) / (2 * 50.0**2))
    corrected_t = rubber_band_baseline(wn, transmittance, upper=True)
    # Dip converted to positive peak.
    assert corrected_t.max() > 40.0


# ---------------------------------------------------------------------------
# Unit-aware dispatch in the UI handler
# ---------------------------------------------------------------------------


def test_on_correct_baseline_uses_upper_hull_for_transmittance(qtbot):
    """_on_correct_baseline selects upper=True automatically for %T spectra."""
    from storage.database import Database
    from storage.settings import Settings
    from ui.main_window import MainWindow

    db = Database()
    db.initialize()
    settings = Settings()
    settings.load()
    win = MainWindow(db=db, settings=settings)
    qtbot.addWidget(win)

    wn = np.linspace(400.0, 4000.0, 1001)
    dip = 40.0 * np.exp(-((wn - 1700.0) ** 2) / (2 * 30.0**2))
    transmittance = np.clip(100.0 - dip, 0.0, 110.0)

    from core.project import Project
    from core.spectrum import SpectralUnit, Spectrum

    spectrum = Spectrum(
        wavenumbers=wn, intensities=transmittance, y_unit=SpectralUnit.TRANSMITTANCE
    )
    win._project = Project(name="test", spectrum=spectrum)

    win._on_correct_baseline()

    assert win._project.corrected_spectrum is not None
    corrected = win._project.corrected_spectrum.intensities
    # Dip becomes a positive peak.
    assert corrected.max() > 30.0
    # Endpoints near zero (baseline regions).
    assert abs(corrected[0]) < 5.0
    assert abs(corrected[-1]) < 5.0
    # Corrected spectrum must NOT retain the raw %T unit — it is now a derived signal.
    from core.spectrum import SpectralUnit

    assert win._project.corrected_spectrum.y_unit == SpectralUnit.BASELINE_CORRECTED


def test_on_correct_baseline_absorbance_also_gets_baseline_corrected_unit(qtbot):
    """Baseline-corrected Absorbance spectrum also carries BASELINE_CORRECTED unit."""
    from core.project import Project
    from core.spectrum import SpectralUnit, Spectrum
    from storage.database import Database
    from storage.settings import Settings
    from ui.main_window import MainWindow

    db = Database()
    db.initialize()
    settings = Settings()
    settings.load()
    win = MainWindow(db=db, settings=settings)
    qtbot.addWidget(win)

    wn = np.linspace(400.0, 4000.0, 1001)
    peak_abs = 0.5 * np.exp(-((wn - 1700.0) ** 2) / (2 * 30.0**2))
    absorbance = 0.02 + peak_abs

    spectrum = Spectrum(wavenumbers=wn, intensities=absorbance, y_unit=SpectralUnit.ABSORBANCE)
    win._project = Project(name="test_abs", spectrum=spectrum)

    win._on_correct_baseline()

    assert win._project.corrected_spectrum is not None
    assert win._project.corrected_spectrum.y_unit == SpectralUnit.BASELINE_CORRECTED


def test_baseline_corrected_unit_roundtrips_in_serializer():
    """BASELINE_CORRECTED unit survives project save/load via ProjectSerializer."""
    import os
    import tempfile

    import numpy as np

    from core.project import Project
    from core.spectrum import SpectralUnit, Spectrum
    from storage.project_serializer import ProjectSerializer

    wn = np.linspace(400.0, 4000.0, 100)
    y = np.abs(np.sin(wn / 200.0))
    spectrum = Spectrum(wavenumbers=wn, intensities=y, y_unit=SpectralUnit.BASELINE_CORRECTED)
    project = Project(name="roundtrip", spectrum=spectrum)

    with tempfile.NamedTemporaryFile(suffix=".irproj", delete=False, mode="w") as f:
        path = f.name
    try:
        ProjectSerializer().save(project, path)
        loaded = ProjectSerializer().load(path)
    finally:
        os.unlink(path)

    assert loaded.spectrum is not None
    assert loaded.spectrum.y_unit == SpectralUnit.BASELINE_CORRECTED


def test_spectrum_renderer_baseline_corrected_autoscales():
    """SpectrumRenderer uses autoscale (not 0–110 %T range) for BASELINE_CORRECTED spectra."""
    import numpy as np

    from core.spectrum import SpectralUnit
    from reporting.spectrum_renderer import SpectrumRenderer

    wn = np.linspace(400.0, 4000.0, 1001)
    # Corrected signal: positive peaks, low values, definitely not 0–110 %T range
    y = 0.5 * np.exp(-((wn - 1700.0) ** 2) / (2 * 30.0**2))

    png_bytes = SpectrumRenderer().render_to_bytes(
        wn, y, peaks=[], y_unit=SpectralUnit.BASELINE_CORRECTED
    )
    # The renderer must produce valid PNG output — if ylim were forced to 0–110
    # the spectrum (max ≈ 0.5) would be invisible. We can only check it renders.
    assert png_bytes[:4] == b"\x89PNG"
    assert len(png_bytes) > 1000


def test_spectrum_widget_label_changes_to_baseline_corrected(qtbot):
    """Interactive viewer label updates to 'Baseline Corrected' after correction."""
    import numpy as np

    from core.spectrum import SpectralUnit, Spectrum
    from ui.spectrum_widget import SpectrumWidget

    wn = np.linspace(400.0, 4000.0, 100)
    y = np.ones_like(wn) * 0.1
    corrected = Spectrum(
        wavenumbers=wn,
        intensities=y,
        y_unit=SpectralUnit.BASELINE_CORRECTED,
    )

    widget = SpectrumWidget()
    qtbot.addWidget(widget)
    widget.set_spectrum(corrected)

    left_axis = widget._plot_widget.getAxis("left")
    label_text = left_axis.labelText
    assert "Baseline Corrected" in label_text


def test_detect_peaks_uses_high_prominence_for_baseline_corrected(qtbot):
    """Peak detection uses prominence=1.0 for BASELINE_CORRECTED spectra (not 0.01).

    A corrected %T signal spans 0–100, so prominence=0.01 would return thousands
    of spurious peaks.  The handler must use the same threshold as for raw %T.
    """
    from storage.database import Database
    from storage.settings import Settings
    from ui.main_window import MainWindow

    db = Database()
    db.initialize()
    settings = Settings()
    settings.load()
    win = MainWindow(db=db, settings=settings)
    qtbot.addWidget(win)

    wn = np.linspace(400.0, 4000.0, 3601)
    # Two well-separated Gaussian peaks on a zero baseline (already corrected).
    y = 30.0 * np.exp(-((wn - 1000.0) ** 2) / (2 * 30.0**2)) + 25.0 * np.exp(
        -((wn - 2500.0) ** 2) / (2 * 30.0**2)
    )

    from core.project import Project
    from core.spectrum import SpectralUnit, Spectrum

    spectrum = Spectrum(wavenumbers=wn, intensities=y, y_unit=SpectralUnit.BASELINE_CORRECTED)
    win._project = Project(name="bc_peaks", spectrum=spectrum)
    # Put the corrected spectrum directly so _on_detect_peaks uses it.
    win._project.corrected_spectrum = spectrum

    win._on_detect_peaks()

    n_peaks = len(win._project.peaks)
    # Should find exactly the two prominent peaks, not hundreds of noise points.
    assert n_peaks == 2, f"Expected 2 peaks, got {n_peaks}"
