"""Tests for processing.normalization."""

import numpy as np
from scipy.integrate import trapezoid

from processing.normalization import area_normalize, minmax_normalize, peak_normalize


def test_minmax_normalize_spans_zero_to_one():
    result = minmax_normalize(np.array([2.0, 4.0, 6.0]))

    assert np.isclose(result.min(), 0.0)
    assert np.isclose(result.max(), 1.0)


def test_minmax_normalize_flat_spectrum_stays_finite():
    result = minmax_normalize(np.full(5, 3.0))

    assert np.allclose(result, 0.0)


def test_peak_normalize_puts_the_maximum_at_one():
    result = peak_normalize(np.array([1.0, 5.0, 2.5]))

    assert np.isclose(result.max(), 1.0)
    assert np.isclose(result[1], 1.0)


def test_peak_normalize_all_zero_spectrum_is_returned_unchanged():
    result = peak_normalize(np.zeros(4))

    assert np.allclose(result, 0.0)


def test_area_normalize_gives_unit_area():
    """Guards the integration call itself — NumPy 2.0 removed ``np.trapz``."""
    wavenumbers = np.linspace(400.0, 4000.0, 601)
    intensities = np.exp(-(((wavenumbers - 1700.0) / 60.0) ** 2))

    result = area_normalize(wavenumbers, intensities)

    assert np.isclose(abs(trapezoid(result, wavenumbers)), 1.0)


def test_area_normalize_zero_area_spectrum_is_returned_unchanged():
    wavenumbers = np.linspace(400.0, 4000.0, 100)

    result = area_normalize(wavenumbers, np.zeros(100))

    assert np.allclose(result, 0.0)
