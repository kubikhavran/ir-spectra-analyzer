"""Integration tests for functional-group suggestions in MainWindow."""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _gaussian(wn: np.ndarray, center: float, width: float, height: float) -> np.ndarray:
    return height * np.exp(-0.5 * ((wn - center) / width) ** 2)


def _make_nitrile_spectrum():
    from core.spectrum import Spectrum

    wn = np.linspace(4000.0, 400.0, 3601)
    signal = np.full_like(wn, 0.02) + _gaussian(wn, 2245.0, 7.0, 1.10)
    return Spectrum(wavenumbers=wn, intensities=signal, title="Nitrile")


def _make_db_with_nitrile_preset():
    db = MagicMock()
    db.get_vibration_presets.return_value = [
        {
            "id": 1,
            "name": "ν(C≡N) –C≡N",
            "typical_range_min": 2200.0,
            "typical_range_max": 2270.0,
            "category": "stretch",
            "description": "",
            "color": "#1ABC9C",
            "is_builtin": 1,
        }
    ]
    return db


def _make_settings():
    settings = MagicMock()
    settings.get.return_value = None
    return settings


def test_main_window_creates_functional_group_dock(qtbot):
    from ui.main_window import MainWindow

    window = MainWindow(db=_make_db_with_nitrile_preset(), settings=_make_settings())
    qtbot.addWidget(window)

    assert window._dock_functional_groups.windowTitle() == "Functional Groups"


def test_functional_group_suggestion_assigns_preset_to_selected_peak(qtbot):
    from core.peak import Peak
    from core.project import Project
    from ui.main_window import MainWindow

    spectrum = _make_nitrile_spectrum()
    peak = Peak(position=2245.0, intensity=1.12)

    window = MainWindow(db=_make_db_with_nitrile_preset(), settings=_make_settings())
    qtbot.addWidget(window)
    window._project = Project(name="Nitrile", spectrum=spectrum, peaks=[peak])
    window._spectrum_widget.set_spectrum(spectrum)
    window._spectrum_widget.set_peaks([peak])
    window._peak_table.set_peaks([peak])
    window._peak_table.select_peak(peak)
    window._refresh_functional_group_analysis()
    window._functional_group_panel.set_active_peak(peak)

    nitrile_result = next(
        result for result in window._functional_group_panel._results if result.group_id == "nitrile"
    )
    suggestion = nitrile_result.suggested_bands[0]

    window._on_functional_group_suggestion_selected(suggestion)

    assert peak.vibration_labels == ["ν(C≡N) –C≡N"]
    assert peak.vibration_ids == [1]


def test_main_window_populates_assignment_preview_for_active_peak(qtbot):
    from core.peak import Peak
    from core.project import Project
    from ui.main_window import MainWindow

    spectrum = _make_nitrile_spectrum()
    peak = Peak(position=2245.0, intensity=1.12)

    window = MainWindow(db=_make_db_with_nitrile_preset(), settings=_make_settings())
    qtbot.addWidget(window)
    window._project = Project(name="Nitrile", spectrum=spectrum, peaks=[peak])
    window._spectrum_widget.set_spectrum(spectrum)
    window._spectrum_widget.set_peaks([peak])
    window._peak_table.set_peaks([peak])
    window._peak_table.select_peak(peak)
    window._refresh_functional_group_analysis()

    first_item = window._functional_group_panel._detail_list.item(0)

    assert 'It will assign "ν(C≡N) –C≡N".' in window._functional_group_panel._peak_info_label.text()
    assert "ν(C≡N) –C≡N" in first_item.text()
    assert "Will assign: ν(C≡N) –C≡N" in first_item.toolTip()


def test_delete_peak_clears_peak_context_from_side_panels(qtbot):
    from core.peak import Peak
    from core.project import Project
    from ui.main_window import MainWindow

    spectrum = _make_nitrile_spectrum()
    peak = Peak(position=2245.0, intensity=1.12)

    window = MainWindow(db=_make_db_with_nitrile_preset(), settings=_make_settings())
    qtbot.addWidget(window)
    window._project = Project(name="Nitrile", spectrum=spectrum, peaks=[peak])
    window._spectrum_widget.set_spectrum(spectrum)
    window._refresh_peak_views(peak)
    window._refresh_functional_group_analysis()

    window._on_delete_peak()

    assert window._peak_table.selected_peak() is None
    assert window._functional_group_panel._assignment_preview_map == {}
    assert "Select a peak" in window._functional_group_panel._peak_info_label.text()
    assert window._vibration_panel._hint_label.text() == ""


