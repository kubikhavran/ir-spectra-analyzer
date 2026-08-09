"""
Normalization — Normalizace IR spektra.

Zodpovědnost:
- Min-max normalizace (0 až 1)
- Area normalizace (integral = 1)
- Peak normalizace (maximum = 1)
"""

from __future__ import annotations

import numpy as np

# NumPy removed ``np.trapz`` in 2.0 and the project's floor still allows 1.26,
# so integrate through SciPy, which spells it the same way on every supported
# version.
from scipy.integrate import trapezoid


def minmax_normalize(intensities: np.ndarray) -> np.ndarray:
    """Normalize intensities to [0, 1] range."""
    min_val, max_val = intensities.min(), intensities.max()
    if max_val == min_val:
        return np.zeros_like(intensities)
    return (intensities - min_val) / (max_val - min_val)


def peak_normalize(intensities: np.ndarray) -> np.ndarray:
    """Normalize so that the maximum intensity = 1."""
    max_val = intensities.max()
    if max_val == 0:
        return intensities.copy()
    return intensities / max_val


def area_normalize(wavenumbers: np.ndarray, intensities: np.ndarray) -> np.ndarray:
    """Normalize so that spectral area (trapezoid integral) = 1."""
    area = float(trapezoid(intensities, wavenumbers))
    if area == 0:
        return intensities.copy()
    return intensities / abs(area)
