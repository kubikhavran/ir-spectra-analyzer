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


# Detection sensitivity, as offered in the toolbar: 1 marks only the dominant
# bands, 10 also the faintest shoulders that still form a local extremum.
SENSITIVITY_MIN = 1
SENSITIVITY_MAX = 10
DEFAULT_SENSITIVITY = 5
# Prominence threshold as a fraction of the spectrum's own intensity span, at
# the two ends of the scale; the levels in between are spaced geometrically.
_LEAST_SENSITIVE_FRACTION = 0.10
_MOST_SENSITIVE_FRACTION = 0.002


def clamp_sensitivity(value: object) -> int:
    """Coerce a stored/typed sensitivity to a valid level, default when unusable."""
    try:
        level = int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return DEFAULT_SENSITIVITY
    return int(max(SENSITIVITY_MIN, min(SENSITIVITY_MAX, level)))


def prominence_fraction(sensitivity: int = DEFAULT_SENSITIVITY) -> float:
    """Prominence threshold for a sensitivity level, as a fraction of the span."""
    level = clamp_sensitivity(sensitivity)
    position = (level - SENSITIVITY_MIN) / (SENSITIVITY_MAX - SENSITIVITY_MIN)
    ratio = _MOST_SENSITIVE_FRACTION / _LEAST_SENSITIVE_FRACTION
    return float(_LEAST_SENSITIVE_FRACTION * ratio**position)


def default_prominence(spectrum, sensitivity: int = DEFAULT_SENSITIVITY) -> float:
    """Return the prominence threshold used for automatic detection on a spectrum.

    The threshold is relative to the spectrum's own intensity span. A fixed
    value (1 %T, 0.05 A) suited strong spectra only: on a weak one — bands a
    few %T deep, or an absorbance difference spectrum peaking at 0.1 — it sat
    above most of the bands and detection returned a handful of peaks.
    Measured against the peak tables analysts stored in the lab files, the
    fixed threshold recovered about half of their peaks.
    """
    values = np.asarray(spectrum.intensities, dtype=float)
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return 1.0
    span = float(finite.max() - finite.min())
    if span <= 0.0:
        return 1.0
    return span * prominence_fraction(sensitivity)
