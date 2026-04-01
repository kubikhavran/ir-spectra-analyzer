"""
VibrationPresets — Správa předvoleb vibrací.

Zodpovědnost:
- Načítání vibrační předvolby z databáze
- Přiřazování předvolby k peakům
- Filtrování předvoleb dle spektrálního rozsahu
- Kategorizace vibrací (stretch, bend, etc.)
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class VibrationPreset:
    """A vibration assignment preset (functional group IR band).

    Attributes:
        name: Human-readable name (e.g., "O-H stretch").
        typical_range_min: Typical lower wavenumber limit (cm⁻¹).
        typical_range_max: Typical upper wavenumber limit (cm⁻¹).
        category: Vibration type (stretch, bend, etc.).
        description: Optional extended description.
        color: Hex color for UI display.
        db_id: Database row ID.
    """
    name: str
    typical_range_min: float
    typical_range_max: float
    category: str = ""
    description: str = ""
    color: str = "#4A90D9"
    db_id: int | None = None

    def covers_wavenumber(self, wavenumber: float) -> bool:
        """Return True if wavenumber falls within the typical range."""
        return self.typical_range_min <= wavenumber <= self.typical_range_max
