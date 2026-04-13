"""
Spectrum — Datový model IR spektra.

Zodpovědnost:
- Reprezentace spektrálních dat (wavenumbers + intensities)
- Metadata spektra (titul, datum, jednotky)
- Validace a normalizace dat při načtení
- Konverze jednotek (Absorbance ↔ Transmittance)

Toto je centrální datová třída. Všechny ostatní komponenty
pracují s instancí Spectrum.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path

import numpy as np


class SpectralUnit(Enum):
    """Spectral intensity units."""

    ABSORBANCE = "Absorbance"
    TRANSMITTANCE = "Transmittance"
    REFLECTANCE = "Reflectance"
    SINGLE_BEAM = "Single Beam"
    BASELINE_CORRECTED = "Baseline Corrected"


class XAxisUnit(Enum):
    """X-axis units."""

    WAVENUMBER = "cm⁻¹"
    WAVELENGTH_NM = "nm"
    WAVELENGTH_UM = "μm"


@dataclass
class Spectrum:
    """IR spectrum data model.

    Attributes:
        wavenumbers: X-axis data in cm⁻¹ (or other unit per x_unit).
        intensities: Y-axis data (absorbance, transmittance, etc.).
        title: Human-readable spectrum title.
        source_path: Original file path (SPA or other).
        acquired_at: Acquisition timestamp.
        y_unit: Spectral intensity unit.
        x_unit: X-axis unit.
        comments: Free-text notes from file header.
        extra_metadata: Additional key-value metadata from file.
    """

    wavenumbers: np.ndarray
    intensities: np.ndarray
    title: str = ""
    source_path: Path | None = None
    acquired_at: datetime | None = None
    y_unit: SpectralUnit = SpectralUnit.ABSORBANCE
    x_unit: XAxisUnit = XAxisUnit.WAVENUMBER
    comments: str = ""
    extra_metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate spectrum data after initialization."""
        if len(self.wavenumbers) != len(self.intensities):
            raise ValueError(
                f"wavenumbers length {len(self.wavenumbers)} != "
                f"intensities length {len(self.intensities)}"
            )
        if len(self.wavenumbers) == 0:
            raise ValueError("Spectrum must contain at least one data point.")

    @property
    def n_points(self) -> int:
        """Number of data points in the spectrum."""
        return len(self.wavenumbers)

    @property
    def x_range(self) -> tuple[float, float]:
        """(min, max) wavenumber range."""
        return float(self.wavenumbers.min()), float(self.wavenumbers.max())

    @property
    def is_dip_spectrum(self) -> bool:
        """Return True when absorption bands should be treated as downward dips.

        Primary signal comes from the declared Y unit. Some OMNIC files in the
        lab collection are mislabeled as ``Absorbance`` while their numeric
        values clearly behave like percent-transmittance curves near 100 with
        downward absorptions. For those files, use a conservative heuristic so
        label placement and peak workflows stay physically meaningful.
        """
        dip_units = {
            SpectralUnit.TRANSMITTANCE,
            SpectralUnit.REFLECTANCE,
            SpectralUnit.SINGLE_BEAM,
        }
        if self.y_unit in dip_units:
            return True
        if self.y_unit == SpectralUnit.BASELINE_CORRECTED:
            return False

        y_min = float(np.min(self.intensities))
        y_max = float(np.max(self.intensities))
        if y_max <= 5.0 or y_min < -5.0 or y_max > 120.0:
            return False

        median = float(np.median(self.intensities))
        lower_drop = median - y_min
        upper_headroom = y_max - median
        return lower_drop > (upper_headroom * 1.25)

    @property
    def display_y_unit(self) -> SpectralUnit:
        """Return the best user-facing Y unit for plotting.

        Some OMNIC fixtures declare ``Absorbance`` while clearly containing a
        percent-style transmittance curve. Preserve the original stored unit for
        metadata fidelity, but display the physically meaningful label in the
        viewer when the signal is unmistakably dip-like.
        """
        if self.y_unit == SpectralUnit.ABSORBANCE and self.is_dip_spectrum:
            return SpectralUnit.TRANSMITTANCE
        return self.y_unit
