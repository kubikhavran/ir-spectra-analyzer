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
from PySide6.QtCore import QPointF, Qt

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


def _dim_transmittance(factor: float = 0.5) -> Spectrum:
    """A %T spectrum whose whole baseline sits at ``100 * factor`` %."""
    spectrum = _transmittance()
    return replace(spectrum, intensities=spectrum.intensities * factor)


def _legacy_corrected(spectrum: Spectrum) -> np.ndarray:
    """Corrected %T as versions up to 0.29 stored it: hull subtracted, bands below zero."""
    return spectrum.intensities - float(spectrum.intensities.max())


def test_baseline_correction_moves_existing_peaks_onto_the_corrected_curve() -> None:
    """Labels used to stay at the raw intensity, far from the corrected curve."""
    spectrum = _dim_transmittance()
    project = Project(name="p", spectrum=spectrum)
    peak = Peak(position=1715.0, intensity=float(np.interp(1715.0, _WN, spectrum.intensities)))
    project.add_peak(peak)
    raw_intensity = peak.intensity

    corrected = replace(
        spectrum, intensities=rubber_band_baseline(_WN, spectrum.intensities, upper=True)
    )
    command = CorrectBaselineCommand(project, corrected)
    command.redo()

    assert peak.intensity == pytest.approx(float(np.interp(1715.0, _WN, corrected.intensities)))
    assert peak.intensity == pytest.approx(2.0 * raw_intensity, rel=1e-3)

    command.undo()
    assert peak.intensity == pytest.approx(raw_intensity)
    assert project.corrected_spectrum is None


def test_baseline_correction_keeps_the_curve_in_view(qtbot) -> None:
    """The Y range of the raw curve was kept, so the corrected one was off screen."""
    window = _window(qtbot)
    window._apply_project_to_ui(Project(name="p", spectrum=_dim_transmittance()))
    raw = window._project.spectrum
    assert float(raw.intensities.max()) == pytest.approx(50.0)

    window._on_correct_baseline()

    corrected = window._project.corrected_spectrum
    assert corrected is not None
    assert float(corrected.intensities.max()) == pytest.approx(100.0)
    y_lo, y_hi = window._spectrum_widget.get_y_view_range()
    assert y_lo <= float(corrected.intensities.min())
    assert y_hi >= float(corrected.intensities.max())

    window._undo_stack.undo()
    y_lo, y_hi = window._spectrum_widget.get_y_view_range()
    assert y_lo <= float(raw.intensities.min())
    assert float(raw.intensities.max()) <= y_hi < 90.0


def test_corrected_transmittance_stays_usable_as_transmittance(qtbot) -> None:
    """Dividing the baseline out leaves real %T: the unit switch must still be offered."""
    window = _window(qtbot)
    window._apply_project_to_ui(Project(name="p", spectrum=_dim_transmittance()))
    window._on_correct_baseline()

    corrected = window._project.corrected_spectrum
    assert corrected.y_unit == SpectralUnit.TRANSMITTANCE
    assert corrected.is_dip_spectrum
    assert SpectralUnit.ABSORBANCE in corrected.convertible_units()
    widget = window._spectrum_widget
    assert "baseline corrected" in widget._plot_widget.getAxis("left").labelText

    # A raw %T reference is drawn as it is — both curves share the %T scale.
    reference = _transmittance(depth=30.0)
    assert widget._overlay_in_display_unit(reference) is reference


def test_weak_legacy_corrected_transmittance_is_still_read_as_dips() -> None:
    """Bands shallower than 5 %T fell under a fixed threshold and flipped polarity."""
    corrected = _legacy_corrected(_transmittance(depth=4.0))
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


def test_a_weak_legacy_corrected_query_matches_its_own_raw_spectrum() -> None:
    weak = _transmittance(depth=4.0)
    raw_vector = _vector(weak.intensities, SpectralUnit.TRANSMITTANCE)
    corrected_vector = _vector(_legacy_corrected(weak), SpectralUnit.BASELINE_CORRECTED)
    assert cosine_similarity(raw_vector, corrected_vector) > 0.99


