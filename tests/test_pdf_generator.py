"""Tests for PDF report generation."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from core.peak import Peak
from core.project import Project
from core.spectrum import SpectralUnit, Spectrum


def _make_spectrum(y_unit: SpectralUnit = SpectralUnit.TRANSMITTANCE) -> Spectrum:
    wn = np.linspace(650, 4000, 200)
    ints = np.random.default_rng(0).uniform(20, 90, 200)
    return Spectrum(wavenumbers=wn, intensities=ints, y_unit=y_unit)


def _make_project(name: str = "Test Project", **kwargs) -> Project:
    return Project(name=name, spectrum=_make_spectrum(), **kwargs)


def test_pdf_generates_file(tmp_path: Path) -> None:
    """Generated PDF file exists and is larger than 1 kB."""
    from reporting.pdf_generator import PDFGenerator

    project = _make_project()
    out = tmp_path / "report.pdf"
    PDFGenerator().generate(project, out)
    assert out.exists()
    assert out.stat().st_size > 1000


def test_pdf_with_peaks(tmp_path: Path) -> None:
    """PDF is generated without error when peaks are present."""
    from reporting.pdf_generator import PDFGenerator

    project = _make_project()
    for pos in [1000.0, 2000.0, 3000.0]:
        project.peaks.append(Peak(position=pos, intensity=0.5))

    out = tmp_path / "report_peaks.pdf"
    PDFGenerator().generate(project, out)
    assert out.exists()
    assert out.stat().st_size > 2000


def test_pdf_no_spectrum_raises() -> None:
    """ValueError is raised when project has no spectrum."""
    from reporting.pdf_generator import PDFGenerator

    project = Project(name="empty")
    with pytest.raises(ValueError, match="no spectrum"):
        PDFGenerator().generate(project, Path("/tmp/irrelevant.pdf"))


def test_pdf_output_is_valid_pdf(tmp_path: Path) -> None:
    """Output file starts with the PDF magic bytes."""
    from reporting.pdf_generator import PDFGenerator

    project = _make_project()
    out = tmp_path / "report_magic.pdf"
    PDFGenerator().generate(project, out)
    assert out.read_bytes()[:4] == b"%PDF"


def test_pdf_with_structure_section_no_smiles(tmp_path: Path) -> None:
    """PDF is generated without error when peaks have no SMILES (structures section skipped)."""
    from reporting.pdf_generator import PDFGenerator

    project = _make_project()
    for pos in [1000.0, 2000.0]:
        project.peaks.append(Peak(position=pos, intensity=0.5))

    out = tmp_path / "report_no_smiles.pdf"
    PDFGenerator().generate(project, out)
    assert out.exists()
    assert out.stat().st_size > 1000


def test_report_builder_build_with_options(tmp_path: Path) -> None:
    """ReportBuilder.build_with_options generates a PDF without error when structures are disabled."""
    from reporting.pdf_generator import ReportOptions
    from reporting.report_builder import ReportBuilder

    project = _make_project()
    project.peaks.append(Peak(position=1500.0, intensity=0.6))

    out = tmp_path / "report_no_structures.pdf"
    ReportBuilder().build_with_options(project, out, ReportOptions(include_structures=False))
    assert out.exists()
    assert out.stat().st_size > 1000


def test_spectrum_renderer_render_to_bytes() -> None:
    """render_to_bytes returns non-empty PNG bytes."""
    from reporting.spectrum_renderer import SpectrumRenderer

    wn = np.linspace(650, 4000, 50)
    ints = np.ones(50) * 0.5
    result = SpectrumRenderer().render_to_bytes(wn, ints, [])
    assert isinstance(result, bytes)
    assert len(result) > 0
    assert result[:4] == b"\x89PNG"