def test_clear_peaks_clears_peak_context_from_side_panels(qtbot):
    from core.peak import Peak
    from core.project import Project
    from ui.main_window import MainWindow

    spectrum = _make_nitrile_spectrum()
    peak = Peak(position=2245.0, intensity=1.12)

    window = MainWindow(db=_make_db_with_nitrile_preset(), settings=_make_settings())
    qtbot.addWidget(window)
    window._project = Project(name="Nitrile", spectrum=spectrum, peaks=[peak])
    window._spectrum_widget.set_spectrum(spectrum)
    window._refresh_peak_views(peak)
    window._refresh_functional_group_analysis()

    window._on_clear_peaks()

    assert window._project.peaks == []
    assert window._peak_table.selected_peak() is None
    assert window._functional_group_panel._assignment_preview_map == {}
    assert "Select a peak" in window._functional_group_panel._peak_info_label.text()
    assert window._vibration_panel._hint_label.text() == ""


def test_assigning_suggestion_preserves_selected_functional_group(qtbot, monkeypatch):
    from core.functional_groups import (
        DiagnosticBandMatch,
        FunctionalGroupAnalysis,
        FunctionalGroupScore,
    )
    from core.peak import Peak
    from core.project import Project
    from ui.main_window import MainWindow

    peak = Peak(position=1559.0, intensity=0.45)
    spectrum = _make_nitrile_spectrum()
    band = DiagnosticBandMatch(
        band_id="phenol_ring",
        label="Aromatic ring stretches",
        range_min=1490.0,
        range_max=1625.0,
        role="supporting",
        confidence=68.0,
        presence=0.7,
        intensity_match=0.7,
        shape_match=0.7,
        center_fit=0.7,
        matched_wavenumber=1559.0,
        matched_intensity=0.45,
        expected_intensity="m",
        observed_intensity_class="vs",
        color="#7D3C98",
        suggested_preset_names=("ν(C=C) Ar conj. ~1580",),
        source_refs=(),
        source_links=(),
    )
    analysis = FunctionalGroupAnalysis(
        results=(
            FunctionalGroupScore(
                group_id="amine_salt",
                group_name="Amine Salt",
                color="#F39C12",
                score=79.2,
                summary="",
                bands=(),
            ),
            FunctionalGroupScore(
                group_id="phenol",
                group_name="Phenol",
                color="#7D3C98",
                score=43.2,
                summary="",
                bands=(band,),
            ),
        )
    )

    monkeypatch.setattr(
        "processing.functional_group_scoring.score_functional_groups",
        lambda *args, **kwargs: analysis,
    )

    db = MagicMock()
    db.get_vibration_presets.return_value = [
        {
            "id": 1,
            "name": "ν(C=C) Ar conj. ~1580",
            "typical_range_min": 1490.0,
            "typical_range_max": 1625.0,
            "category": "stretch",
            "description": "",
            "color": "#1ABC9C",
            "is_builtin": 1,
        }
    ]

    window = MainWindow(db=db, settings=_make_settings())
    qtbot.addWidget(window)
    window._project = Project(name="Functional", spectrum=spectrum, peaks=[peak])
    window._spectrum_widget.set_spectrum(spectrum)
    window._refresh_peak_views(peak)
    window._refresh_functional_group_analysis()

    window._functional_group_panel._group_list.setCurrentRow(1)
    window._refresh_functional_group_assignment_preview()

    window._on_functional_group_suggestion_selected(band)

    assert peak.vibration_labels == ["ν(C=C) Ar conj. ~1580"]
    assert window._functional_group_panel.current_result().group_id == "phenol"
    assert window._functional_group_panel._group_list.currentRow() == 1
