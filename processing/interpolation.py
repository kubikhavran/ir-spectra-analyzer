"""
Interpolation — Interpolace spekter pro porovnávání.

Zodpovědnost:
- Resampling spektra na zadanou osu wavenumberů
- Lineární a kubická interpolace
- Příprava spekter pro databázové matching (stejná osa)
"""

from __future__ import annotations

import numpy as np
from scipy.interpolate import interp1d


def resample(
    wavenumbers: np.ndarray,
    intensities: np.ndarray,
    new_wavenumbers: np.ndarray,
    kind: str = "linear",
) -> np.ndarray:
    """Resample spectrum to a new wavenumber axis.

    Args:
        wavenumbers: Original X-axis.
        intensities: Original intensities.
        new_wavenumbers: Target wavenumber axis.
        kind: Interpolation kind ("linear", "cubic").

    Returns:
        Intensities resampled to new_wavenumbers.
    """
    f = interp1d(wavenumbers, intensities, kind=kind, bounds_error=False, fill_value=0.0)
    return f(new_wavenumbers)
