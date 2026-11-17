"""Turn any IR spectrum into one fixed feature vector for the group model.

The learned functional-group model (``processing.fg_model``) needs every
spectrum on the same footing whatever the instrument, unit or range:

1. sorted to ascending wavenumber, blanked points bridged;
2. converted to an absorbance-like scale with its baseline removed —
   transmittance is divided by its upper convex hull and turned into
   ``-log10(T)``; absorbance has its lower convex hull subtracted;
3. resampled onto a common grid (650-3900 cm⁻¹), normalised to the strongest
   band, and max-pooled into 20 cm⁻¹ bins;
4. square-rooted, so weak but diagnostic bands (a nitrile, an aldehyde C-H)
   are not drowned by the strongest one.

Only numpy is used, so the model runs inside the application with no extra
dependency.
"""

from __future__ import annotations

import numpy as np

from core.spectrum import Spectrum
from processing.baseline import _convex_hull_baseline

GRID_MIN = 650.0
GRID_MAX = 3900.0
GRID_STEP = 4.0
BIN_WIDTH = 20.0

_GRID = np.arange(GRID_MIN, GRID_MAX + GRID_STEP / 2, GRID_STEP)
_PER_BIN = int(round(BIN_WIDTH / GRID_STEP))
_N_BINS = len(_GRID) // _PER_BIN
#: Centre of every feature bin, in cm⁻¹.
BIN_CENTERS = _GRID[: _N_BINS * _PER_BIN].reshape(_N_BINS, _PER_BIN).mean(axis=1)
N_FEATURES = _N_BINS


def absorbance_profile(spectrum: Spectrum) -> tuple[np.ndarray, np.ndarray] | None:
    """Baseline-free absorbance-like curve on the common grid, scaled to 1."""
    wn = np.asarray(spectrum.wavenumbers, dtype=float)
    y = np.asarray(spectrum.intensities, dtype=float)
    finite = np.isfinite(wn) & np.isfinite(y)
    if finite.sum() < 20:
        return None
    wn, y = wn[finite], y[finite]
    order = np.argsort(wn)
    wn, y = wn[order], y[order]
    wn, unique = np.unique(wn, return_index=True)
    y = y[unique]
    if wn[-1] - wn[0] < 500.0:
        return None

    if spectrum.is_dip_spectrum:
        hull = _convex_hull_baseline(wn, y, upper=True)
        hull = np.where(np.abs(hull) > 1e-12, hull, np.nan)
        transmittance = np.clip(y / hull, 1e-3, 1.0)
        absorbance = -np.log10(np.nan_to_num(transmittance, nan=1.0))
    else:
        absorbance = y - _convex_hull_baseline(wn, y, upper=False)
    absorbance = np.clip(absorbance, 0.0, None)

    inside = (_GRID >= wn[0]) & (_GRID <= wn[-1])
    profile = np.zeros_like(_GRID)
    profile[inside] = np.interp(_GRID[inside], wn, absorbance)
    peak = float(profile.max())
    if peak <= 1e-9:
        return None
    return _GRID, profile / peak


def spectrum_features(spectrum: Spectrum) -> np.ndarray | None:
    """Feature vector of ``N_FEATURES`` values in [0, 1], or ``None``."""
    prepared = absorbance_profile(spectrum)
    if prepared is None:
        return None
    _grid, profile = prepared
    pooled = profile[: _N_BINS * _PER_BIN].reshape(_N_BINS, _PER_BIN).max(axis=1)
    return np.sqrt(pooled)
