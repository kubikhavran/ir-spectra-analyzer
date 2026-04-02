"""
MathUtils — Pomocné matematické funkce.

Zodpovědnost:
- Interpolační utility
- Statistické funkce pro spektrální analýzu
- Pomocné funkce pro peak fitting
"""

from __future__ import annotations

import numpy as np


def nearest_index(array: np.ndarray, value: float) -> int:
    """Return the index of the element nearest to value.

    Args:
        array: 1D numpy array.
        value: Target value.

    Returns:
        Index of nearest element.
    """
    return int(np.argmin(np.abs(array - value)))


def fwhm_from_peak(
    wavenumbers: np.ndarray,
    intensities: np.ndarray,
    peak_index: int,
) -> float | None:
    """Estimate FWHM for a peak at given index.

    Args:
        wavenumbers: X-axis data.
        intensities: Y-axis data.
        peak_index: Index of the peak maximum.

    Returns:
        FWHM in wavenumber units, or None if estimation fails.
    """
    half_max = intensities[peak_index] / 2.0
    left_indices = np.where(intensities[:peak_index] < half_max)[0]
    right_indices = np.where(intensities[peak_index:] < half_max)[0]

    if len(left_indices) == 0 or len(right_indices) == 0:
        return None

    left_wn = float(wavenumbers[left_indices[-1]])
    right_wn = float(wavenumbers[peak_index + right_indices[0]])
    return abs(right_wn - left_wn)
