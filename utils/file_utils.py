"""
FileUtils — Utility pro práci se soubory.

Zodpovědnost:
- Validace přípon souborů
- Bezpečné zajištění přípony výstupního souboru
"""

from __future__ import annotations

from pathlib import Path

SUPPORTED_SPECTRAL_EXTENSIONS = {".spa", ".spc", ".jdx", ".dx", ".csv"}


def is_supported_spectral_file(path: Path) -> bool:
    """Return True if the file extension is a supported spectral format."""
    return path.suffix.lower() in SUPPORTED_SPECTRAL_EXTENSIONS


def ensure_extension(path: Path, extension: str) -> Path:
    """Return path with the given extension, adding it if missing.

    Args:
        path: Input file path.
        extension: Desired extension (with dot, e.g., ".pdf").

    Returns:
        Path with correct extension.
    """
    if path.suffix.lower() != extension.lower():
        return path.with_suffix(extension)
    return path
