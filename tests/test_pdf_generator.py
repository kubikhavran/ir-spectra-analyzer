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


def test_pdf_generator_omits_peak_table_when_disabled(tmp_path: Path, monkeypatch) -> None:
    """Peak table section should not be appended when disabled in ReportOptions."""
    from reporting.pdf_generator import PDFGenerator, ReportOptions

    project = _make_project()
    project.peaks.append(Peak(position=1500.0, intensity=0.6))
    called = False
    original = PDFGenerator._append_peak_table_section

    def _spy(self, *args, **kwargs) -> None:
        nonlocal called
        called = True
        return original(self, *args, **kwargs)

    monkeypatch.setattr(PDFGenerator, "_append_peak_table_section", _spy)

    out = tmp_path / "report_without_peak_table.pdf"
    PDFGenerator().generate(project, out, options=ReportOptions(include_peak_table=False))

    assert out.exists()
    assert not called


def test_pdf_generator_omits_metadata_when_disabled(tmp_path: Path, monkeypatch) -> None:
    """Metadata section should not be appended when disabled in ReportOptions."""
    from reporting.pdf_generator import PDFGenerator, ReportOptions

    project = _make_project()
    called = False
    original = PDFGenerator._append_metadata_and_structure_section

    def _spy(self, *args, **kwargs) -> None:
        nonlocal called
        called = True
        return original(self, *args, **kwargs)

    monkeypatch.setattr(PDFGenerator, "_append_metadata_and_structure_section", _spy)

    out = tmp_path / "report_without_metadata.pdf"
    PDFGenerator().generate(project, out, options=ReportOptions(include_metadata=False))

    assert out.exists()
    assert not called


def test_pdf_generator_omits_structures_when_disabled(tmp_path: Path, monkeypatch) -> None:
    """Structure rendering should be skipped when include_structures=False, even though the
    metadata section itself is still drawn."""
    from reporting.pdf_generator import PDFGenerator, ReportOptions

    project = _make_project()
    project.smiles = "CCO"  # project-level SMILES so structure would otherwise be rendered
    project.peaks.append(Peak(position=1500.0, intensity=0.6))

    render_calls: list = []

    def _fake_render_to_svg(*args, **kwargs) -> str:
        render_calls.append(kwargs)
        return "<svg></svg>"

    monkeypatch.setattr(
        "chemistry.structure_renderer.render_to_svg", _fake_render_to_svg
    )

    out = tmp_path / "report_without_structures.pdf"
    PDFGenerator().generate(project, out, options=ReportOptions(include_structures=False))

    assert out.exists()
    assert render_calls == [], "render_to_svg should not be called when include_structures=False"


def test_spectrum_renderer_render_to_bytes() -> None:
    """render_to_bytes returns non-empty PNG bytes."""
    from reporting.spectrum_renderer import SpectrumRenderer

    wn = np.linspace(650, 4000, 50)
    ints = np.ones(50) * 0.5
    result = SpectrumRenderer().render_to_bytes(wn, ints, [])
    assert isinstance(result, bytes)
    assert len(result) > 0
    assert result[:4] == b"\x89PNG"


def test_pdf_with_project_smiles_calls_structure_section(tmp_path, monkeypatch) -> None:
    """PDF with project.smiles='CCO' should call _append_metadata_and_structure_section."""
    from reporting.pdf_generator import PDFGenerator, ReportOptions

    project = _make_project()
    project.smiles = "CCO"

    called_with: list = []
    original = PDFGenerator._append_metadata_and_structure_section

    def _spy(self, story, proj, spectrum, key_style, val_style, options) -> None:
        called_with.append(proj.smiles)
        return original(self, story, proj, spectrum, key_style, val_style, options)

    monkeypatch.setattr(PDFGenerator, "_append_metadata_and_structure_section", _spy)

    out = tmp_path / "report_project_smiles.pdf"
    PDFGenerator().generate(project, out, options=ReportOptions(include_structures=True))

    assert out.exists()
    assert called_with == ["CCO"]


def test_pdf_without_project_smiles_skips_structure_section(tmp_path, monkeypatch) -> None:
    """PDF with empty project.smiles should not attempt to render any molecular structure."""
    from reporting.pdf_generator import PDFGenerator, ReportOptions

    project = _make_project()
    project.smiles = ""  # no project-level SMILES
    project.mol_block = ""
    project.structure_image = None

    render_calls: list = []

    def _fake_render_to_svg(*args, **kwargs) -> str:
        render_calls.append(kwargs)
        return "<svg></svg>"

    monkeypatch.setattr(
        "chemistry.structure_renderer.render_to_svg", _fake_render_to_svg
    )

    out = tmp_path / "report_no_project_smiles.pdf"
    PDFGenerator().generate(project, out, options=ReportOptions(include_structures=True))

    assert out.exists()
    assert render_calls == [], "render_to_svg should not be called without SMILES/mol_block"
