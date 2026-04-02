"""
UnitConversion — Konverze spektrálních jednotek.

Zodpovědnost:
- Absorbance ↔ Transmittance konverze
- Wavenumber ↔ Wavelength (nm, μm) konverze
"""

from __future__ import annotations

import numpy as np


def absorbance_to_transmittance(absorbance: np.ndarray) -> np.ndarray:
    """Convert absorbance to transmittance (%).

    T = 10^(-A) * 100
    """
    return 10.0 ** (-absorbance) * 100.0


def transmittance_to_absorbance(transmittance: np.ndarray) -> np.ndarray:
    """Convert transmittance (%) to absorbance.

    A = -log10(T/100)
    """
    t_fraction = np.clip(transmittance / 100.0, 1e-10, None)
    return -np.log10(t_fraction)


def wavenumber_to_wavelength_nm(wavenumber: np.ndarray) -> np.ndarray:
    """Convert wavenumber (cm⁻¹) to wavelength (nm)."""
    return 1e7 / wavenumber


def wavelength_nm_to_wavenumber(wavelength_nm: np.ndarray) -> np.ndarray:
    """Convert wavelength (nm) to wavenumber (cm⁻¹)."""
    return 1e7 / wavelength_nm
