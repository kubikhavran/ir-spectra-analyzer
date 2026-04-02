"""
Interpretation — Přiřazení vibrací k peakům.

Zodpovědnost:
- Mapování Peak → VibrationPreset
- Uložení poznámek k přiřazení
- Export interpretace pro reporting
"""

from __future__ import annotations

from dataclasses import dataclass

from core.peak import Peak
from core.vibration_presets import VibrationPreset


@dataclass
class VibrationAssignment:
    """Assignment of a vibration preset to a peak.

    Attributes:
        peak: The assigned peak.
        preset: The vibration preset.
        notes: Optional analyst notes for this assignment.
    """

    peak: Peak
    preset: VibrationPreset
    notes: str = ""
