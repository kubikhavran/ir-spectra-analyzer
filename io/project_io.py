"""
ProjectIO — Ukládání a načítání projektů (.irproj).

Zodpovědnost:
- Serializace/deserializace Project objektu do/z databáze
- Export projektu jako .irproj soubor (ZIP archiv s JSON + metadaty)
- Import .irproj souborů

Formát .irproj:
  ZIP archiv obsahující:
  - project.json  (metadata, peaky, interpretace)
  - spectrum.npy  (numpy binary pro rychlé načtení)

Plánováno pro v0.2.0.
"""
from __future__ import annotations

from pathlib import Path

from core.project import Project


class ProjectIO:
    """Handles project serialization and deserialization."""

    def save(self, project: Project, output_path: Path) -> None:
        """Save project to .irproj file.

        Args:
            project: Project to save.
            output_path: Destination path (should have .irproj extension).
        """
        raise NotImplementedError("ProjectIO.save() — not yet implemented (v0.2.0)")

    def load(self, filepath: Path) -> Project:
        """Load project from .irproj file.

        Args:
            filepath: Path to .irproj file.

        Returns:
            Loaded Project instance.
        """
        raise NotImplementedError("ProjectIO.load() — not yet implemented (v0.2.0)")
