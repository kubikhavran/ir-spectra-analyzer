"""Regression tests for the defects found in the v0.29.0 audit.

Each test pins one behaviour that was wrong before the fix; the docstring says
what the analyst saw.
"""

from __future__ import annotations

import tomllib
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from core.commands import CorrectBaselineCommand
from core.peak import Peak
from core.peak_assignments import classify_peak_intensities
from core.project import Project
from core.spectrum import SpectralUnit, Spectrum
from core.vibration_presets import VibrationPreset
from matching.preprocessing import prepare_for_matching
from matching.similarity import STANDARD_GRID, cosine_similarity
from processing.baseline import rubber_band_baseline
from processing.y_unit_check import is_dip_shaped
from ui.main_window import MainWindow
from ui.peak_table_widget import PeakTableWidget, format_intensity
from ui.spectrum_widget import SpectrumWidget
from ui.vibration_panel import VibrationPanel

_WN = np.linspace(400.0, 4000.0, 3601)
_BANDS = ((2950.0, 25.0, 1.0), (1715.0, 12.0, 0.8), (1250.0, 18.0, 0.5), (760.0, 10.0, 0.3))


def _absorbance(scale: float = 1.0) -> np.ndarray:
    y = np.zeros_like(_WN)
    for centre, width, height in _BANDS:
        y += scale * height * np.exp(-((_WN - centre) ** 2) / (2 * width**2))
    return y


def _transmittance(depth: float = 40.0) -> Spectrum:
    """A %T spectrum whose deepest band reaches ``100 - depth``."""
    return Spectrum(
        wavenumbers=_WN.copy(),
        intensities=100.0 - depth * _absorbance(),
        y_unit=SpectralUnit.TRANSMITTANCE,
        title="T",
    )


def _window(qtbot) -> MainWindow:
    db = MagicMock()
    db.get_vibration_presets.return_value = []
    settings = MagicMock()
    settings.get.return_value = None
    window = MainWindow(db=db, settings=settings)
    qtbot.addWidget(window)
    return window


# ── Baseline correction ──────────────────────────────────────────────────────


def test_baseline_correction_moves_existing_peaks_onto_the_corrected_curve() -> None:
    """Labels used to stay at the raw intensity, ~100 units above the new curve."""
    spectrum = _transmittance()
    project = Project(name="p", spectrum=spectrum)
    peak = Peak(position=1715.0, intensity=float(np.interp(1715.0, _WN, spectrum.intensities)))
    project.add_peak(peak)
    raw_intensity = peak.intensity

    corrected = replace(
        spectrum,
        intensities=rubber_band_baseline(_WN, spectrum.intensities, upper=True),
        y_unit=SpectralUnit.BASELINE_CORRECTED,
    )
    command = CorrectBaselineCommand(project, corrected)
    command.redo()

    assert peak.intensity == pytest.approx(float(np.interp(1715.0, _WN, corrected.intensities)))
    assert peak.intensity < 0.0

    command.undo()
    assert peak.intensity == pytest.approx(raw_intensity)
    assert project.corrected_spectrum is None


def test_baseline_correction_keeps_the_curve_in_view(qtbot) -> None:
    """The old Y range (60–100 %T) was kept, so the corrected curve was off screen."""
    window = _window(qtbot)
    window._apply_project_to_ui(Project(name="p", spectrum=_transmittance()))
    window._on_correct_baseline()

    corrected = window._project.corrected_spectrum
    assert corrected is not None
    y_lo, y_hi = window._spectrum_widget.get_y_view_range()
    assert y_lo <= float(corrected.intensities.min())
    assert y_hi >= float(corrected.intensities.max())

    window._undo_stack.undo()
    y_lo, y_hi = window._spectrum_widget.get_y_view_range()
    assert y_lo <= float(window._project.spectrum.intensities.min())
    assert y_hi >= 100.0


