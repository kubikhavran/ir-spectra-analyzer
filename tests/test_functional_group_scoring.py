"""Tests for functional-group scoring and UI panel."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np


def _gaussian(wn: np.ndarray, center: float, width: float, height: float) -> np.ndarray:
    return height * np.exp(-0.5 * ((wn - center) / width) ** 2)


def _make_absorbance_spectrum(features: list[tuple[float, float, float]], title: str):
    from core.spectrum import Spectrum

    wn = np.linspace(4000.0, 400.0, 3601)
    signal = np.full_like(wn, 0.02)
    for center, width, height in features:
        signal += _gaussian(wn, center, width, height)
    return Spectrum(wavenumbers=wn, intensities=signal, title=title)


def test_functional_group_scoring_ranks_carboxylic_acid_first():
    from processing.functional_group_scoring import score_functional_groups

    spectrum = _make_absorbance_spectrum(
        [
            (3000.0, 180.0, 0.60),  # broad acid OH
            (1710.0, 16.0, 0.90),  # acid carbonyl
            (1260.0, 24.0, 0.40),  # C-O
        ],
        title="Acid",
    )

    analysis = score_functional_groups(spectrum)

    assert analysis.results
    assert analysis.results[0].group_id == "carboxylic_acid"
    assert analysis.results[0].score >= 55.0
    alcohol = next(result for result in analysis.results if result.group_id == "alcohol")
    assert analysis.results[0].score > alcohol.score


def test_functional_group_scoring_ranks_amide_first():
    from processing.functional_group_scoring import score_functional_groups

    spectrum = _make_absorbance_spectrum(
        [
            (3350.0, 55.0, 0.18),  # amide NH
            (1660.0, 14.0, 0.75),  # amide I
            (1545.0, 18.0, 0.35),  # amide II
            (1398.0, 18.0, 0.22),  # amide III / CN
        ],
        title="Amide",
    )

    analysis = score_functional_groups(spectrum)

    assert analysis.results[0].group_id == "amide"
    assert analysis.results[0].score >= 50.0


def test_functional_group_scoring_ranks_nitrile_first():
    from processing.functional_group_scoring import score_functional_groups

    spectrum = _make_absorbance_spectrum(
        [
            (2245.0, 7.0, 1.10),  # nitrile
        ],
        title="Nitrile",
    )

    analysis = score_functional_groups(spectrum)

    assert analysis.results[0].group_id == "nitrile"
    assert analysis.results[0].score >= 60.0
    assert analysis.results[0].source_links
    assert analysis.results[0].bands[0].source_links


def test_functional_group_scoring_ranks_amine_above_alcohol_for_amine_pattern():
    from processing.functional_group_scoring import score_functional_groups

    spectrum = _make_absorbance_spectrum(
        [
            (3380.0, 45.0, 0.28),  # amine NH
            (1605.0, 14.0, 0.32),  # NH bend
            (1250.0, 18.0, 0.26),  # CN
        ],
        title="Amine",
    )

    analysis = score_functional_groups(spectrum)

    assert analysis.results[0].group_id == "amine"
    alcohol = next(result for result in analysis.results if result.group_id == "alcohol")
    assert analysis.results[0].score >= 70.0
    assert analysis.results[0].score > alcohol.score


def test_functional_group_scoring_ranks_phenol_first():
    from processing.functional_group_scoring import score_functional_groups

    spectrum = _make_absorbance_spectrum(
        [
            (3430.0, 90.0, 0.34),  # broad phenolic OH
            (1595.0, 10.0, 0.22),  # aromatic ring
            (1505.0, 10.0, 0.20),  # aromatic ring
            (1360.0, 16.0, 0.28),  # Ar-OH bend
            (750.0, 12.0, 0.22),  # aromatic out-of-plane CH
        ],
        title="Phenol",
    )

    analysis = score_functional_groups(spectrum)

    assert analysis.results[0].group_id == "phenol"
    assert analysis.results[0].score >= 70.0


def test_functional_group_scoring_ranks_carboxylate_first():
    from processing.functional_group_scoring import score_functional_groups

    spectrum = _make_absorbance_spectrum(
        [
            (1560.0, 12.0, 0.45),  # asym COO-
            (1410.0, 12.0, 0.40),  # sym COO-
        ],
        title="Carboxylate",
    )

    analysis = score_functional_groups(spectrum)

    assert analysis.results[0].group_id == "carboxylate"
    assert analysis.results[0].score >= 60.0


def test_functional_group_scoring_ranks_oxime_first():
    from processing.functional_group_scoring import score_functional_groups

    spectrum = _make_absorbance_spectrum(
        [
            (1660.0, 10.0, 0.42),  # oxime C=N
            (945.0, 10.0, 0.34),  # oxime N-O
        ],
        title="Oxime",
    )

    analysis = score_functional_groups(spectrum)

    assert analysis.results[0].group_id == "oxime"
    assert analysis.results[0].score >= 70.0


def test_functional_group_scoring_downranks_alkene_for_aromatic_pattern():
    from processing.functional_group_scoring import score_functional_groups

    spectrum = _make_absorbance_spectrum(
        [
            (1600.0, 10.0, 0.24),  # aromatic ring
            (1495.0, 10.0, 0.20),  # aromatic ring
            (750.0, 12.0, 0.26),  # out-of-plane CH
            (3035.0, 12.0, 0.10),  # aromatic CH
        ],
        title="Aromatic",
    )

    analysis = score_functional_groups(spectrum)

    assert analysis.results[0].group_id == "aromatic_ring"
    alkene = next(result for result in analysis.results if result.group_id == "alkene")
    assert analysis.results[0].score >= 60.0
    assert analysis.results[0].score > alkene.score


def test_functional_group_score_marks_missing_required_bands():
    from processing.functional_group_scoring import score_functional_groups

    spectrum = _make_absorbance_spectrum(
        [
            (1715.0, 14.0, 0.95),  # carbonyl only, no acid OH
        ],
        title="Carbonyl only",
    )

    analysis = score_functional_groups(spectrum)
    acid = next(result for result in analysis.results if result.group_id == "carboxylic_acid")

    assert acid.missing_bands
    assert any(band.is_missing_required for band in acid.bands)


def test_functional_group_panel_shows_results_and_suggestions(qtbot):
    from core.peak import Peak
    from processing.functional_group_scoring import score_functional_groups
    from ui.functional_group_panel import FunctionalGroupPanel

    spectrum = _make_absorbance_spectrum(
        [
            (2245.0, 7.0, 1.10),
        ],
        title="Nitrile",
    )
    analysis = score_functional_groups(spectrum)

    panel = FunctionalGroupPanel()
    qtbot.addWidget(panel)
    panel.set_results(list(analysis.results))
    panel.set_active_peak(Peak(position=2245.0, intensity=1.10))
    nitrile = next(result for result in analysis.results if result.group_id == "nitrile")
    panel.set_assignment_preview_map(
        {nitrile.suggested_bands[0].band_id: "ν(C≡N) –C≡N"}
    )

    assert panel._group_list.count() >= 1
    assert "Nitrile" in panel._group_list.item(0).text()
    assert panel._detail_list.count() >= 1
    assert "Sources:" in panel._group_info_label.text()
    assert 'href="' in panel._group_info_label.text()
    assert "Matched:" in panel._group_info_label.text()
    assert "Best assignable match:" in panel._peak_info_label.text()
    assert 'It will assign "ν(C≡N) –C≡N".' in panel._peak_info_label.text()
    assert "Assign" in panel._detail_list.item(0).text()
    assert "ν(C≡N) –C≡N" in panel._detail_list.item(0).text()
    assert "Will assign: ν(C≡N) –C≡N" in panel._detail_list.item(0).toolTip()
    assert "Double-click to assign" in panel._detail_list.item(0).toolTip()


def test_spectrum_widget_diagnostic_regions(qtbot):
    from processing.functional_group_scoring import score_functional_groups
    from ui.spectrum_widget import SpectrumWidget

    spectrum = _make_absorbance_spectrum(
        [
            (1710.0, 16.0, 0.90),
            (1260.0, 24.0, 0.40),
        ],
        title="Ester-like",
    )
    analysis = score_functional_groups(spectrum)

    widget = SpectrumWidget()
    qtbot.addWidget(widget)
    widget.set_spectrum(spectrum)
    widget.set_diagnostic_regions(list(analysis.results[0].bands))

    assert len(widget._diagnostic_region_items) == len(analysis.results[0].bands)


def test_spectrum_widget_styles_missing_required_region(qtbot):
    from processing.functional_group_scoring import score_functional_groups
    from ui.spectrum_widget import SpectrumWidget

    spectrum = _make_absorbance_spectrum(
        [
            (1715.0, 14.0, 0.95),
        ],
        title="Carbonyl only",
    )
    analysis = score_functional_groups(spectrum)
    acid = next(result for result in analysis.results if result.group_id == "carboxylic_acid")
    missing_band = next(band for band in acid.bands if band.is_missing_required)

    widget = SpectrumWidget()
    qtbot.addWidget(widget)
    brush, pen = widget._diagnostic_region_style(missing_band)

    assert brush.alpha() > 0
    assert pen.color().name().lower() == "#c0392b"
