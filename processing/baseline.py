"""
Baseline — Korekce baseline IR spektra.

Zodpovědnost:
- Polynomial baseline fitting
- Rubber band correction
- Asymmetric Least Squares (ALS) baseline

Architektonické pravidlo:
  Čistě funkcionální. Vstup: numpy arrays. Výstup: numpy array (korigované intenzity).
"""
from __future__ import annotations

import numpy as np


def polynomial_baseline(
    wavenumbers: np.ndarray,
    intensities: np.ndarray,
    degree: int = 3,
    regions: list[tuple[float, float]] | None = None,
) -> np.ndarray:
    """Fit polynomial baseline and subtract it from intensities.

    Args:
        wavenumbers: X-axis data.
        intensities: Y-axis data.
        degree: Polynomial degree for baseline fit.
        regions: Optional list of (min_wn, max_wn) baseline anchor regions.
                 If None, uses full spectral range.

    Returns:
        Baseline-corrected intensities.
    """
    if regions is None:
        fit_wn = wavenumbers
        fit_int = intensities
    else:
        mask = np.zeros(len(wavenumbers), dtype=bool)
        for r_min, r_max in regions:
            mask |= (wavenumbers >= r_min) & (wavenumbers <= r_max)
        fit_wn = wavenumbers[mask]
        fit_int = intensities[mask]

    coeffs = np.polyfit(fit_wn, fit_int, degree)
    baseline = np.polyval(coeffs, wavenumbers)
    return intensities - baseline
