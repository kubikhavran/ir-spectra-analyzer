"""Tests for band-level comparison of two spectra."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from core.spectrum import SpectralUnit, Spectrum

FIXTURES = Path(__file__).resolve().parent / "fixtures/reference library_1"


def _spectrum(band_centers, *, depth=40.0, width=8.0) -> Spectrum:
    """Transmittance spectrum with sharp absorption dips at the given positions."""
    wn = np.arange(400.0, 4001.0, 1.0)
    y = np.full_like(wn, 98.0)
    for center in band_centers:
        y = y - depth * np.exp(-0.5 * ((wn - center) / (width / 2.355)) ** 2)
    return Spectrum(
        wavenumbers=wn, intensities=y, y_unit=SpectralUnit.TRANSMITTANCE, title="synthetic"
    )


def test_shared_bands_within_tolerance_are_not_reported():
    from processing.band_difference import compare_bands

    query = _spectrum([700.0, 1100.0, 1600.0])
    reference = _spectrum([704.0, 1100.0, 1597.0])  # all within 8 cm-1

    comparison = compare_bands(query, reference)
    assert comparison.only_in_query == ()
    assert comparison.only_in_reference == ()
    assert comparison.shared_count == 3


def test_extra_and_missing_bands_are_reported_strongest_first():
    from processing.band_difference import compare_bands

    query = _spectrum([700.0, 1100.0])
    reference = _spectrum([700.0, 1400.0])

    comparison = compare_bands(query, reference)
    assert [round(band.position) for band in comparison.only_in_query] == [1100]
    assert [round(band.position) for band in comparison.only_in_reference] == [1400]
    assert comparison.shared_count == 1
    assert "only in sample: 1100" in comparison.summary()
    assert "only in reference: 1400" in comparison.summary()


def test_summary_is_empty_when_a_spectrum_has_no_detectable_bands():
    from processing.band_difference import compare_bands

    flat = _spectrum([], depth=0.0)
    assert compare_bands(flat, _spectrum([700.0])).summary() == ""


@pytest.mark.skipif(
    not (FIXTURES / "PAR1706-HA.SPA").exists(), reason="lab fixture pair not present"
)
@pytest.mark.lab_fixtures
def test_real_substituent_pair_reports_the_azide_and_methoxy_bands():
    """The azide/methoxy swap must be spelled out for the analyst.

    PAR1706-HA carries N3 where PAR1507-MK carries OMe, which is why the two
    spectra score far apart overall despite being the same skeleton.
    """
    from file_io.spa_reader import SPAReader
    from processing.band_difference import compare_bands

    query = SPAReader().read(FIXTURES / "PAR1706-HA.SPA")
    reference = SPAReader().read(FIXTURES / "PAR1507-MK.SPA")

    comparison = compare_bands(query, reference)
    # The azide is the strongest band the sample has and the reference lacks.
    assert abs(comparison.only_in_query[0].position - 2114.0) < 10.0
    # The methoxy C-H stretch is among the bands only the reference shows.
    assert any(abs(band.position - 2830.0) < 10.0 for band in comparison.only_in_reference)
    assert comparison.shared_count >= 15