def test_weak_corrected_transmittance_is_still_read_as_dips() -> None:
    """Bands shallower than 5 %T fell under a fixed threshold and flipped polarity."""
    weak = _transmittance(depth=4.0)
    corrected = rubber_band_baseline(_WN, weak.intensities, upper=True)
    assert corrected.min() > -5.0
    assert is_dip_shaped(corrected, SpectralUnit.BASELINE_CORRECTED)

    corrected_absorbance = rubber_band_baseline(_WN, _absorbance(0.05) + 0.01)
    assert not is_dip_shaped(corrected_absorbance, SpectralUnit.BASELINE_CORRECTED)


def test_intensity_classes_follow_the_corrected_baseline() -> None:
    """Measured from 100 %T, every corrected band came out as "vs"."""
    peaks = [Peak(position=1700.0, intensity=-40.0), Peak(position=1200.0, intensity=-4.0)]
    labels = classify_peak_intensities(peaks, is_dip_spectrum=True)
    assert labels[id(peaks[0])] == "vs"
    assert labels[id(peaks[1])] == "w"

    raw = [Peak(position=1700.0, intensity=60.0), Peak(position=1200.0, intensity=96.0)]
    raw_labels = classify_peak_intensities(raw, is_dip_spectrum=True)
    assert raw_labels[id(raw[0])] == "vs"
    assert raw_labels[id(raw[1])] == "w"


# ── Matching polarity ────────────────────────────────────────────────────────


def _vector(intensities: np.ndarray, unit: SpectralUnit) -> np.ndarray:
    return prepare_for_matching(_WN, intensities, STANDARD_GRID, y_unit=unit)


def test_a_mislabeled_file_is_matched_the_way_it_is_displayed() -> None:
    """%T data under an "Absorbance" header was compared upside down."""
    spectrum = _transmittance()
    honest = _vector(spectrum.intensities, SpectralUnit.TRANSMITTANCE)
    mislabeled = _vector(spectrum.intensities, SpectralUnit.ABSORBANCE)
    assert cosine_similarity(honest, mislabeled) > 0.99


def test_a_weak_corrected_query_matches_its_own_raw_spectrum() -> None:
    weak = _transmittance(depth=4.0)
    corrected = rubber_band_baseline(_WN, weak.intensities, upper=True)
    raw_vector = _vector(weak.intensities, SpectralUnit.TRANSMITTANCE)
    corrected_vector = _vector(corrected, SpectralUnit.BASELINE_CORRECTED)
    assert cosine_similarity(raw_vector, corrected_vector) > 0.99


def test_real_absorbance_is_not_flipped() -> None:
    absorbance = _vector(_absorbance(), SpectralUnit.ABSORBANCE)
    transmittance = _vector(_transmittance().intensities, SpectralUnit.TRANSMITTANCE)
    assert cosine_similarity(absorbance, transmittance) > 0.9


# ── Viewer ───────────────────────────────────────────────────────────────────


def test_overlay_is_drawn_on_the_scale_of_a_corrected_spectrum(qtbot) -> None:
    """A raw %T reference sat near 100 while the corrected curve sat at zero."""
    widget = SpectrumWidget()
    qtbot.addWidget(widget)
    raw = _transmittance()
    corrected = replace(
        raw,
        intensities=rubber_band_baseline(_WN, raw.intensities, upper=True),
        y_unit=SpectralUnit.BASELINE_CORRECTED,
    )
    widget.set_spectrum(corrected)

    overlay = widget._overlay_in_display_unit(_transmittance(depth=30.0))
    assert float(np.nanmax(overlay.intensities)) <= 1e-6
    assert float(np.nanmin(overlay.intensities)) < -5.0

    absorbance_reference = Spectrum(
        wavenumbers=_WN.copy(), intensities=_absorbance(), y_unit=SpectralUnit.ABSORBANCE
    )
    aligned = widget._overlay_in_display_unit(absorbance_reference)
    assert float(np.nanmax(aligned.intensities)) <= 1e-6


