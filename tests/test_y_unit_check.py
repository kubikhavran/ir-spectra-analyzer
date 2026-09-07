"""Tests for the Y-unit guard: a mislabeled file must never render as the wrong kind of spectrum."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from core.spectrum import SpectralUnit, Spectrum
from processing.y_unit_check import check_y_unit, infer_y_unit, is_dip_shaped

_FIXTURES = Path(__file__).parent / "fixtures"


def _percent_curve(*, blanked: bool = False) -> np.ndarray:
    """A %T curve: baseline near 100, absorption bands dipping down."""
    wn = np.linspace(400.0, 4000.0, 1200)
    curve = np.full_like(wn, 99.0)
    for centre, depth in ((1050.0, 30.0), (1700.0, 45.0), (2925.0, 20.0)):
        curve -= depth * np.exp(-0.5 * ((wn - centre) / 15.0) ** 2)
    if blanked:
        # OMNIC's Blank tool: a band cut out of the curve and written as NaN.
        curve[(wn > 2275.0) & (wn < 2422.0)] = np.nan
    return curve


def _absorbance_curve() -> np.ndarray:
    """An absorbance curve: baseline near 0, bands pointing up."""
    wn = np.linspace(400.0, 4000.0, 1200)
    curve = np.full_like(wn, 0.01)
    for centre, height in ((1050.0, 0.4), (1700.0, 0.9), (2925.0, 0.3)):
        curve += height * np.exp(-0.5 * ((wn - centre) / 15.0) ** 2)
    return curve


# ── Reading the scale off the numbers ────────────────────────────────────────


def test_percent_curve_is_recognised() -> None:
    assert infer_y_unit(_percent_curve()) == SpectralUnit.TRANSMITTANCE


def test_absorbance_curve_is_recognised() -> None:
    assert infer_y_unit(_absorbance_curve()) == SpectralUnit.ABSORBANCE


def test_blanked_regions_do_not_defeat_the_guard() -> None:
    """A NaN gap is a hole in the data, not a value — the verdict must not change.

    This is the exact shape of JUS251-SE.SPA: plain reductions return NaN, every
    comparison against NaN is False, and the whole check silently gives up.
    """
    assert infer_y_unit(_percent_curve(blanked=True)) == SpectralUnit.TRANSMITTANCE
    assert is_dip_shaped(_percent_curve(blanked=True), SpectralUnit.ABSORBANCE)


def test_all_nan_is_undecidable() -> None:
    assert infer_y_unit(np.full(50, np.nan)) is None
    assert not is_dip_shaped(np.full(50, np.nan), SpectralUnit.ABSORBANCE)


# ── Comparing the numbers with the header ────────────────────────────────────


def test_matching_header_raises_nothing() -> None:
    check = check_y_unit(_percent_curve(), SpectralUnit.TRANSMITTANCE)
    assert check.agrees
    assert check.warning == ""
    assert check.trusted == SpectralUnit.TRANSMITTANCE


def test_percent_data_under_an_absorbance_header_is_reported() -> None:
    check = check_y_unit(_percent_curve(), SpectralUnit.ABSORBANCE)
    assert not check.agrees
    assert check.trusted == SpectralUnit.TRANSMITTANCE
    assert "Absorbance" in check.warning
    assert "Transmittance" in check.warning


def test_reflectance_is_not_corrected_into_transmittance() -> None:
    """%R shares the percent scale with %T, so the numbers cannot tell them apart."""
    check = check_y_unit(_percent_curve(), SpectralUnit.REFLECTANCE)
    assert check.agrees
    assert check.trusted == SpectralUnit.REFLECTANCE


def test_absorbance_data_under_a_transmittance_header_is_reported() -> None:
    check = check_y_unit(_absorbance_curve(), SpectralUnit.TRANSMITTANCE)
    assert not check.agrees
    assert check.trusted == SpectralUnit.ABSORBANCE


def test_spectrum_exposes_the_check() -> None:
    spectrum = Spectrum(
        wavenumbers=np.linspace(400.0, 4000.0, 1200),
        intensities=_percent_curve(),
        y_unit=SpectralUnit.ABSORBANCE,
    )
    assert spectrum.y_unit_check.warning
    assert spectrum.is_dip_spectrum
    assert spectrum.display_y_unit == SpectralUnit.TRANSMITTANCE


# ── The file that started it ─────────────────────────────────────────────────


@pytest.mark.skipif(
    not (_FIXTURES / "JUS251-SE.SPA").exists(), reason="JUS251-SE.SPA fixture not present"
)
def test_jus251_reads_as_transmittance() -> None:
    """OMNIC shows it as %T; so must we.

    Its history carries no ``Final format:`` line at all — only a chain of
    ``Converted to ... y-axis units`` entries ending in %T — and a NaN-blanked
    band that used to defeat the fallback heuristic as well.
    """
    from file_io.spa_binary import SPABinaryReader

    spectrum = SPABinaryReader().read(_FIXTURES / "JUS251-SE.SPA")
    assert spectrum.y_unit == SpectralUnit.TRANSMITTANCE
    assert spectrum.is_dip_spectrum
    assert spectrum.display_y_unit == SpectralUnit.TRANSMITTANCE
    assert spectrum.y_unit_check.agrees
    assert np.any(np.isnan(spectrum.intensities))  # the blanked band is still there
