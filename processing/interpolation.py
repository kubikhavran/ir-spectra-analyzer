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
        Intensities resampled to new_wavenumbers. Points outside the measured
        range continue the nearest measured edge value; introducing a numeric
        zero there would create an artificial absorption edge in percent
        transmittance spectra.
    """
    min_index = int(np.argmin(wavenumbers))
    max_index = int(np.argmax(wavenumbers))
    edge_values = (intensities[min_index], intensities[max_index])
    f = interp1d(
        wavenumbers,
        intensities,
        kind=kind,
        bounds_error=False,
        fill_value=edge_values,
    )
    return f(new_wavenumbers)
