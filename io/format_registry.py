"""
FormatRegistry — Registr podporovaných vstupních formátů.

Zodpovědnost:
- Plug-in architektura pro různé spektrální formáty
- Registrace čteček dle přípony souboru
- Dynamický dispatch na správnou čtečku
- Rozšiřitelný bez změny zbytku kódu

Aktuálně podporované formáty:
- .spa (Thermo Fisher OMNIC)

Plánované (v0.2+):
- .spc (Galactic SPC)
- .jdx / .dx (JCAMP-DX)
- .csv (tabulková data)
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from core.spectrum import Spectrum


class SpectralReader(Protocol):
    """Protocol for all spectral file readers."""

    def read(self, filepath: Path) -> Spectrum:
        """Read a spectral file and return a Spectrum object."""
        ...


class FormatRegistry:
    """Registry mapping file extensions to reader implementations."""

    def __init__(self) -> None:
        self._readers: dict[str, SpectralReader] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        """Register built-in format readers."""
        from io.spa_reader import SPAReader  # noqa: PLC0415

        self.register(".spa", SPAReader())

    def register(self, extension: str, reader: SpectralReader) -> None:
        """Register a reader for a file extension.

        Args:
            extension: Lowercase extension with dot (e.g., ".spa").
            reader: Reader instance implementing SpectralReader protocol.
        """
        self._readers[extension.lower()] = reader

    def read(self, filepath: Path) -> Spectrum:
        """Read a spectral file using the appropriate registered reader.

        Args:
            filepath: Path to the spectral file.

        Returns:
            Spectrum object.

        Raises:
            ValueError: If no reader is registered for this file type.
        """
        ext = filepath.suffix.lower()
        reader = self._readers.get(ext)
        if reader is None:
            supported = ", ".join(sorted(self._readers.keys()))
            raise ValueError(f"Unsupported file format '{ext}'. Supported formats: {supported}")
        return reader.read(filepath)
