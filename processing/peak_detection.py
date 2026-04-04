"""
PeakDetection — Automatická detekce peaků.

Zodpovědnost:
- Automatická detekce absorbančních maxim v IR spektru
- Konfigurovatelné parametry (prominance, šířka, výška)
- Wrapper nad scipy.signal.find_peaks

Architektonické pravidlo:
  Čistě funkcionální — vstup: numpy arrays, výstup: seznam Peak objektů.
  Žádný stav, žádné side-effects. Snadno testovatelné.
"""

from __future__ import annotations

import numpy as np
from scipy import signal

from core.peak import Peak


def detect_peaks(
    wavenumbers: np.ndarray,
    intensities: np.ndarray,
    prominence: float = 0.01,
    min_width: float = 2.0,
    height: float | None = None,
    invert: bool = False,
) -> list[Peak]:
    """Detect peaks in IR spectrum using scipy.signal.find_peaks.

    Args:
        wavenumbers: X-axis data (cm⁻¹).
        intensities: Y-axis data (absorbance or transmittance).
        prominence: Minimum peak prominence relative to surrounding baseline.
        min_width: Minimum peak width in data points.
        height: Minimum peak height. If None, no height constraint.
        invert: If True, detect minima instead of maxima (use for %Transmittance
            data where absorption bands are dips, not peaks).

    Returns:
        List of detected Peak objects sorted by position descending (IR convention).
        Peak intensities always reflect the original (non-inverted) signal values.
    """
    kwargs: dict = {"prominence": prominence, "width": min_width}
    if height is not None:
        kwargs["height"] = height

    search_signal = -intensities if invert else intensities
    peak_indices, _ = signal.find_peaks(search_signal, **kwargs)

    peaks = [
        Peak(position=float(wavenumbers[idx]), intensity=float(intensities[idx]))
        for idx in peak_indices
    ]

    return sorted(peaks, key=lambda p: p.position, reverse=True)
