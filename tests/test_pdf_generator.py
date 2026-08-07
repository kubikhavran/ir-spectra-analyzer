"""Tests for PDF report generation."""

from __future__ import annotations

import io
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


def test_pdf_peak_table_omits_numeric_peak_intensity_column(monkeypatch) -> None:
    """PDF peak table should keep qualitative intensity class but omit raw peak intensity."""
    from reportlab.lib.styles import getSampleStyleSheet

    from reporting.pdf_generator import PDFGenerator

    peak = Peak(position=2864.0, intensity=86.7, vibration_id=42, label="νas(NH₂)")
    peak.vibration_ids = [42]
    peak.vibration_labels = ["νas(NH₂)"]

    captured: dict[str, object] = {}
    original_table = PDFGenerator._append_peak_table_section.__globals__["Table"]

    class _TableSpy:
        def __init__(self, table_data, colWidths=None) -> None:  # noqa: N803
            captured["table_data"] = table_data
            captured["col_widths"] = colWidths

        def setStyle(self, style) -> None:  # noqa: N802
            captured["style"] = style

    monkeypatch.setitem(PDFGenerator._append_peak_table_section.__globals__, "Table", _TableSpy)

    styles = getSampleStyleSheet()
    story: list[object] = []
    PDFGenerator()._append_peak_table_section(
        story,
        [peak],
        styles["Heading2"],
        styles["Normal"],
        styles["Normal"],
        styles["Normal"],
        is_dip_spectrum=True,
    )

    monkeypatch.setitem(
        PDFGenerator._append_peak_table_section.__globals__, "Table", original_table
    )

    table_data = captured["table_data"]
    assert len(table_data[0]) == 3
    assert len(table_data[1]) == 3
    assert [cell.getPlainText() for cell in table_data[0]] == [
        "Position (cm⁻¹)",
        "Int.",
        "Assignment",
    ]
    assert len(captured["col_widths"]) == 3


def test_pdf_generator_peak_table_includes_only_assigned_peaks(tmp_path: Path, monkeypatch) -> None:
    """Peak assignments table should only include peaks with a real vibration assignment."""
    from reporting.pdf_generator import PDFGenerator

    project = _make_project()
    project.peaks.extend(
        [
            Peak(position=3134.0, intensity=85.3, label="3134"),
            Peak(
                position=3030.0,
                intensity=85.2,
                vibration_ids=[None],
                vibration_labels=["ν(CH₃)"],
            ),
            Peak(
                position=2864.0,
                intensity=86.7,
                vibration_id=42,
                label="νas(NH₂)",
            ),
        ]
    )

    captured_positions: list[float] = []
    original = PDFGenerator._append_peak_table_section

    def _spy(
        self,
        story,
        sorted_peaks,
        section_style,
        table_header_style,
        table_cell_style,
        table_cell_right,
        *,
        is_dip_spectrum=False,
    ) -> None:
        captured_positions.extend(peak.position for peak in sorted_peaks)
        return original(
            self,
            story,
            sorted_peaks,
            section_style,
            table_header_style,
            table_cell_style,
            table_cell_right,
            is_dip_spectrum=is_dip_spectrum,
        )

    monkeypatch.setattr(PDFGenerator, "_append_peak_table_section", _spy)

    out = tmp_path / "report_only_assigned_peaks.pdf"
    PDFGenerator().generate(project, out)

    assert out.exists()
    assert captured_positions == [3030.0, 2864.0]


def test_pdf_generator_omits_peak_table_when_no_peaks_have_assignments(
    tmp_path: Path, monkeypatch
) -> None:
    """Peak assignments section should be skipped entirely when nothing is assigned."""
    from reporting.pdf_generator import PDFGenerator

    project = _make_project()
    project.peaks.extend(
        [
            Peak(position=3134.0, intensity=85.3, label="3134"),
            Peak(position=1967.0, intensity=99.0, label="1967"),
        ]
    )

    called = False
    original = PDFGenerator._append_peak_table_section

    def _spy(self, *args, **kwargs) -> None:
        nonlocal called
        called = True
        return original(self, *args, **kwargs)

    monkeypatch.setattr(PDFGenerator, "_append_peak_table_section", _spy)

    out = tmp_path / "report_without_assigned_peaks.pdf"
    PDFGenerator().generate(project, out)

    assert out.exists()
    assert called is False


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

    monkeypatch.setattr("chemistry.structure_renderer.render_to_svg", _fake_render_to_svg)

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


