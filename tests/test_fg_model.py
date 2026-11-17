"""The learned functional-group model and the structure check, on real spectra."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from core.spectrum import SpectralUnit, Spectrum
from file_io.spa_reader import SPAReader
from processing import fg_model
from processing.fg_features import N_FEATURES, spectrum_features
from processing.functional_group_scoring import RULE_ONLY_FACTOR, score_functional_groups
from processing.structure_check import FOUND, NOT_SEEN, check_structure

FIXTURES = Path(__file__).parent / "fixtures"


def _read(name: str) -> Spectrum:
    return SPAReader().read(FIXTURES / name)


def _found(spectrum: Spectrum) -> set[str]:
    return {r.group_id for r in score_functional_groups(spectrum).results if r.score >= 55.0}


def test_shipped_model_loads_and_covers_the_common_groups() -> None:
    model = fg_model.load_model()
    assert model is not None
    assert len(model.thresholds) >= 45
    for group in ("ester", "alcohol", "aromatic_ring", "amide", "nitrile", "carboxylic_acid"):
        assert model.is_modelled(group)
    assert model.info["features"]["n"] == N_FEATURES


def test_features_are_unit_and_scale_independent() -> None:
    wn = np.linspace(4000.0, 600.0, 3401)
    absorbance = 0.8 * np.exp(-((wn - 1715.0) ** 2) / 200.0) + 0.3 * np.exp(
        -((wn - 2950.0) ** 2) / 400.0
    )
    a = spectrum_features(Spectrum(wavenumbers=wn, intensities=absorbance))
    t = spectrum_features(
        Spectrum(
            wavenumbers=wn,
            intensities=100.0 * 10 ** (-absorbance),
            y_unit=SpectralUnit.TRANSMITTANCE,
        )
    )
    assert a is not None
    assert t is not None
    assert a.shape == (N_FEATURES,)
    assert np.max(np.abs(a - t)) < 0.08
    assert spectrum_features(Spectrum(wavenumbers=wn[:10], intensities=absorbance[:10])) is None


@pytest.mark.parametrize(
    ("fixture", "expected", "not_expected"),
    [
        ("atrcor.spa", {"alcohol", "primary_alcohol"}, {"aliphatic_ether", "isothiocyanate"}),
        (
            "absorb.spa",
            {"aromatic_ring", "monosubstituted_benzene"},
            {"amine_salt", "sulfoxide", "sulfonyl_chloride", "aliphatic_ether"},
        ),
        ("advatrref.SPA", {"para_disubstituted_benzene"}, {"acid_halide", "organophosphate"}),
        ("EVA Out Of Specifications 32%.SPA", {"ester"}, {"aryl_ether", "organophosphate"}),
        ("Cyclohexane Contaminated - Low.SPA", {"aliphatic_hydrocarbon"}, {"epoxide"}),
    ],
)
def test_known_samples_get_their_groups_and_no_absurd_ones(
    fixture: str, expected: set[str], not_expected: set[str]
) -> None:
    found = _found(_read(fixture))
    assert expected <= found, expected - found
    assert not (not_expected & found), not_expected & found


def test_groups_outside_the_model_never_claim_to_be_found() -> None:
    results = score_functional_groups(_read("0min-1-97C.SPA")).results
    rules_only = [r for r in results if r.evidence_source == "rules"]
    assert rules_only
    for result in rules_only:
        assert result.score <= 100.0 * RULE_ONLY_FACTOR
        assert result.rule_score is not None
    modelled = [r for r in results if r.evidence_source == "model"]
    assert all(r.model_probability is not None for r in modelled)


def test_scoring_without_model_keeps_the_band_windows(monkeypatch) -> None:
    monkeypatch.setattr(fg_model, "load_model", lambda path=None: None)
    results = score_functional_groups(_read("atrcor.spa")).results
    assert results
    assert all(r.evidence_source == "rules" for r in results)


def test_missing_model_file_disables_the_model(tmp_path) -> None:
    assert fg_model.load_model(tmp_path / "absent.npz") is None


def test_structure_check_confirms_the_right_structure() -> None:
    spectrum = _read("atrcor.spa")  # methanol
    analysis = score_functional_groups(spectrum)
    check = check_structure("CO", analysis, spectrum)
    assert check is not None
    assert check.consistent
    assert {g.group_id for g in check.found} >= {"primary_alcohol"}


def test_structure_check_flags_a_wrong_structure() -> None:
    spectrum = _read("absorb.spa")  # polystyrene
    analysis = score_functional_groups(spectrum)
    check = check_structure("CC(C)OC(C)=O", analysis, spectrum)  # an ester instead
    assert check is not None
    assert not check.consistent
    assert "ester" in {g.group_id for g in check.groups if g.status == NOT_SEEN}
    assert any(3000 <= band.wavenumber <= 3110 for band in check.unexplained)


def test_structure_check_knows_carbonates() -> None:
    spectrum = _read("advatrref.SPA")  # polycarbonate film
    analysis = score_functional_groups(spectrum)
    check = check_structure("COC(=O)Oc1ccc(C(C)(C)c2ccc(OC(=O)OC)cc2)cc1", analysis, spectrum)
    assert check is not None
    assert not any(1700 <= band.wavenumber <= 1800 for band in check.unexplained)
    assert "para_disubstituted_benzene" in {g.group_id for g in check.groups if g.status == FOUND}


def test_structure_check_needs_a_structure() -> None:
    spectrum = _read("atrcor.spa")
    analysis = score_functional_groups(spectrum)
    assert check_structure("", analysis, spectrum) is None
    assert check_structure("not smiles", analysis, spectrum) is None
