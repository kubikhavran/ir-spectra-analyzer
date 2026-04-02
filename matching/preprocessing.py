"""
MatchingPreprocessing — Preprocessing pro spectral matching.

Zodpovědnost:
- Normalizace a resampling spektra před porovnáváním
- Zajišťuje, že všechna porovnávaná spektra mají stejnou osu
"""

from __future__ import annotations

import numpy as np

from processing.interpolation import resample
from processing.normalization import peak_normalize


def prepare_for_matching(
    wavenumbers: np.ndarray,
    intensities: np.ndarray,
    target_axis: np.ndarray,
) -> np.ndarray:
    """Preprocess spectrum for database matching.

    Resamples to target axis and normalizes to peak = 1.

    Args:
        wavenumbers: Original X-axis.
        intensities: Original intensities.
        target_axis: Common wavenumber axis for matching.

    Returns:
        Normalized, resampled intensity array.
    """
    resampled = resample(wavenumbers, intensities, target_axis)
    return peak_normalize(resampled)