def test_add_peak_snaps_to_the_band_apex(qtbot) -> None:
    """At full view one pixel is ~5 cm⁻¹, so a click never hit the apex exactly."""
    widget = SpectrumWidget()
    qtbot.addWidget(widget)
    widget.set_spectrum(
        Spectrum(wavenumbers=_WN.copy(), intensities=_absorbance(), y_unit=SpectralUnit.ABSORBANCE)
    )
    assert widget.snap_to_band_apex(1708.0, 15.0) == pytest.approx(1715.0, abs=1.0)
    # On the slope, with the apex out of reach, the click position is kept.
    assert widget.snap_to_band_apex(1690.0, 5.0) == pytest.approx(1690.0)
    assert widget.snap_to_band_apex(1708.0, 0.0) == pytest.approx(1708.0)

    widget.set_spectrum(_transmittance())
    assert widget.snap_to_band_apex(1722.0, 15.0) == pytest.approx(1715.0, abs=1.0)


def test_peak_added_in_a_converted_view_keeps_the_native_intensity(qtbot) -> None:
    """The %T value on screen was stored as the peak's absorbance."""
    window = _window(qtbot)
    spectrum = Spectrum(
        wavenumbers=_WN.copy(), intensities=_absorbance(), y_unit=SpectralUnit.ABSORBANCE
    )
    window._apply_project_to_ui(Project(name="p", spectrum=spectrum))
    widget = window._spectrum_widget
    widget.set_display_unit(SpectralUnit.TRANSMITTANCE)

    native = widget._native_intensity_at(1715.0)
    assert native == pytest.approx(0.8, abs=0.01)
    assert widget._intensity_at(1715.0) > 10.0  # what is drawn is %T

    window._on_peak_clicked(1715.0, native, 20.0)
    peak = window._project.peaks[0]
    assert peak.intensity == pytest.approx(native)
    assert not peak.manual_placement
    assert peak.label_offset_y == 0.0


def test_peak_table_shows_usable_absorbance_values(qtbot) -> None:
    """Whole-number rounding turned every absorbance into "0" or "1"."""
    assert format_intensity(0.2286) == "0.229"
    assert format_intensity(96.78) == "96.8"
    assert format_intensity(-13.71) == "-13.7"

    table = PeakTableWidget()
    qtbot.addWidget(table)
    table.set_peaks([Peak(position=1715.0, intensity=0.2286)])
    assert table._table.item(0, 1).text() == "0.229"
    # One table, one number of decimals — set by its largest value.
    table.set_peaks([Peak(position=1715.0, intensity=-16.3), Peak(position=1200.0, intensity=-2.4)])
    assert [table._table.item(row, 1).text() for row in range(2)] == ["-16.3", "-2.4"]


def test_vibration_filter_finds_a_preset_by_its_range(qtbot) -> None:
    panel = VibrationPanel()
    qtbot.addWidget(panel)
    panel.set_presets(
        [
            VibrationPreset(name="ν(C=O)", typical_range_min=1700.0, typical_range_max=1750.0),
            VibrationPreset(name="ν(OH)", typical_range_min=3200.0, typical_range_max=3600.0),
        ]
    )
    panel._filter_edit.setText("1700-1750")
    assert panel._list.count() == 1
    panel._filter_edit.setText("3200–3600")
    assert panel._list.count() == 1


# ── Main-window workflow ─────────────────────────────────────────────────────


def test_detect_peaks_keeps_peaks_that_carry_an_assignment(qtbot) -> None:
    """Re-running detection silently discarded every assignment."""
    window = _window(qtbot)
    spectrum = Spectrum(
        wavenumbers=_WN.copy(), intensities=_absorbance(), y_unit=SpectralUnit.ABSORBANCE
    )
    window._apply_project_to_ui(Project(name="p", spectrum=spectrum))
    window._on_detect_peaks()
    assert len(window._project.peaks) == len(_BANDS)

    assigned = next(p for p in window._project.peaks if abs(p.position - 1715.0) < 2.0)
    assigned.vibration_labels = ["ν(C=O)"]
    assigned.vibration_ids = [None]

    window._on_detect_peaks()
    assert any(p is assigned for p in window._project.peaks)
    assert assigned.vibration_labels == ["ν(C=O)"]
    # No duplicate of the assigned band, and the rest is still detected.
    assert len(window._project.peaks) == len(_BANDS)
    assert "1 assigned kept" in window.statusBar().currentMessage()


