"""Tests for automatic peak detection."""

from __future__ import annotations

import numpy as np


def test_detect_peaks_single_gaussian() -> None:
    """detect_peaks should find a single obvious Gaussian peak."""
    from processing.peak_detection import detect_peaks

    wavenumbers = np.linspace(400.0, 4000.0, 3601)
    intensities = np.exp(-((wavenumbers - 1700.0) ** 2) / (2 * 20.0**2))

    peaks = detect_peaks(wavenumbers, intensities, prominence=0.1)

    assert len(peaks) == 1
    assert abs(peaks[0].position - 1700.0) < 5.0


def test_detect_peaks_empty_returns_no_peaks() -> None:
    """detect_peaks should return empty list for flat spectrum."""
    from processing.peak_detection import detect_peaks

    wavenumbers = np.linspace(400.0, 4000.0, 100)
    intensities = np.zeros(100)

    peaks = detect_peaks(wavenumbers, intensities, prominence=0.01)
    assert peaks == []


def test_detect_peaks_sorted_descending() -> None:
    """detect_peaks should return peaks sorted by position descending."""
    from processing.peak_detection import detect_peaks

    wavenumbers = np.linspace(400.0, 4000.0, 3601)
    intensities = np.exp(-((wavenumbers - 1000.0) ** 2) / (2 * 10.0**2)) + np.exp(
        -((wavenumbers - 3000.0) ** 2) / (2 * 10.0**2)
    )

    peaks = detect_peaks(wavenumbers, intensities, prominence=0.1)

    assert len(peaks) == 2
    assert peaks[0].position > peaks[1].position


def test_detect_peaks_transmittance_invert() -> None:
    """detect_peaks with invert=True should find absorption dips in %T data."""
    from processing.peak_detection import detect_peaks

    # Simulate %T spectrum: baseline ~100%, absorption dip at 1700 cm-1
    wavenumbers = np.linspace(400.0, 4000.0, 3601)
    baseline = np.ones_like(wavenumbers) * 100.0
    dip = 30.0 * np.exp(-((wavenumbers - 1700.0) ** 2) / (2 * 20.0**2))
    transmittance = baseline - dip  # dip goes down to ~70%T at 1700

    # Without invert: should NOT find the absorption band (it's a dip, not a max)
    peaks_no_invert = detect_peaks(wavenumbers, transmittance, prominence=5.0)
    assert not any(abs(p.position - 1700.0) < 10.0 for p in peaks_no_invert)

    # With invert: should find the absorption band at ~1700 cm-1
    peaks_inverted = detect_peaks(wavenumbers, transmittance, prominence=5.0, invert=True)
    assert len(peaks_inverted) == 1
    assert abs(peaks_inverted[0].position - 1700.0) < 5.0
    # Reported intensity is the original %T value (not inverted)
    assert peaks_inverted[0].intensity < 80.0  # dip is below 80%T


def test_detect_peaks_invert_intensity_is_original() -> None:
    """Peak intensity should reflect the original signal even when invert=True."""
    from processing.peak_detection import detect_peaks

    wavenumbers = np.linspace(400.0, 4000.0, 3601)
    # Gaussian dip at 1700 cm-1 going down to 60%T
    dip = 40.0 * np.exp(-((wavenumbers - 1700.0) ** 2) / (2 * 20.0**2))
    transmittance = 100.0 - dip

    peaks = detect_peaks(wavenumbers, transmittance, prominence=5.0, invert=True)
    assert len(peaks) == 1
    # Reported intensity is the original %T value at the dip minimum (~60%T)
    assert peaks[0].intensity == pytest.approx(60.0, abs=2.0)


import pytest  # noqa: E402
