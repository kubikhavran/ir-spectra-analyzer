"""
Peak — Datový model spektrálního peaku.

Zodpovědnost:
- Reprezentace jednoho identifikovaného peaku
- Pozice, intenzita, šířka peaku
- Label pro zobrazení (cm⁻¹ hodnota nebo vlastní text)
- Přiřazená vibrační předvolba (optional)
- Pozice labelu pro ruční umístění v grafu
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Peak:
    """Single IR absorption peak.

    Attributes:
        position: Peak position in cm⁻¹.
        intensity: Peak intensity (absorbance or transmittance).
        label: Display label (defaults to position string).
        vibration_id: FK to vibration_presets table (optional).
        label_offset_x: Manual label X offset in plot units.
        label_offset_y: Manual label Y offset in plot units.
        manual_placement: True if user manually positioned the label.
        fwhm: Full width at half maximum (cm⁻¹), if computed.
        db_id: Database row ID (None if not yet persisted).
        smiles: SMILES string for the associated molecule structure (optional).
    """

    position: float
    intensity: float
    label: str = ""
    vibration_id: int | None = None
    label_offset_x: float = 0.0
    label_offset_y: float = 0.0
    manual_placement: bool = False
    fwhm: float | None = None
    db_id: int | None = None
    smiles: str = ""

    def __post_init__(self) -> None:
        if not self.label:
            self.label = f"{self.position:.1f}"

    @property
    def display_label(self) -> str:
        """Label shown in the spectrum plot."""
        return self.label or f"{self.position:.1f}"