def test_delete_removes_every_selected_row_as_one_undo_step(qtbot) -> None:
    window = _window(qtbot)
    spectrum = Spectrum(
        wavenumbers=_WN.copy(), intensities=_absorbance(), y_unit=SpectralUnit.ABSORBANCE
    )
    window._apply_project_to_ui(Project(name="p", spectrum=spectrum))
    window._on_detect_peaks()
    window._peak_table._table.selectAll()

    window._on_delete_peak()
    assert window._project.peaks == []

    window._undo_stack.undo()
    assert len(window._project.peaks) == len(_BANDS)


def test_save_writes_to_the_open_project_without_asking_again(qtbot, tmp_path, monkeypatch) -> None:
    """Ctrl+S opened the Save As dialog every single time."""
    window = _window(qtbot)
    spectrum = Spectrum(
        wavenumbers=_WN.copy(), intensities=_absorbance(), y_unit=SpectralUnit.ABSORBANCE
    )
    window._apply_project_to_ui(Project(name="p", spectrum=spectrum))
    monkeypatch.setattr(window, "_refresh_saved_project_names", lambda: None)
    monkeypatch.setattr(window, "_register_saved_project_as_reference", lambda _path: None)

    destination = tmp_path / "sample.irproj"
    asked: list[int] = []

    def _ask(*_args, **_kwargs):
        asked.append(1)
        return str(destination), ""

    monkeypatch.setattr("ui.main_window.QFileDialog.getSaveFileName", _ask)

    assert window._on_save_project_quick()  # first save: has to ask for a name
    assert asked == [1]
    assert destination.exists()

    window._on_peak_clicked(1715.0, 0.8, 0.9)
    assert window._has_unsaved_changes()
    assert window._on_save_project_quick()  # later saves: straight to the file
    assert asked == [1]
    assert not window._has_unsaved_changes()

    assert window._on_save_project()  # Save As always asks
    assert asked == [1, 1]


def test_report_from_a_converted_view_uses_the_converted_curve(qtbot) -> None:
    """Viewer Y range (%T) was applied to absorbance data: the PDF showed a flat line."""
    window = _window(qtbot)
    spectrum = Spectrum(
        wavenumbers=_WN.copy(), intensities=_absorbance(), y_unit=SpectralUnit.ABSORBANCE
    )
    window._apply_project_to_ui(Project(name="p", spectrum=spectrum))
    window._on_detect_peaks()
    project = window._project
    native_intensities = [peak.intensity for peak in project.peaks]

    same_project, placements = window._project_as_displayed(project)
    assert same_project is project
    assert set(placements) == {id(peak) for peak in project.peaks}

    window._spectrum_widget.set_display_unit(SpectralUnit.TRANSMITTANCE)
    shown, shown_placements = window._project_as_displayed(project)

    assert shown is not project
    assert shown.spectrum.y_unit == SpectralUnit.TRANSMITTANCE
    assert float(shown.spectrum.intensities.max()) == pytest.approx(100.0, abs=0.5)
    assert set(shown_placements) == {id(peak) for peak in shown.peaks}
    y_lo, y_hi = window._spectrum_widget.get_y_view_range()
    assert all(y_lo <= peak.intensity <= y_hi for peak in shown.peaks)
    # The project being edited is left exactly as it was.
    assert project.spectrum is spectrum
    assert [peak.intensity for peak in project.peaks] == native_intensities


# ── Packaging ────────────────────────────────────────────────────────────────


def test_pyside6_is_capped_below_the_release_that_crashes_on_python_311() -> None:
    """PySide6 6.12.0 corrupts None/True refcounts; Python 3.11 then aborts."""
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    dependencies = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["dependencies"]
    pyside = next(dep for dep in dependencies if dep.startswith("PySide6"))
    assert "<6.12" in pyside
