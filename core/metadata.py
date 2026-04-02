"""
Metadata — Metadata spektra.

Zodpovědnost:
- Strukturovaná reprezentace metadat extrahovaných ze SPA souboru
- Uživatelem editovatelná pole (vzorek, operátor, poznámky)
- Serializace pro ukládání do databáze
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class SpectrumMetadata:
    """Metadata associated with an IR spectrum.

    Attributes:
        title: Spectrum title from file header.
        sample_name: Sample identifier (user-editable).
        operator: Analyst name (user-editable).
        instrument: Spectrometer model/identifier.
        acquired_at: Acquisition timestamp.
        resolution: Spectral resolution in cm⁻¹.
        scans: Number of scans averaged.
        comments: Free-text notes.
        extra: Additional key-value metadata from file.
    """

    title: str = ""
    sample_name: str = ""
    operator: str = ""
    instrument: str = ""
    acquired_at: datetime | None = None
    resolution: float | None = None
    scans: int | None = None
    comments: str = ""
    extra: dict = field(default_factory=dict)
