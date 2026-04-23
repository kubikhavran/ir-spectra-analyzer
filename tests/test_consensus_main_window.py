"""Integration tests for Consensus panel wiring in MainWindow."""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _gaussian(wn: np.ndarray, center: float, width: float, height: float) -> np.ndarray:
    return height * np.exp(-0.5 * ((wn - center) / width) ** 2)


def _make_spectrum():
    from core.spectrum import Spectrum

    wn = np.linspace(4000.0, 400.0, 3601)
    signal = np.full_like(wn, 0.02) + _gaussian(wn, 1600.0, 18.0, 0.80)
    return Spectrum(wavenumbers=wn, intensities=signal, title="Consensus")


def _make_db():
    db = MagicMock()
    db.get_vibration_presets.return_value = []
    return db


def _make_settings():
    settings = MagicMock()
    settings.get.return_value = None
    return settings


def _make_fake_analysis():
    from core.functional_groups import (
        DiagnosticBandMatch,
        FunctionalGroupAnalysis,
        FunctionalGroupScore,
    )

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
        observed_intensity_class="s",
        color="#7D3C98",
        suggested_preset_names=("ν(C=C) Ar conj. ~1580",),
        source_refs=(),
        source_links=(),
    )
    return FunctionalGroupAnalysis(
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


def test_main_window_creates_consensus_dock(qtbot):
    from ui.main_window import MainWindow

    window = MainWindow(db=_make_db(), settings=_make_settings())
    qtbot.addWidget(window)

    assert window._dock_consensus.windowTitle() == "Consensus"


def test_consensus_panel_navigation_selects_functional_group_and_match(qtbot, monkeypatch):
    from app.reference_library_service import ReferenceSearchOutcome
    from core.project import Project
    from matching.search_engine import MatchResult
    from ui.main_window import MainWindow

    monkeypatch.setattr(
        "processing.functional_group_scoring.score_functional_groups",
        lambda *args, **kwargs: _make_fake_analysis(),
    )

    spectrum = _make_spectrum()
    window = MainWindow(db=_make_db(), settings=_make_settings())
    qtbot.addWidget(window)
    window._project = Project(name="Consensus", spectrum=spectrum)
    window._spectrum_widget.set_spectrum(spectrum)
    window._reference_library_service.get_reference_spectrum = lambda _ref_id: {
        "wavenumbers": spectrum.wavenumbers,
        "intensities": spectrum.intensities,
        "name": "Reference B",
    }

    window._refresh_functional_group_analysis()
    outcome = ReferenceSearchOutcome(
        results=(
            MatchResult(ref_id=1, name="Reference A", score=0.74),
            MatchResult(ref_id=2, name="Reference B", score=0.70),
        ),
        references=(
            {"id": 1, "name": "Reference A"},
            {"id": 2, "name": "Reference B"},
        ),
    )
    window._apply_match_spectrum_outcome(outcome)

    window._consensus_panel._hypothesis_list.setCurrentRow(1)
    window._consensus_panel._match_list.setCurrentRow(1)

    assert window._functional_group_panel.current_result().group_id == "phenol"
    assert window._match_results_panel._list.currentRow() == 1


def test_consensus_navigation_does_not_raise_other_docks(qtbot, monkeypatch):
    from app.reference_library_service import ReferenceSearchOutcome
    from core.project import Project
    from matching.search_engine import MatchResult
    from ui.main_window import MainWindow

    monkeypatch.setattr(
        "processing.functional_group_scoring.score_functional_groups",
        lambda *args, **kwargs: _make_fake_analysis(),
    )

    spectrum = _make_spectrum()
    window = MainWindow(db=_make_db(), settings=_make_settings())
    qtbot.addWidget(window)
    window._project = Project(name="Consensus", spectrum=spectrum)
    window._spectrum_widget.set_spectrum(spectrum)
    window._reference_library_service.get_reference_spectrum = lambda _ref_id: {
        "wavenumbers": spectrum.wavenumbers,
        "intensities": spectrum.intensities,
        "name": "Reference B",
    }

    window._refresh_functional_group_analysis()
    outcome = ReferenceSearchOutcome(
        results=(
            MatchResult(ref_id=1, name="Reference A", score=0.74),
            MatchResult(ref_id=2, name="Reference B", score=0.70),
        ),
        references=(
            {"id": 1, "name": "Reference A"},
            {"id": 2, "name": "Reference B"},
        ),
    )
    window._apply_match_spectrum_outcome(outcome)

    raised = {"functional_groups": 0, "match": 0}
    monkeypatch.setattr(
        window._dock_functional_groups,
        "raise_",
        lambda: raised.__setitem__("functional_groups", raised["functional_groups"] + 1),
    )
    monkeypatch.setattr(
        window._dock_match,
        "raise_",
        lambda: raised.__setitem__("match", raised["match"] + 1),
    )

    window._consensus_panel._hypothesis_list.setCurrentRow(1)
    window._consensus_panel._match_list.setCurrentRow(1)

    assert raised == {"functional_groups": 0, "match": 0}
