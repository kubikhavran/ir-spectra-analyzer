"""
Smoothing — Vyhlazování IR spektra.

Zodpovědnost:
- Savitzky-Golay filtr (doporučeno pro IR)
- Moving average (jednodušší alternativa)

Architektonické pravidlo:
  Čistě funkcionální. Vstup: numpy array. Výstup: numpy array.
"""
from __future__ import annotations

import numpy as np
from scipy.signal import savgol_filter


def savitzky_golay(
    intensities: np.ndarray,
    window_length: int = 11,
    polyorder: int = 3,
) -> np.ndarray:
    """Apply Savitzky-Golay smoothing filter.

    Args:
        intensities: Raw intensity data.
        window_length: Filter window length (must be odd).
        polyorder: Polynomial order for fitting.

    Returns:
        Smoothed intensity array.
    """
    if window_length % 2 == 0:
        window_length += 1
    return savgol_filter(intensities, window_length, polyorder)


def moving_average(intensities: np.ndarray, window: int = 5) -> np.ndarray:
    """Apply moving average smoothing.

    Args:
        intensities: Raw intensity data.
        window: Number of points in the averaging window.

    Returns:
        Smoothed intensity array (same length, edges padded with convolution).
    """
    kernel = np.ones(window) / window
    return np.convolve(intensities, kernel, mode="same")