def test_real_absorbance_is_not_flipped() -> None:
    absorbance = _vector(_absorbance(), SpectralUnit.ABSORBANCE)
    transmittance = _vector(_transmittance().intensities, SpectralUnit.TRANSMITTANCE)
    assert cosine_similarity(absorbance, transmittance) > 0.9


# ── Viewer ───────────────────────────────────────────────────────────────────


def test_overlay_is_drawn_on_the_scale_of_a_legacy_corrected_spectrum(qtbot) -> None:
    """A raw %T reference sat near 100 while the corrected curve sat at zero."""
    widget = SpectrumWidget()
    qtbot.addWidget(widget)
    raw = _transmittance()
    widget.set_spectrum(
        replace(raw, intensities=_legacy_corrected(raw), y_unit=SpectralUnit.BASELINE_CORRECTED)
    )

    overlay = widget._overlay_in_display_unit(_transmittance(depth=30.0))
    assert float(np.nanmax(overlay.intensities)) <= 1e-6
    assert float(np.nanmin(overlay.intensities)) < -5.0

    absorbance_reference = Spectrum(
        wavenumbers=_WN.copy(), intensities=_absorbance(), y_unit=SpectralUnit.ABSORBANCE
    )
    aligned = widget._overlay_in_display_unit(absorbance_reference)
    assert float(np.nanmax(aligned.intensities)) <= 1e-6


class _Click:
    """Stand-in for the scene click event the plot hands to the viewer."""

    def __init__(self, scene_pos, modifiers=Qt.KeyboardModifier.NoModifier) -> None:
        self._scene_pos = scene_pos
        self._modifiers = modifiers

    def scenePos(self):  # noqa: N802 (Qt naming)
        return self._scene_pos

    def modifiers(self):
        return self._modifiers


def test_add_peak_marks_exactly_the_clicked_point(qtbot) -> None:
    """Any point of the spectrum can be labelled; only Ctrl+click goes to the apex."""
    widget = SpectrumWidget()
    qtbot.addWidget(widget)
    widget.resize(1000, 600)
    widget.show()
    qtbot.waitExposed(widget)
    widget.set_spectrum(
        Spectrum(wavenumbers=_WN.copy(), intensities=_absorbance(), y_unit=SpectralUnit.ABSORBANCE)
    )
    widget.set_tool_mode("add_peak")
    view_box = widget._plot_widget.getPlotItem().vb
    scene_pos = view_box.mapViewToScene(QPointF(1700.0, 0.5))
    added: list[tuple[float, float, float]] = []
    widget.peak_clicked.connect(lambda wn, intensity, y: added.append((wn, intensity, y)))

    widget._handle_mouse_clicked(_Click(scene_pos), widget._plot_widget)
    assert len(added) == 1
    assert added[0][0] == pytest.approx(1700.0, abs=0.01)  # on the slope, where clicked
    assert added[0][1] == pytest.approx(float(np.interp(1700.0, _WN, _absorbance())), rel=1e-6)

    widget._handle_mouse_clicked(
        _Click(scene_pos, Qt.KeyboardModifier.ControlModifier), widget._plot_widget
    )
    assert len(added) == 2
    assert added[1][0] == pytest.approx(1715.0, abs=1.0)  # the apex of that band


def test_snap_helper_finds_the_apex_only_when_it_is_in_reach(qtbot) -> None:
    """Ctrl+click snapping: the apex within the window, otherwise the click itself."""
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


def test_clicking_a_vibration_only_shows_its_range(qtbot) -> None:
    """A click used to assign straight away, so the list could not be browsed."""
    window = _window(qtbot)
    spectrum = Spectrum(
        wavenumbers=_WN.copy(), intensities=_absorbance(), y_unit=SpectralUnit.ABSORBANCE
    )
    window._apply_project_to_ui(Project(name="p", spectrum=spectrum))
    window._on_detect_peaks()
    peak = next(p for p in window._project.peaks if abs(p.position - 1715.0) < 2.0)
    window._on_peak_selected_in_viewer(peak)

    panel = window._vibration_panel
    panel.set_presets(
        [VibrationPreset(name="ν(C=O)", typical_range_min=1700.0, typical_range_max=1750.0)]
    )
    panel.highlight_for_peak(peak.position)
    item = panel._list.item(0)

    panel._list.setCurrentItem(item)
    panel._list.itemClicked.emit(item)
    assert peak.vibration_labels == []
    assert window._spectrum_widget.vibration_range() == (1700.0, 1750.0)
    assert window._undo_stack.undoText() == "Detect peaks"  # nothing was written
    assert "double-click" in panel._hint_label.text()

    # The explicit ways to assign: the button (or Enter) and a double-click.
    assert panel._assign_btn.isEnabled()
    assert "1715" in panel._assign_btn.text()
    panel._assign_btn.click()
    assert peak.vibration_labels == ["ν(C=O)"]

    window._undo_stack.undo()
    assert peak.vibration_labels == []
    panel._list.itemDoubleClicked.emit(panel._list.item(0))
    assert peak.vibration_labels == ["ν(C=O)"]