def test_spectrum_renderer_respects_manual_peak_label_offsets(monkeypatch) -> None:
    """Renderer should place peak labels using the same stored offsets as the live viewer."""
    import matplotlib.axes._axes as maxes

    from reporting.spectrum_renderer import SpectrumRenderer

    captured_positions: list[tuple[float, float, str]] = []
    original_text = maxes.Axes.text

    def _spy_text(self, x, y, s, *args, **kwargs):
        captured_positions.append((float(x), float(y), str(s)))
        return original_text(self, x, y, s, *args, **kwargs)

    monkeypatch.setattr(maxes.Axes, "text", _spy_text)

    wn = np.linspace(650, 4000, 50)
    ints = np.ones(50) * 0.5
    peak = Peak(
        position=1500.0,
        intensity=0.5,
        manual_placement=True,
        label_offset_x=12.0,
        label_offset_y=-0.2,
    )

    SpectrumRenderer().render_to_bytes(wn, ints, [peak], y_view_range=(0.0, 1.0))

    assert captured_positions
    x_pos, y_pos, label = captured_positions[0]
    assert label == "1500"
    assert x_pos == pytest.approx(1512.0)
    assert y_pos == pytest.approx(0.3)


def test_spectrum_renderer_can_render_diagnostic_regions() -> None:
    """Renderer should still produce a valid PNG when diagnostic regions are included."""
    from types import SimpleNamespace

    from reporting.spectrum_renderer import SpectrumRenderer

    wn = np.linspace(650, 4000, 50)
    ints = np.ones(50) * 0.5
    region = SimpleNamespace(
        range_min=1000.0,
        range_max=1200.0,
        color="#2980B9",
        is_missing_required=False,
        is_confirmed=True,
    )

    result = SpectrumRenderer().render_to_bytes(wn, ints, [], diagnostic_regions=(region,))

    assert result[:4] == b"\x89PNG"
    assert len(result) > 1000


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

    monkeypatch.setattr("chemistry.structure_renderer.render_to_svg", _fake_render_to_svg)

    out = tmp_path / "report_no_project_smiles.pdf"
    PDFGenerator().generate(project, out, options=ReportOptions(include_structures=True))

    assert out.exists()
    assert render_calls == [], "render_to_svg should not be called without SMILES/mol_block"


def _banded_spectrum() -> tuple[np.ndarray, np.ndarray, list[Peak]]:
    """A %T spectrum with a flat baseline and a few sharp bands — plenty of free area."""
    wn = np.linspace(650, 4000, 4000)
    ints = np.full_like(wn, 97.0)
    bands = [(1050, 40), (1250, 30), (1600, 30), (1700, 55), (2950, 20), (3300, 15)]
    for centre, depth in bands:
        ints -= depth * np.exp(-0.5 * ((wn - centre) / 10.0) ** 2)
    peaks = [
        Peak(position=float(centre), intensity=float(np.interp(centre, wn, ints)))
        for centre, _ in bands
    ]
    return wn, ints, peaks


def test_full_bleed_spectrum_uses_the_whole_sheet(tmp_path: Path, monkeypatch) -> None:
    """The edge-to-edge layout renders the plot at full page size, not inside margins."""
    from reporting import pdf_generator as pdf_module
    from reporting.pdf_generator import LAYOUT_FULL_BLEED, PDFGenerator, ReportOptions
    from reporting.spectrum_renderer import SpectrumRenderer

    captured: dict[str, object] = {}
    original = SpectrumRenderer.render_with_annotation_box

    def _spy(self, *args, **kwargs):
        captured["figsize"] = kwargs["figsize"]
        return original(self, *args, **kwargs)

    monkeypatch.setattr(SpectrumRenderer, "render_with_annotation_box", _spy)

    out = tmp_path / "full_bleed.pdf"
    PDFGenerator().generate(_make_project(), out, options=ReportOptions(layout=LAYOUT_FULL_BLEED))

    assert out.read_bytes().startswith(b"%PDF")
    fig_w, fig_h = captured["figsize"]
    assert fig_w * 72 == pytest.approx(pdf_module._LAND_W)
    assert fig_h * 72 == pytest.approx(pdf_module._LAND_H)


def test_full_page_layout_is_the_export_default() -> None:
    """Exporting without an explicit choice produces the full-page spectrum."""
    from reporting.pdf_generator import LAYOUT_FULL_BLEED, ReportOptions

    assert ReportOptions().layout == LAYOUT_FULL_BLEED


