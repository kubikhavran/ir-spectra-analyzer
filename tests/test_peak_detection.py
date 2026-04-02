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
