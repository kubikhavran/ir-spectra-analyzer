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