def test_standard_layout_keeps_the_framed_spectrum_page(tmp_path: Path, monkeypatch) -> None:
    """The older layout is untouched — it still flows the spectrum through a frame."""
    from reporting.pdf_generator import LAYOUT_STANDARD, PDFGenerator, ReportOptions

    calls: list[str] = []
    original_section = PDFGenerator._append_spectrum_section
    original_full_bleed = PDFGenerator._build_full_bleed_first_page

    def _spy_section(self, *args, **kwargs):
        calls.append("framed")
        return original_section(self, *args, **kwargs)

    def _spy_full_bleed(self, *args, **kwargs):
        calls.append("full_bleed")
        return original_full_bleed(self, *args, **kwargs)

    monkeypatch.setattr(PDFGenerator, "_append_spectrum_section", _spy_section)
    monkeypatch.setattr(PDFGenerator, "_build_full_bleed_first_page", _spy_full_bleed)

    PDFGenerator().generate(
        _make_project(),
        tmp_path / "standard.pdf",
        options=ReportOptions(layout=LAYOUT_STANDARD),
    )

    assert calls == ["framed"]


def test_full_bleed_page_draws_identity_and_structure() -> None:
    """File name, sample name and the molecule all land on the full-page spectrum.

    The two identity lines must be visually equal — same font, size and colour —
    with the file identifier first and without its spectrum-file extension.
    """
    from reporting.pdf_generator import LAYOUT_FULL_BLEED, PDFGenerator, ReportOptions

    wn, ints, peaks = _banded_spectrum()
    spectrum = Spectrum(
        wavenumbers=wn, intensities=ints, y_unit=SpectralUnit.TRANSMITTANCE, title="PAR1706-HA"
    )
    project = Project(name="PAR1706-HA", spectrum=spectrum)
    project.peaks.extend(peaks)
    project.smiles = "CCO"
    project.metadata.title = "LF_647"
    project.metadata.file_name = "PAR1706-HA.SPA"

    drawn_strings: list[tuple[str, tuple[str, float], object]] = []
    drawn_images: list[tuple[float, float]] = []

    class _RecordingCanvas:
        _pagesize = (100.0, 100.0)

        def __init__(self) -> None:
            self.font: tuple[str, float] = ("", 0.0)
            self.fill: object = None

        def __getattr__(self, name):
            def _noop(*args, **kwargs):
                return None

            return _noop

        def setFont(self, name, size):  # noqa: N802
            self.font = (name, size)

        def setFillColor(self, color):  # noqa: N802
            self.fill = color

        def drawString(self, x, y, text):  # noqa: N802
            drawn_strings.append((text, self.font, self.fill))

        def drawImage(self, image, x, y, **kwargs):  # noqa: N802
            drawn_images.append((kwargs.get("width", 0.0), kwargs.get("height", 0.0)))

    generator = PDFGenerator()
    painter = generator._build_full_bleed_first_page(
        project,
        spectrum,
        ReportOptions(layout=LAYOUT_FULL_BLEED, dpi=72),
        x_min=650.0,
        x_max=4000.0,
        font_bold="Helvetica-Bold",
    )
    canvas = _RecordingCanvas()
    canvas._pagesize = (841.89, 595.28)
    painter(canvas, None)

    assert [entry[0] for entry in drawn_strings] == ["PAR1706-HA", "LF_647"]
    assert drawn_strings[0][1] == drawn_strings[1][1]  # identical font and size
    assert drawn_strings[0][2] == drawn_strings[1][2]  # identical colour
    # First image is the page-filling spectrum, second the molecule inside it.
    assert len(drawn_images) == 2
    assert drawn_images[0] == pytest.approx((841.89, 595.28))
    assert 0 < drawn_images[1][0] < 841.89


def test_identity_line_only_strips_known_spectrum_extensions() -> None:
    """A dot inside the name is not an extension and must survive."""
    from reporting.pdf_generator import PDFGenerator

    strip = PDFGenerator._without_spectrum_suffix
    assert strip("FER60-SE.SPA") == "FER60-SE"
    assert strip("PAR1706-HA.spa") == "PAR1706-HA"
    assert strip("run.jdx") == "run"
    assert strip("saved.irproj") == "saved"
    assert strip("sample 2.5 mg") == "sample 2.5 mg"
    assert strip("FER60-SE") == "FER60-SE"


