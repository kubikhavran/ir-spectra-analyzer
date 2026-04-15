"""
Project — Kontejner pro celý analytický projekt.

Zodpovědnost:
- Drží veškerý stav: spektrum + peaky + metadata + interpretace
- Single source of truth pro aktuální analýzu
- Implementuje command pattern pro Undo/Redo (v0.2.0)
- Emituje Qt signály při změnách pro aktualizaci UI

Pravidlo: UI nikdy nemodifikuje data přímo.
Vždy volá metody na Project instanci.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from core.peak import Peak
from core.spectrum import Spectrum


@dataclass
class Project:
    """Analytical project combining spectrum, peaks, and metadata.

    Attributes:
        name: Project name (editable by user).
        spectrum: The loaded IR spectrum.
        peaks: List of identified peaks.
        created_at: Project creation timestamp.
        updated_at: Last modification timestamp.
        db_id: Database row ID (None if not persisted).
    """

    name: str
    spectrum: Spectrum | None = None
    corrected_spectrum: Spectrum | None = None
    peaks: list[Peak] = field(default_factory=list)
    smiles: str = ""
    structure_image: bytes = field(default=b"")
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    db_id: int | None = None

    def add_peak(self, peak: Peak) -> None:
        """Add a peak to the project and update modification time."""
        self.peaks.append(peak)
        self.updated_at = datetime.now()

    def remove_peak(self, peak: Peak) -> bool:
        """Remove a peak from the project. Returns True if found and removed."""
        try:
            self.peaks.remove(peak)
            self.updated_at = datetime.now()
            return True
        except ValueError:
            return False

    def clear_peaks(self) -> None:
        """Remove all peaks from the project."""
        self.peaks.clear()
        self.updated_at = datetime.now()