def test_assign_button_is_off_without_a_selected_peak(qtbot) -> None:
    panel = VibrationPanel()
    qtbot.addWidget(panel)
    panel.set_presets(
        [VibrationPreset(name="ν(C=O)", typical_range_min=1700.0, typical_range_max=1750.0)]
    )
    panel._list.setCurrentRow(0)
    assert not panel._assign_btn.isEnabled()

    panel.set_active_peak(Peak(position=1715.0, intensity=0.8))
    assert panel._assign_btn.isEnabled()
    panel.clear_peak_context()
    assert not panel._assign_btn.isEnabled()


def _faint_and_strong() -> Spectrum:
    intensities = np.zeros_like(_WN)
    for centre, height in ((3000.0, 1.0), (1700.0, 0.3), (1200.0, 0.05), (800.0, 0.006)):
        intensities += height * np.exp(-((_WN - centre) ** 2) / (2 * 15.0**2))
    return Spectrum(wavenumbers=_WN.copy(), intensities=intensities, y_unit=SpectralUnit.ABSORBANCE)


def test_sensitivity_slider_redetects_live_as_one_undo_step(qtbot) -> None:
    """Detection had one fixed threshold; faint bands could not be picked up at all."""
    window = _window(qtbot)
    window._apply_project_to_ui(Project(name="p", spectrum=_faint_and_strong()))
    slider = window._toolbar._sensitivity_slider
    assert window._toolbar.sensitivity() == 5

    window._on_detect_peaks()
    assert len(window._project.peaks) == 3
    assert "sensitivity 5" in window.statusBar().currentMessage()

    slider.setValue(10)
    assert len(window._project.peaks) == 4
    window._settings.set.assert_any_call("peak_sensitivity", 10)
    slider.setValue(1)
    assert len(window._project.peaks) == 2

    # However often the slider moved, one Ctrl+Z takes the detection back.
    window._undo_stack.undo()
    assert window._project.peaks == []
    assert not window._undo_stack.canUndo()


def test_sensitivity_slider_leaves_later_work_alone(qtbot) -> None:
    """Once something else was done after detecting, the slider must not redo it."""
    window = _window(qtbot)
    window._apply_project_to_ui(Project(name="p", spectrum=_faint_and_strong()))
    window._on_detect_peaks()
    window._on_peak_clicked(2500.0, 0.0, 0.1)  # a hand-placed peak
    assert len(window._project.peaks) == 4

    window._toolbar._sensitivity_slider.setValue(1)
    assert len(window._project.peaks) == 4
    assert "press Detect Peaks" in window.statusBar().currentMessage()


def test_stored_sensitivity_is_restored_on_start(qtbot) -> None:
    db = MagicMock()
    db.get_vibration_presets.return_value = []
    settings = MagicMock()
    settings.get.side_effect = lambda key, default=None: 8 if key == "peak_sensitivity" else None
    window = MainWindow(db=db, settings=settings)
    qtbot.addWidget(window)
    assert window._toolbar.sensitivity() == 8
    settings.set.assert_not_called()


# ── Packaging ────────────────────────────────────────────────────────────────


def test_pyside6_is_capped_below_the_release_that_crashes_on_python_311() -> None:
    """PySide6 6.12.0 corrupts None/True refcounts; Python 3.11 then aborts."""
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    dependencies = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["dependencies"]
    pyside = next(dep for dep in dependencies if dep.startswith("PySide6"))
    assert "<6.12" in pyside
