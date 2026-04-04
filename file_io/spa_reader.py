"""
SPAReader — Parser pro Thermo Fisher OMNIC .spa soubory.

Zodpovědnost:
- Třístupňový fallback systém pro čtení SPA souborů:
  1. SpectroChemPy (nejrobustnější, nejvíce metadat)
  2. Vlastní binární parser (spa_binary.py) — lightweight fallback
  3. Výjimka s popisným chybovým hlášením
- Vrací standardizovaný objekt Spectrum

Poznámka k SPA formátu:
  SPA je proprietární binární formát Thermo Fisher bez veřejné dokumentace.
  Parsování je založeno na reverse engineeringu. U exotických modelů
  spektrometrů může selhat — proto třístupňový fallback.
"""

from __future__ import annotations

from pathlib import Path

from core.spectrum import Spectrum


class SPAReadError(Exception):
    """Raised when a SPA file cannot be read by any available parser."""


class SPAReader:
    """Three-stage fallback SPA file reader.

    Usage:
        reader = SPAReader()
        spectrum = reader.read(Path("sample.spa"))
    """

    def read(self, filepath: Path) -> Spectrum:
        """Read a .spa file and return a Spectrum object.

        Args:
            filepath: Path to the .spa file.

        Returns:
            Spectrum with wavenumbers, intensities, and available metadata.

        Raises:
            SPAReadError: If all parsers fail.
            FileNotFoundError: If the file does not exist.
        """
        if not filepath.exists():
            raise FileNotFoundError(f"SPA file not found: {filepath}")

        # Stage 1: SpectroChemPy
        try:
            return self._read_spectrochempy(filepath)
        except Exception:  # noqa: BLE001
            pass

        # Stage 2: Custom binary parser
        try:
            from file_io.spa_binary import SPABinaryReader  # noqa: PLC0415

            return SPABinaryReader().read(filepath)
        except Exception:  # noqa: BLE001
            pass

        raise SPAReadError(
            f"Failed to read '{filepath.name}' with all available parsers. "
            "The file may be corrupted or from an unsupported instrument."
        )

    def _read_spectrochempy(self, filepath: Path) -> Spectrum:
        """Read SPA using SpectroChemPy library."""
        import numpy as np  # noqa: PLC0415
        import spectrochempy as scp  # noqa: PLC0415

        from core.spectrum import SpectralUnit, XAxisUnit  # noqa: PLC0415

        dataset = scp.read_omnic(str(filepath))

        wavenumbers = np.array(dataset.x.data, dtype=np.float64)
        intensities = np.array(dataset.data.squeeze(), dtype=np.float64)

        y_unit = SpectralUnit.ABSORBANCE
        title = str(dataset.name) if dataset.name else filepath.stem

        return Spectrum(
            wavenumbers=wavenumbers,
            intensities=intensities,
            title=title,
            source_path=filepath,
            y_unit=y_unit,
            x_unit=XAxisUnit.WAVENUMBER,
        )
