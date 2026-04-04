"""
Baseline — Korekce baseline IR spektra.

Zodpovědnost:
- Polynomial baseline fitting
- Rubber band correction (lower-hull for Absorbance, upper-hull for %Transmittance)
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


def _convex_hull_baseline(
    wn: np.ndarray,
    y: np.ndarray,
    *,
    upper: bool = False,
) -> np.ndarray:
    """Return interpolated convex-hull baseline values (not the corrected signal).

    Computes the lower convex hull by default (for Absorbance data), or the
    upper convex hull when ``upper=True`` (for %Transmittance data).

    The upper hull is derived by negating the signal, computing the lower hull
    on the negated data, then negating the result back.

    Args:
        wn: Wavenumber axis (may be ascending or descending).
        y: Intensity values.
        upper: If True, compute the upper hull instead of the lower hull.

    Returns:
        Interpolated baseline values at every point in ``wn``, in the same
        order as the input arrays.
    """
    wn_arr = np.asarray(wn, dtype=float)
    y_arr = np.asarray(y, dtype=float)

    sort_idx = np.argsort(wn_arr)
    wn_sorted = wn_arr[sort_idx]
    # Work on negated data when upper hull is requested.
    y_work = -y_arr[sort_idx] if upper else y_arr[sort_idx]

    # Monotone-chain lower convex hull.
    def _cross(o: int, a: int, b: int) -> float:
        return (wn_sorted[a] - wn_sorted[o]) * (y_work[b] - y_work[o]) - (y_work[a] - y_work[o]) * (
            wn_sorted[b] - wn_sorted[o]
        )

    hull: list[int] = []
    for i in range(len(wn_sorted)):
        while len(hull) >= 2 and _cross(hull[-2], hull[-1], i) <= 0:
            hull.pop()
        hull.append(i)

    hull_x = wn_sorted[hull]
    hull_y = y_work[hull]

    baseline_sorted = np.interp(wn_sorted, hull_x, hull_y)

    if upper:
        # Un-negate: lower hull of (-y) gives -(upper hull of y).
        baseline_sorted = -baseline_sorted

    baseline = np.empty_like(y_arr)
    baseline[sort_idx] = baseline_sorted
    return baseline


def rubber_band_baseline(
    wavenumbers: np.ndarray,
    intensities: np.ndarray,
    *,
    upper: bool = False,
) -> np.ndarray:
    """Subtract a rubber-band convex-hull baseline from intensities.

    The direction of the hull depends on the spectral mode:

    * ``upper=False`` (default) — **Absorbance mode**: lower convex hull is
      used as the baseline.  Returns ``intensities − lower_hull``.  Absorption
      peaks (which point upward in absorbance) remain positive; the baseline
      regions become zero.

    * ``upper=True`` — **%Transmittance mode**: upper convex hull is used as
      the baseline.  Returns ``upper_hull − intensities``.  Absorption bands
      (which are downward dips in %T) become positive; the flat transmission
      baseline regions become zero.

    Both modes produce a corrected signal where absorption features point
    upward from a near-zero baseline, regardless of the original spectral unit.

    Args:
        wavenumbers: X-axis data (cm⁻¹, ascending or descending).
        intensities: Y-axis data (absorbance or %transmittance).
        upper: Set to True for %Transmittance spectra.

    Returns:
        Baseline-corrected intensities (same shape as input).

    Raises:
        ValueError: If inputs have mismatched shapes or fewer than 1 point.
    """
    wn = np.asarray(wavenumbers, dtype=float)
    y = np.asarray(intensities, dtype=float)

    if wn.shape != y.shape:
        raise ValueError("wavenumbers and intensities must have the same shape")
    if wn.size == 0:
        raise ValueError("Spectrum must contain at least one data point")
    if wn.size == 1:
        return np.array([0.0], dtype=float)

    baseline = _convex_hull_baseline(wn, y, upper=upper)

    if upper:
        return baseline - y  # upper_hull − y  →  positive at absorption dips
    return y - baseline  # y − lower_hull  →  positive at absorption peaks
