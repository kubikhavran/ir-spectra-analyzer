"""
MatchingPreprocessing — Preprocessing pro spectral matching.

Zodpovědnost:
- Normalizace a resampling spektra před porovnáváním
- Zajišťuje, že všechna porovnávaná spektra mají stejnou osu
"""

from __future__ import annotations

import numpy as np
from scipy.signal import savgol_filter

from processing.interpolation import resample


def prepare_for_matching(
    wavenumbers: np.ndarray,
    intensities: np.ndarray,
    target_axis: np.ndarray,
    y_unit: object | None = None,
) -> np.ndarray:
    """Preprocess spectrum for database matching.

    Resamples to a common axis, aligns spectral polarity, and emphasizes band shape.

    Args:
        wavenumbers: Original X-axis.
        intensities: Original intensities.
        target_axis: Common wavenumber axis for matching.
        y_unit: Optional spectral intensity unit used to align transmittance-like
            spectra with absorbance-like spectra before matching.

    Returns:
        Unit-normalized feature vector suitable for cosine similarity.
    """
    signal = resample(wavenumbers, intensities, target_axis).astype(np.float64, copy=False)
    signal = np.nan_to_num(signal, nan=0.0, posinf=0.0, neginf=0.0)

    sig_min = float(np.nanmin(signal))
    sig_max = float(np.nanmax(signal))
    _is_corrected_t = sig_min < -5.0 and sig_max <= 5.0  # corrected %T has negative dips

    if _is_transmittance_like(y_unit) or _is_corrected_t:
        signal = float(np.nanmax(signal)) - signal
    else:
        signal = signal - float(np.nanmin(signal))

    window = _matching_window_length(signal.size)
    if window is not None:
        baseline = savgol_filter(signal, window_length=window, polyorder=3, mode="interp")
        signal = signal - baseline

    signal = np.clip(signal, 0.0, None)
    peak = float(np.nanmax(signal))
    if peak > 0.0:
        signal = signal / peak

    derivative = np.gradient(signal)
    vector = np.concatenate((signal, derivative * 0.5))
    norm = float(np.linalg.norm(vector))
    if norm > 0.0:
        return vector / norm
    return vector


def _is_transmittance_like(y_unit: object | None) -> bool:
    """Return True for spectral units where absorptions appear as dips."""
    text = getattr(y_unit, "value", y_unit)
    if text is None:
        return False
    return str(text) in {"Transmittance", "Reflectance", "Single Beam"}


def _matching_window_length(n_points: int) -> int | None:
    """Pick a stable Savitzky-Golay window length for baseline suppression."""
    if n_points < 7:
        return None
    window = min(n_points, 151)
    if window % 2 == 0:
        window -= 1
    if window < 7:
        return None
    return window
