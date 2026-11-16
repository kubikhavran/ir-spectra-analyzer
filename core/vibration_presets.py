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
        is_builtin: True for an entry of the shipped library.
        seed_name: The name a built-in entry shipped with. Built-in entries can
            be renamed; the functional-group knowledge base still refers to
            them by this name.
    """

    name: str
    typical_range_min: float
    typical_range_max: float
    category: str = ""
    description: str = ""
    color: str = "#4A90D9"
    db_id: int | None = None
    is_builtin: bool = True
    seed_name: str = ""

    @property
    def catalog_name(self) -> str:
        """Name the knowledge base knows this entry by (survives a rename)."""
        return self.seed_name or self.name

    def answers_to(self, names) -> bool:
        """True when ``names`` refers to this entry, by its current or shipped name."""
        return self.name in names or self.catalog_name in names

    def covers_wavenumber(self, wavenumber: float) -> bool:
        """Return True if wavenumber falls within the typical range."""
        return self.typical_range_min <= wavenumber <= self.typical_range_max
