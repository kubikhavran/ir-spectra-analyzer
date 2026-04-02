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
from reporting.pdf_generator import PDFGenerator, ReportOptions
from reporting.spectrum_renderer import SpectrumRenderer


class ReportBuilder:
    """Orchestrates full PDF report assembly from a Project.

    Wraps PDFGenerator and provides option-driven report generation.
    """

    def __init__(self) -> None:
        self._generator = PDFGenerator()
        self._renderer = SpectrumRenderer()

    def build(self, project: Project, output_path: Path) -> None:
        """Build and save a complete PDF report with default options.

        Args:
            project: Project with spectrum, peaks, and metadata.
            output_path: Destination PDF file path.
        """
        self.build_with_options(project, output_path, ReportOptions())

    def build_with_options(
        self, project: Project, output_path: Path, options: ReportOptions
    ) -> None:
        """Build and save a PDF report with the given options.

        Args:
            project: Project with spectrum, peaks, and metadata.
            output_path: Destination PDF file path.
            options: ReportOptions controlling report content.
        """
        self._generator.generate(project, output_path, options=options)
