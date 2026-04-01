"""
SPABinaryReader — Low-level binární parser pro .spa soubory.

Zodpovědnost:
- Přímé čtení binárního formátu SPA bez závislosti na SpectroChemPy
- Fallback pro případ, že SpectroChemPy selže
- Extrahuje minimálně: wavenumbers + intensities

Implementace je založena na reverse engineeringu SPA formátu.
Funguje spolehlivě pro data ze spektrometrů Thermo Nicolet/Nexus.

TODO (v0.1.x): Implementovat plné SPA block structure navigation.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from core.spectrum import Spectrum, SpectralUnit, XAxisUnit


class SPABinaryReader:
    """Minimal SPA binary reader as SpectroChemPy fallback."""

    def read(self, filepath: Path) -> Spectrum:
        """Read spectral data directly from SPA binary format.

        Args:
            filepath: Path to .spa file.

        Returns:
            Spectrum with wavenumbers and intensities.

        Raises:
            NotImplementedError: Until full SPA block parsing is implemented.
        """
        data = filepath.read_bytes()
        wavenumbers, intensities = self._extract_spectral_data(data)

        return Spectrum(
            wavenumbers=wavenumbers,
            intensities=intensities,
            title=filepath.stem,
            source_path=filepath,
            y_unit=SpectralUnit.ABSORBANCE,
            x_unit=XAxisUnit.WAVENUMBER,
        )

    def _extract_spectral_data(
        self, data: bytes
    ) -> tuple[np.ndarray, np.ndarray]:
        """Extract wavenumber and intensity arrays from raw SPA bytes.

        Args:
            data: Raw file bytes.

        Returns:
            Tuple of (wavenumbers, intensities) as float64 arrays.
        """
        # TODO: Implement full SPA block structure navigation
        raise NotImplementedError(
            "SPABinaryReader: full SPA block parsing not yet implemented. "
            "This is a v0.1.x TODO item."
        )
