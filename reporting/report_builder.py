"""
ReportBuilder — Sestavení kompletního IR analytického reportu.

Zodpovědnost:
- Orchestrace renderování spektra, tabulky peaků a metadat
- Vytvoření finálního PDF z jednotlivých komponent
- Koordinace SpectrumRenderer, PDFGenerator, ReportTemplate
"""
from __future__ import annotations

from pathlib import Path

from core.project import Project
from reporting.pdf_generator import PDFGenerator
from reporting.spectrum_renderer import SpectrumRenderer


class ReportBuilder:
    """Orchestrates full PDF report assembly from a Project."""

    def __init__(self) -> None:
        self._generator = PDFGenerator()
        self._renderer = SpectrumRenderer()

    def build(self, project: Project, output_path: Path) -> None:
        """Build and save a complete PDF report.

        Args:
            project: Project with spectrum, peaks, and metadata.
            output_path: Destination PDF file path.
        """
        self._generator.generate(project, output_path)