def _assert_box_is_blank(png_bytes: bytes, box: tuple[float, float, float, float]) -> None:
    """Fail unless every pixel under the reported free box is white."""
    from PIL import Image as PILImage

    with PILImage.open(io.BytesIO(png_bytes)) as image:
        rgb = image.convert("RGB")
        width, height = rgb.size
        # Figure fractions measure y from the bottom; PIL rows from the top.
        crop = rgb.crop(
            (
                round(box[0] * width),
                round((1.0 - box[3]) * height),
                round(box[2] * width),
                round((1.0 - box[1]) * height),
            )
        )
    assert crop.size[0] > 0
    assert crop.size[1] > 0
    assert crop.getextrema() == ((255, 255), (255, 255), (255, 255))


def test_full_bleed_annotation_lands_on_empty_canvas() -> None:
    """The reported free box must contain no ink from the rendered spectrum."""
    from reporting.spectrum_renderer import SpectrumRenderer

    wn, ints, peaks = _banded_spectrum()
    png_bytes, box = SpectrumRenderer().render_with_annotation_box(
        wn,
        ints,
        peaks,
        dpi=100,
        y_unit=SpectralUnit.TRANSMITTANCE,
        is_dip_spectrum=True,
        figsize=(11.69, 8.27),
        x_min=650.0,
        x_max=4000.0,
        annotation_target=(0.26, 0.40),
    )

    assert box is not None
    # Nothing was given up: the block fits at the full size it asked for.
    assert box[2] - box[0] == pytest.approx(0.26, abs=0.01)
    assert box[3] - box[1] == pytest.approx(0.40, abs=0.01)
    _assert_box_is_blank(png_bytes, box)


def test_annotation_box_sits_in_the_corner_of_the_axes() -> None:
    """The block hugs the far edge of its gap: bottom for %T, top for absorbance."""
    from reporting.spectrum_renderer import SpectrumRenderer

    wn, dip_intensities, peaks = _banded_spectrum()
    kwargs = {
        "dpi": 72,
        "figsize": (11.69, 8.27),
        "x_min": 650.0,
        "x_max": 4000.0,
        "annotation_target": (0.26, 0.40),
    }

    _png, dip_box = SpectrumRenderer().render_with_annotation_box(
        wn,
        dip_intensities,
        peaks,
        y_unit=SpectralUnit.TRANSMITTANCE,
        is_dip_spectrum=True,
        **kwargs,
    )
    flipped = 100.0 - dip_intensities
    up_peaks = [Peak(position=peak.position, intensity=100.0 - peak.intensity) for peak in peaks]
    _png, abs_box = SpectrumRenderer().render_with_annotation_box(
        wn,
        flipped,
        up_peaks,
        y_unit=SpectralUnit.ABSORBANCE,
        is_dip_spectrum=False,
        **kwargs,
    )

    assert dip_box is not None
    assert abs_box is not None
    # Both plots share the same axes geometry, so the two boxes must end up on
    # opposite edges of it — neither floating near the middle.
    assert dip_box[1] < 0.15
    assert abs_box[3] > 0.90


def test_saturated_plot_still_gets_a_blank_block_area() -> None:
    """Wall-to-wall noise has no natural gap, so a bounded y-stretch makes one."""
    from reporting.spectrum_renderer import SpectrumRenderer

    wn = np.linspace(650, 4000, 4000)
    ints = np.random.default_rng(1).uniform(0.0, 100.0, wn.size)

    png_bytes, box = SpectrumRenderer().render_with_annotation_box(
        wn,
        ints,
        [],
        dpi=100,
        y_unit=SpectralUnit.TRANSMITTANCE,
        is_dip_spectrum=True,
        figsize=(11.69, 8.27),
        x_min=650.0,
        x_max=4000.0,
        annotation_target=(0.26, 0.40),
    )

    assert box is not None
    # The stretch is capped, so the block ends up smaller than it asked for
    # rather than the curve being squashed to make room.
    assert box[3] - box[1] < 0.40
    _assert_box_is_blank(png_bytes, box)


def _pdf_page_count(path: Path) -> int:
    import re

    data = path.read_bytes()
    return len(re.findall(rb"/Type\s*/Page[^s]", data))


def test_pdf_assignment_table_shares_metadata_page(tmp_path: Path) -> None:
    """A 45-assignment two-column table stays on the metadata page (no own page, no orphan)."""
    from reporting.pdf_generator import PDFGenerator, ReportOptions

    project = _make_project()
    for i in range(45):
        project.peaks.append(
            Peak(position=500.0 + i * 70.0, intensity=60.0, vibration_labels=["ν test"])
        )

    out = tmp_path / "balanced.pdf"
    PDFGenerator().generate(
        project, out, options=ReportOptions(split_xaxis=False, include_structures=False)
    )
    # spectrum page + one combined metadata + two-column table page
    assert _pdf_page_count(out) == 2


