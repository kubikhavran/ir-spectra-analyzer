"""Tests for functional-group scoring and UI panel."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest


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


def test_functional_group_repository_contains_common_backbone_groups():
    from storage.functional_group_repository import FunctionalGroupRepository

    knowledge_base = FunctionalGroupRepository().load()
    group_ids = {group.id for group in knowledge_base.groups}

    assert "aliphatic_hydrocarbon" in group_ids
    assert "methylene_rich_alkyl" in group_ids
    assert "methyl_rich_alkyl" in group_ids
    assert "long_chain_n_alkyl" in group_ids
    assert "monosubstituted_benzene" in group_ids
    assert "ortho_disubstituted_benzene" in group_ids
    assert "meta_disubstituted_benzene" in group_ids
    assert "para_disubstituted_benzene" in group_ids
    assert "trisubstituted_benzene_1_2_4" in group_ids
    assert "trisubstituted_benzene_1_2_3" in group_ids
    assert "trisubstituted_benzene_1_3_5" in group_ids
    assert "primary_alcohol" in group_ids
    assert "secondary_alcohol" in group_ids
    assert "primary_amide" in group_ids
    assert "secondary_amide" in group_ids
    assert "primary_amine" in group_ids
    assert "secondary_amine" in group_ids
    assert "tertiary_alcohol" in group_ids
    assert "isopropyl_group" in group_ids
    assert "tert_butyl_group" in group_ids
    assert "terminal_alkene" in group_ids
    assert "vinylidene_alkene" in group_ids
    assert "trans_disubstituted_alkene" in group_ids
    assert "cis_disubstituted_alkene" in group_ids
    assert "trisubstituted_alkene" in group_ids
    assert "benzene" in group_ids


@pytest.mark.parametrize(
    ("group_id", "features", "minimum_score"),
    [
        (
            "methylene_rich_alkyl",
            [(2926.0, 9.0, 0.34), (2852.0, 9.0, 0.32), (1455.0, 10.0, 0.25)],
            55.0,
        ),
        (
            "methyl_rich_alkyl",
            [(2962.0, 9.0, 0.30), (2872.0, 9.0, 0.28), (1460.0, 10.0, 0.22), (1375.0, 9.0, 0.26)],
            55.0,
        ),
        (
            "long_chain_n_alkyl",
            [(2926.0, 9.0, 0.32), (2852.0, 9.0, 0.30), (1455.0, 10.0, 0.22), (723.0, 8.0, 0.28)],
            60.0,
        ),
        (
            "monosubstituted_benzene",
            [(3030.0, 10.0, 0.10), (1600.0, 10.0, 0.22), (1495.0, 10.0, 0.20), (750.0, 8.0, 0.30), (700.0, 8.0, 0.22)],
            60.0,
        ),
        (
            "ortho_disubstituted_benzene",
            [(3030.0, 10.0, 0.08), (1600.0, 10.0, 0.22), (1495.0, 10.0, 0.20), (755.0, 8.0, 0.30), (685.0, 8.0, 0.10)],
            55.0,
        ),
        (
            "meta_disubstituted_benzene",
            [(1600.0, 10.0, 0.22), (1495.0, 10.0, 0.20), (880.0, 8.0, 0.28), (780.0, 8.0, 0.24), (700.0, 8.0, 0.18)],
            60.0,
        ),
        (
            "para_disubstituted_benzene",
            [(3030.0, 10.0, 0.08), (1600.0, 10.0, 0.22), (1495.0, 10.0, 0.20), (810.0, 8.0, 0.28)],
            55.0,
        ),
        (
            "trisubstituted_benzene_1_2_4",
            [(1600.0, 10.0, 0.22), (1495.0, 10.0, 0.20), (875.0, 8.0, 0.24), (812.0, 8.0, 0.26), (705.0, 8.0, 0.18)],
            60.0,
        ),
        (
            "trisubstituted_benzene_1_2_3",
            [(1600.0, 10.0, 0.22), (1495.0, 10.0, 0.20), (705.0, 8.0, 0.18), (780.0, 8.0, 0.26)],
            60.0,
        ),
        (
            "trisubstituted_benzene_1_3_5",
            [(1600.0, 10.0, 0.22), (1495.0, 10.0, 0.20), (705.0, 8.0, 0.18), (860.0, 8.0, 0.24)],
            60.0,
        ),
        (
            "primary_alcohol",
            [(3360.0, 80.0, 0.32), (1062.0, 10.0, 0.40), (1295.0, 12.0, 0.18)],
            65.0,
        ),
        (
            "secondary_alcohol",
            [(3360.0, 80.0, 0.32), (1102.0, 10.0, 0.38), (1295.0, 12.0, 0.18)],
            65.0,
        ),
        (
            "tertiary_alcohol",
            [(3380.0, 85.0, 0.30), (1165.0, 10.0, 0.34), (1370.0, 12.0, 0.22)],
            60.0,
        ),
        (
            "primary_amide",
            [
                (3385.0, 16.0, 0.16),
                (3195.0, 16.0, 0.14),
                (1662.0, 10.0, 0.70),
                (1625.0, 10.0, 0.28),
                (1410.0, 8.0, 0.18),
                (690.0, 10.0, 0.12),
            ],
            60.0,
        ),
        (
            "secondary_amide",
            [(3315.0, 35.0, 0.20), (1658.0, 10.0, 0.72), (1325.0, 10.0, 0.26), (725.0, 10.0, 0.16)],
            60.0,
        ),
        (
            "primary_amine",
            [(3450.0, 12.0, 0.14), (3360.0, 12.0, 0.12), (1605.0, 10.0, 0.30), (1060.0, 10.0, 0.20), (780.0, 12.0, 0.12)],
            60.0,
        ),
        (
            "secondary_amine",
            [(3340.0, 16.0, 0.18), (1535.0, 10.0, 0.24), (1180.0, 8.0, 0.30), (725.0, 10.0, 0.12)],
            60.0,
        ),
        (
            "isopropyl_group",
            [(2962.0, 9.0, 0.26), (2872.0, 9.0, 0.24), (1372.0, 9.0, 0.30), (1170.0, 6.0, 0.32)],
            60.0,
        ),
        (
            "tert_butyl_group",
            [(2962.0, 9.0, 0.24), (2872.0, 9.0, 0.22), (1375.0, 9.0, 0.28), (927.0, 6.0, 0.34), (1460.0, 10.0, 0.20)],
            60.0,
        ),
        (
            "terminal_alkene",
            [(3080.0, 12.0, 0.14), (1642.0, 10.0, 0.28), (910.0, 8.0, 0.30), (988.0, 8.0, 0.26)],
            60.0,
        ),
        (
            "vinylidene_alkene",
            [(3086.0, 10.0, 0.16), (1644.0, 10.0, 0.28), (890.0, 7.0, 0.32), (1412.0, 10.0, 0.18)],
            60.0,
        ),
        (
            "trans_disubstituted_alkene",
            [(3070.0, 12.0, 0.10), (1650.0, 10.0, 0.26), (967.0, 7.0, 0.34), (1325.0, 8.0, 0.22)],
            60.0,
        ),
        (
            "cis_disubstituted_alkene",
            [(1650.0, 10.0, 0.28), (1380.0, 10.0, 0.22), (705.0, 8.0, 0.30)],
            60.0,
        ),
        (
            "trisubstituted_alkene",
            [(1668.0, 8.0, 0.24), (820.0, 8.0, 0.26), (3065.0, 12.0, 0.08)],
            55.0,
        ),
        (
            "benzene",
            [(3030.0, 10.0, 0.08), (1600.0, 10.0, 0.22), (1495.0, 10.0, 0.20), (670.0, 8.0, 0.26)],
            55.0,
        ),
        ("acid_halide", [(1792.0, 7.0, 0.95)], 60.0),
        ("anhydride", [(1812.0, 8.0, 0.90), (1760.0, 8.0, 0.82)], 70.0),
        ("aliphatic_ether", [(1120.0, 12.0, 0.70)], 55.0),
        ("aryl_ether", [(1245.0, 10.0, 0.58), (1600.0, 9.0, 0.20), (1500.0, 9.0, 0.18)], 55.0),
        ("amine_salt", [(2920.0, 55.0, 0.42), (1560.0, 12.0, 0.24), (1105.0, 14.0, 0.18)], 55.0),
        (
            "aromatic_amine",
            [
                (3400.0, 45.0, 0.18),
                (1305.0, 12.0, 0.28),
                (1600.0, 10.0, 0.20),
                (1500.0, 10.0, 0.18),
            ],
            55.0,
        ),
        ("azide", [(2145.0, 6.0, 1.00)], 70.0),
        ("isocyanate", [(2265.0, 6.0, 1.00), (1410.0, 10.0, 0.22)], 70.0),
        ("thiocyanate", [(2150.0, 6.0, 0.88)], 45.0),
        ("carbodiimide", [(2132.0, 6.0, 0.92)], 60.0),
        ("isothiocyanate", [(2065.0, 8.0, 0.82)], 50.0),
        ("allene", [(1955.0, 8.0, 0.55)], 55.0),
        ("thiol", [(2570.0, 7.0, 0.34)], 55.0),
        ("sulfoxide", [(1048.0, 10.0, 0.95)], 65.0),
        ("sulfone", [(1325.0, 9.0, 0.62), (1145.0, 9.0, 0.55)], 65.0),
        ("sulfonamide", [(3360.0, 45.0, 0.16), (1343.0, 8.0, 0.52), (1162.0, 8.0, 0.44)], 60.0),
        ("sulfonyl_chloride", [(1392.0, 8.0, 0.58), (1175.0, 8.0, 0.48)], 60.0),
        ("sulfate", [(1400.0, 8.0, 0.55), (1192.0, 8.0, 0.44)], 55.0),
        ("sulfonate", [(1352.0, 8.0, 0.58), (1180.0, 8.0, 0.46)], 60.0),
        ("vinyl_ether", [(1210.0, 8.0, 0.52), (3075.0, 10.0, 0.14), (988.0, 8.0, 0.30)], 60.0),
    ],
)
def test_functional_group_scoring_ranks_expanded_groups_first(group_id, features, minimum_score):
    from processing.functional_group_scoring import score_functional_groups

    spectrum = _make_absorbance_spectrum(features, title=group_id)

    analysis = score_functional_groups(spectrum)

    assert analysis.results[0].group_id == group_id
    assert analysis.results[0].score >= minimum_score


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
    panel.set_assignment_preview_map({nitrile.suggested_bands[0].band_id: "ν(C≡N) –C≡N"})

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


def test_spectrum_widget_can_hide_and_restore_diagnostic_regions(qtbot):
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

    widget.set_diagnostic_regions_visible(False)
    assert len(widget._diagnostic_region_items) == 0

    widget.set_diagnostic_regions_visible(True)
    assert len(widget._diagnostic_region_items) == len(analysis.results[0].bands)
