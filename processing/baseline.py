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


def rubber_band_baseline(
    wavenumbers: np.ndarray,
    intensities: np.ndarray,
) -> np.ndarray:
    """Subtract a rubber-band (lower convex hull) baseline from intensities."""
    wn = np.asarray(wavenumbers, dtype=float)
    y = np.asarray(intensities, dtype=float)

    if wn.shape != y.shape:
        raise ValueError("wavenumbers and intensities must have the same shape")
    if wn.size == 0:
        raise ValueError("Spectrum must contain at least one data point")
    if wn.size == 1:
        return np.array([0.0], dtype=float)

    # Work on a sorted copy to support ascending or descending wavenumbers.
    sort_idx = np.argsort(wn)
    wn_sorted = wn[sort_idx]
    y_sorted = y[sort_idx]

    # Build lower convex hull using monotonic chain.
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    hull: list[int] = []
    for i in range(len(wn_sorted)):
        while len(hull) >= 2:
            o = (wn_sorted[hull[-2]], y_sorted[hull[-2]])
            a = (wn_sorted[hull[-1]], y_sorted[hull[-1]])
            b = (wn_sorted[i], y_sorted[i])
            if cross(o, a, b) <= 0:
                hull.pop()
            else:
                break
        hull.append(i)

    hull_x = wn_sorted[hull]
    hull_y = y_sorted[hull]

    # Linear interpolation over hull points gives a baseline at every x.
    baseline_sorted = np.interp(wn_sorted, hull_x, hull_y)
    baseline = np.empty_like(y)
    baseline[sort_idx] = baseline_sorted

    corrected = y - baseline
    return corrected
