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


# ── Display-unit conversion ──────────────────────────────────────────────────

# Only absorbance and %transmittance are related by a defined transform. %R,
# single beam and baseline-corrected data have no absorbance counterpart worth
# inventing: reflectance needs the Kubelka-Munk model and a single beam is not
# a ratio at all, so offering to "convert" them would be a lie in a menu.


def _units() -> tuple:
    """SpectralUnit members used here, imported lazily to keep this module light."""
    from core.spectrum import SpectralUnit  # noqa: PLC0415

    return (SpectralUnit.ABSORBANCE, SpectralUnit.TRANSMITTANCE)


def convertible_units(source: object) -> tuple:
    """The units ``source`` data can be shown as, itself included.

    Empty when the unit has no defined counterpart, which is how a caller
    knows not to offer the choice at all.
    """
    absorbance, transmittance = _units()
    if source in (absorbance, transmittance):
        return (absorbance, transmittance)
    return ()


def convert_intensities(
    intensities: np.ndarray, source: object, target: object
) -> np.ndarray | None:
    """Convert intensities between absorbance and %transmittance.

    Returns the input unchanged when source and target match, and None when
    the pair has no defined transform — the caller must not guess.

    NaN survives the round trip: a band OMNIC blanked out is missing data in
    either unit, and filling it in would invent a measurement.
    """
    absorbance, transmittance = _units()
    if source == target:
        return np.asarray(intensities, dtype=float)
    if source == absorbance and target == transmittance:
        return absorbance_to_transmittance(np.asarray(intensities, dtype=float))
    if source == transmittance and target == absorbance:
        return transmittance_to_absorbance(np.asarray(intensities, dtype=float))
    return None
