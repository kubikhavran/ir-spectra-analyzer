"""
PDFGenerator — Generování PDF reportu.

Zodpovědnost:
- Sestavení kompletního analytického reportu ve formátu PDF
- Integrace statického spektrálního obrázku (Matplotlib)
- Tabulka peaků s vibračními přiřazeními
- Metadata vzorku a přístrojové podmínky

Závislost: ReportLab, Matplotlib

TODO (v0.1.0 — vysoká priorita): Implementovat ReportLab layout.
"""
from __future__ import annotations

from pathlib import Path

from core.project import Project


class PDFGenerator:
    """Generates professional PDF analysis reports using ReportLab."""

    def generate(self, project: Project, output_path: Path) -> None:
        """Generate a PDF report for the given project.

        Args:
            project: Project with spectrum, peaks, and metadata.
            output_path: Destination PDF file path.
        """
        raise NotImplementedError(
            "PDFGenerator.generate() — planned for v0.1.0 (high priority)"
        )