def test_pdf_very_large_assignment_table_splits_across_pages(tmp_path: Path) -> None:
    """A table too tall for one page splits across pages (header repeats), no crash."""
    from reporting.pdf_generator import PDFGenerator, ReportOptions

    project = _make_project()
    for i in range(130):
        project.peaks.append(
            Peak(position=450.0 + i * 27.0, intensity=60.0, vibration_labels=["ν test"])
        )

    out = tmp_path / "big.pdf"
    PDFGenerator().generate(
        project, out, options=ReportOptions(split_xaxis=False, include_structures=False)
    )
    assert out.read_bytes().startswith(b"%PDF")
    assert _pdf_page_count(out) >= 3


def test_pdf_uses_corrected_spectrum_when_available(tmp_path: Path, monkeypatch) -> None:
    from reporting.pdf_generator import PDFGenerator

    project = _make_project()
    project.corrected_spectrum = Spectrum(
        wavenumbers=project.spectrum.wavenumbers.copy(),
        intensities=np.full_like(project.spectrum.intensities, 7.0),
        y_unit=SpectralUnit.BASELINE_CORRECTED,
    )
    captured: dict[str, Spectrum] = {}
    original = PDFGenerator._build_full_bleed_first_page

    def _spy(self, project_arg, spectrum_arg, *args, **kwargs):
        captured["spectrum"] = spectrum_arg
        return original(self, project_arg, spectrum_arg, *args, **kwargs)

    monkeypatch.setattr(PDFGenerator, "_build_full_bleed_first_page", _spy)

    PDFGenerator().generate(project, tmp_path / "corrected.pdf")

    assert captured["spectrum"] is project.corrected_spectrum


def test_pdf_default_x_range_expands_to_full_spectrum_data(tmp_path: Path, monkeypatch) -> None:
    from reporting.pdf_generator import PDFGenerator
    from reporting.spectrum_renderer import SpectrumRenderer

    project = _make_project()
    captured: dict[str, float] = {}
    original = SpectrumRenderer.render_with_annotation_box

    def _spy(self, *args, **kwargs):
        captured["x_min"] = kwargs["x_min"]
        captured["x_max"] = kwargs["x_max"]
        return original(self, *args, **kwargs)

    monkeypatch.setattr(SpectrumRenderer, "render_with_annotation_box", _spy)

    PDFGenerator().generate(project, tmp_path / "full-range.pdf")

    assert captured == {"x_min": 400.0, "x_max": 4000.0}


def test_pdf_escapes_dynamic_paragraph_text(tmp_path: Path) -> None:
    from reporting.pdf_generator import PDFGenerator

    project = _make_project()
    project.metadata.file_name = "sample <broken"
    project.metadata.title = "<b>literal title</b> & comparison"
    project.metadata.comments = "A < B & C > D"
    project.peaks.append(
        Peak(
            position=1700.0,
            intensity=20.0,
            vibration_ids=[None],
            vibration_labels=["<b>literal assignment</b> & note"],
        )
    )

    output_path = tmp_path / "escaped.pdf"
    PDFGenerator().generate(project, output_path)

    assert output_path.read_bytes().startswith(b"%PDF")


def test_pdf_failed_build_preserves_existing_file(tmp_path: Path, monkeypatch) -> None:
    from reporting.pdf_generator import BaseDocTemplate, PDFGenerator

    output_path = tmp_path / "existing.pdf"
    output_path.write_bytes(b"known-good")

    def _failing_build(self, _story) -> None:
        Path(self.filename).write_bytes(b"partial")
        raise OSError("simulated disk failure")

    monkeypatch.setattr(BaseDocTemplate, "build", _failing_build)

    with pytest.raises(OSError, match="simulated disk failure"):
        PDFGenerator().generate(_make_project(), output_path)

    assert output_path.read_bytes() == b"known-good"


def test_spectrum_renderer_closes_figure_when_savefig_fails(monkeypatch) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.figure import Figure

    from reporting.spectrum_renderer import SpectrumRenderer

    before = set(plt.get_fignums())

    def _failing_savefig(self, *args, **kwargs) -> None:
        raise OSError("simulated render failure")

    monkeypatch.setattr(Figure, "savefig", _failing_savefig)

    with pytest.raises(OSError, match="simulated render failure"):
        SpectrumRenderer().render_to_bytes(
            np.array([400.0, 1000.0, 2000.0]),
            np.array([0.1, 0.2, 0.15]),
            [],
            split_at=None,
        )

    assert set(plt.get_fignums()) == before
