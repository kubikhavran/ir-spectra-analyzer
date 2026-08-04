"""
PDFGenerator — Generování PDF reportu.

Zodpovědnost:
- Sestavení kompletního analytického reportu ve formátu PDF
- Integrace statického spektrálního obrázku (Matplotlib)
- Tabulka peaků s vibračními přiřazeními
- Metadata vzorku a přístrojové podmínky

Závislost: ReportLab, Matplotlib
"""

from __future__ import annotations

import io
import struct
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import matplotlib
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    Image,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from core.peak_assignments import (
    build_peak_assignment_rows,
    classify_peak_intensities,
    peak_assignment_text,
)
from core.project import Project
from reporting.spectrum_renderer import SpectrumRenderer

if TYPE_CHECKING:
    from reportlab.pdfgen.canvas import Canvas

    from core.spectrum import Spectrum

# ---------------------------------------------------------------------------
# Unicode font registration — DejaVu Sans ships with Matplotlib and covers
# Greek letters, subscripts, superscripts used in IR vibration labels.
# ---------------------------------------------------------------------------
_FONT_DIR = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
_FONTS_REGISTERED = False


def _ensure_fonts() -> tuple[str, str, str]:
    """Register DejaVu Sans fonts once and return (regular, bold, oblique) names."""
    global _FONTS_REGISTERED  # noqa: PLW0603
    regular = "Helvetica"
    bold = "Helvetica-Bold"
    oblique = "Helvetica-Oblique"

    ttf_regular = _FONT_DIR / "DejaVuSans.ttf"
    ttf_bold = _FONT_DIR / "DejaVuSans-Bold.ttf"
    ttf_oblique = _FONT_DIR / "DejaVuSans-Oblique.ttf"

    if not _FONTS_REGISTERED and ttf_regular.exists():
        pdfmetrics.registerFont(TTFont("DejaVuSans", str(ttf_regular)))
        if ttf_bold.exists():
            pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", str(ttf_bold)))
        if ttf_oblique.exists():
            pdfmetrics.registerFont(TTFont("DejaVuSans-Oblique", str(ttf_oblique)))
        _FONTS_REGISTERED = True
        regular = "DejaVuSans"
        bold = "DejaVuSans-Bold" if ttf_bold.exists() else "DejaVuSans"
        oblique = "DejaVuSans-Oblique" if ttf_oblique.exists() else "DejaVuSans"
    elif _FONTS_REGISTERED:
        regular = "DejaVuSans"
        bold = "DejaVuSans-Bold" if (ttf_bold).exists() else "DejaVuSans"
        oblique = "DejaVuSans-Oblique" if (ttf_oblique).exists() else "DejaVuSans"

    return regular, bold, oblique


# Default figsize (used only if spectrum section gets a text_height constraint)
_RENDERER_FIG_W = 7.5
_RENDERER_FIG_H = 3.2

_MARGIN = 2 * cm

# Landscape A4 (page 1 — spectrum)
_LAND_W, _LAND_H = landscape(A4)
_LAND_TEXT_W = _LAND_W - 2 * _MARGIN
_LAND_TEXT_H = _LAND_H - 2 * _MARGIN - 0.5 * cm  # leave room for footer

# Portrait A4 (pages 2+)
_PORT_W, _PORT_H = A4
_PORT_TEXT_W = _PORT_W - 2 * _MARGIN
_PORT_TEXT_H = _PORT_H - 2 * _MARGIN - 0.5 * cm  # leave room for footer

# First-page layouts.
LAYOUT_STANDARD = "standard"
LAYOUT_FULL_BLEED = "full_bleed"
LAYOUT_CHOICES = (LAYOUT_STANDARD, LAYOUT_FULL_BLEED)

# Extensions dropped from the identity line drawn on the spectrum — there it
# reads as a sample identifier, not as a file name. The metadata table on the
# later pages still prints the file name in full.
_IDENTITY_STRIPPED_SUFFIXES = frozenset({".spa", ".jdx", ".dx", ".irproj"})

# The edge-to-edge page has no margins to hide resampling in, and its text is
# drawn by ReportLab rather than rasterised — but the curve and peak labels are
# still pixels, so give them a floor above the 150 dpi used inside a frame.
_FULL_BLEED_MIN_DPI = 200


@dataclass
class ReportOptions:
    """Options controlling what sections appear in the PDF report.

    Attributes:
        include_structures: If True, include molecular structure images for peaks with SMILES.
        include_peak_table: If True, include the peak assignments table.
        include_metadata: If True, include the project/spectrum metadata table.
        dpi: Resolution for the spectrum image (default 150).
        view_x_range: Optional (x_min, x_max) visible wavenumber range from the viewer.
            When set, the PDF plot and X range metadata row use this range instead of
            the full data extent. Defaults to (400.0, 3800.0) when None.
        view_y_range: Optional (y_min, y_max) visible y-axis range from the viewer.
        diagnostic_regions: Runtime-only diagnostic overlays currently visible in the viewer.
        split_xaxis: When True, render the spectrum with a split X-axis at 2000 cm⁻¹
            (hi-wavenumber region left, fingerprint region right). Default True.
        layout: First-page layout, LAYOUT_FULL_BLEED by default. It drops the page
            margins so the plot covers the whole A4 sheet and floats the file/sample
            identity plus the molecular structure into empty space inside the plot.
            LAYOUT_STANDARD is the older layout that keeps the spectrum inside the
            usual 2 cm page margins with nothing drawn on top of it.
    """

    include_structures: bool = True
    include_peak_table: bool = True
    include_metadata: bool = True
    dpi: int = 150
    view_x_range: tuple[float, float] | None = None
    view_y_range: tuple[float, float] | None = None
    diagnostic_regions: tuple[object, ...] = ()
    split_xaxis: bool = True
    layout: str = LAYOUT_FULL_BLEED
    # id(peak) -> (label_x, label_y) in data coordinates, captured from the live
    # viewer so exported labels reproduce the on-screen layout exactly.
    peak_label_placements: dict = None  # type: ignore[assignment]


def _footer(canvas, doc) -> None:  # type: ignore[no-untyped-def]
    """Draw footer on every page — adapts to actual page size."""
    _f, _, _ = _ensure_fonts()
    canvas.saveState()
    canvas.setFont(_f, 8)
    canvas.setFillColor(colors.gray)
    page_w, _page_h = canvas._pagesize
    y = _MARGIN - 0.5 * cm
    canvas.line(_MARGIN, y + 0.35 * cm, page_w - _MARGIN, y + 0.35 * cm)
    canvas.drawString(_MARGIN, y, "IR Spectra Analyzer")
    page_text = f"Page {doc.page}"
    canvas.drawRightString(page_w - _MARGIN, y, page_text)
    canvas.restoreState()


class PDFGenerator:
    """Generates professional PDF analysis reports using ReportLab."""

    def generate(
        self,
        project: Project,
        output_path: Path,
        *,
        options: ReportOptions | None = None,
    ) -> None:
        """Generate a PDF report for the given project.

        Args:
            project: Project with spectrum, peaks, and metadata.
            output_path: Destination PDF file path.
            options: ReportOptions controlling report content. Uses defaults if None.

        Raises:
            ValueError: If the project has no spectrum loaded.
        """
        if options is None:
            options = ReportOptions()
        if project.spectrum is None:
            raise ValueError("Project has no spectrum loaded")

        font_r, font_b, font_o = _ensure_fonts()

        spectrum = project.spectrum
        styles = getSampleStyleSheet()

        title_style = ParagraphStyle(
            "ReportTitle",
            parent=styles["Normal"],
            fontSize=14,
            fontName=font_b,
            spaceAfter=4,
        )
        subtitle_style = ParagraphStyle(
            "ReportSubtitle",
            parent=styles["Normal"],
            fontSize=10,
            fontName=font_r,
            textColor=colors.gray,
            spaceAfter=6,
        )
        key_style = ParagraphStyle(
            "MetaKey",
            parent=styles["Normal"],
            fontSize=9,
            fontName=font_b,
        )
        val_style = ParagraphStyle(
            "MetaVal",
            parent=styles["Normal"],
            fontSize=9,
            fontName=font_r,
        )
        caption_style = ParagraphStyle(
            "Caption",
            parent=styles["Normal"],
            fontSize=8,
            fontName=font_o,
            textColor=colors.gray,
            alignment=TA_CENTER,
        )
        section_style = ParagraphStyle(
            "SectionHeading",
            parent=styles["Normal"],
            fontSize=11,
            fontName=font_b,
            spaceBefore=6,
            spaceAfter=4,
        )
        table_header_style = ParagraphStyle(
            "TableHeader",
            parent=styles["Normal"],
            fontSize=9,
            fontName=font_b,
        )
        table_cell_style = ParagraphStyle(
            "TableCell",
            parent=styles["Normal"],
            fontSize=9,
            fontName=font_r,
        )
        table_cell_right = ParagraphStyle(
            "TableCellRight",
            parent=styles["Normal"],
            fontSize=9,
            fontName=font_r,
            alignment=TA_RIGHT,
        )

        story = []

        # Resolve view range — use what the viewer was showing, or the default 400–3800 window
        _x_min, _x_max = options.view_x_range if options.view_x_range else (400.0, 3800.0)

        # Page 1: full-page spectrum (no header — maximum graph area)
        full_bleed_painter = None
        if options.layout == LAYOUT_FULL_BLEED:
            full_bleed_painter = self._build_full_bleed_first_page(
                project,
                spectrum,
                options,
                x_min=_x_min,
                x_max=_x_max,
                font_bold=font_b,
            )
            # The page is painted entirely by the template callback; the frame
            # only needs to exist so ReportLab emits the page.
            story.append(Spacer(1, 1))
        else:
            self._append_spectrum_section(
                story,
                spectrum.wavenumbers,
                spectrum.intensities,
                project.peaks,
                caption_style,
                dpi=options.dpi,
                y_unit=spectrum.y_unit,
                is_dip_spectrum=spectrum.is_dip_spectrum,
                text_width=_LAND_TEXT_W,
                text_height=_LAND_TEXT_H,
                x_min=_x_min,
                x_max=_x_max,
                y_view_range=options.view_y_range,
                diagnostic_regions=options.diagnostic_regions,
                split_at=2000.0 if options.split_xaxis else None,
                label_placements=options.peak_label_placements,
            )

        # Switch to portrait for subsequent pages, then page break
        story.append(NextPageTemplate("portrait"))
        story.append(PageBreak())

        # Page 2+: header first, then metadata+structure, peak table
        self._append_header_section(
            story,
            project,
            spectrum,
            title_style,
            subtitle_style,
        )

        if options.include_metadata:
            self._append_metadata_and_structure_section(
                story,
                project,
                spectrum,
                key_style,
                val_style,
                options,
            )

        sorted_peaks = [
            row.peak
            for row in build_peak_assignment_rows(
                project.peaks,
                is_dip_spectrum=spectrum.is_dip_spectrum,
            )
        ]
        if options.include_peak_table and sorted_peaks:
            self._append_peak_table_section(
                story,
                sorted_peaks,
                section_style,
                table_header_style,
                table_cell_style,
                table_cell_right,
                is_dip_spectrum=spectrum.is_dip_spectrum,
            )

        # Build document with two page templates
        land_frame = Frame(
            _MARGIN,
            _MARGIN + 0.5 * cm,
            _LAND_TEXT_W,
            _LAND_TEXT_H,
            id="landscape_frame",
            showBoundary=0,
        )
        port_frame = Frame(
            _MARGIN,
            _MARGIN + 0.5 * cm,
            _PORT_TEXT_W,
            _PORT_H - 2 * _MARGIN - 0.5 * cm,
            id="portrait_frame",
            showBoundary=0,
        )

        land_template = PageTemplate(
            id="landscape",
            frames=[land_frame],
            onPage=_footer,
            pagesize=landscape(A4),
        )
        port_template = PageTemplate(
            id="portrait",
            frames=[port_frame],
            onPage=_footer,
            pagesize=A4,
        )

        if full_bleed_painter is not None:
            first_template = PageTemplate(
                id="fullbleed",
                frames=[
                    Frame(
                        0,
                        0,
                        _LAND_W,
                        _LAND_H,
                        id="fullbleed_frame",
                        leftPadding=0,
                        rightPadding=0,
                        topPadding=0,
                        bottomPadding=0,
                        showBoundary=0,
                    )
                ],
                onPage=full_bleed_painter,
                pagesize=landscape(A4),
            )
        else:
            first_template = land_template

        doc = BaseDocTemplate(
            str(output_path),
            pagesize=landscape(A4),
            leftMargin=_MARGIN,
            rightMargin=_MARGIN,
            topMargin=_MARGIN,
            bottomMargin=_MARGIN + 0.5 * cm,
        )
        doc.addPageTemplates([first_template, port_template])
        doc.build(story)

    # ------------------------------------------------------------------
    # Full-bleed first page
    # ------------------------------------------------------------------

    def _build_full_bleed_first_page(
        self,
        project: Project,
        spectrum: Spectrum,
        options: ReportOptions,
        *,
        x_min: float,
        x_max: float,
        font_bold: str,
    ) -> Callable[[Canvas, object], None]:
        """Render the edge-to-edge spectrum page and return its canvas painter.

        The spectrum is rendered at exactly the page size, so nothing is scaled
        down for the identity block or the structure — both float inside the plot
        in whatever empty area the renderer found.
        """
        sample_name, file_name = self._header_identifiers(project, spectrum)
        file_name = self._without_spectrum_suffix(file_name)
        structure_png = self._structure_png_bytes(project, options, trim=True)
        # %T curves leave their gap under the baseline, absorbance above it.
        anchor_bottom = spectrum.is_dip_spectrum

        png_bytes, box = SpectrumRenderer().render_with_annotation_box(
            spectrum.wavenumbers,
            spectrum.intensities,
            project.peaks,
            dpi=max(options.dpi, _FULL_BLEED_MIN_DPI),
            y_unit=spectrum.y_unit,
            is_dip_spectrum=spectrum.is_dip_spectrum,
            figsize=(_LAND_W / 72.0, _LAND_H / 72.0),
            x_min=x_min,
            x_max=x_max,
            y_view_range=options.view_y_range,
            diagnostic_regions=options.diagnostic_regions,
            split_at=2000.0 if options.split_xaxis else None,
            label_placements=options.peak_label_placements,
            annotation_target=self._annotation_target(structure_png),
        )

        def _paint(canvas: Canvas, doc: object) -> None:
            from reportlab.lib.utils import ImageReader  # noqa: PLC0415

            page_w, page_h = canvas._pagesize
            canvas.drawImage(
                ImageReader(io.BytesIO(png_bytes)),
                0,
                0,
                width=page_w,
                height=page_h,
                preserveAspectRatio=False,
                anchor="sw",
            )
            if box is None:
                return
            self._draw_annotation_block(
                canvas,
                x=box[0] * page_w,
                y=box[1] * page_h,
                width=(box[2] - box[0]) * page_w,
                height=(box[3] - box[1]) * page_h,
                sample_name=sample_name,
                file_name=file_name,
                structure_png=structure_png,
                anchor_bottom=anchor_bottom,
                font_bold=font_bold,
            )

        return _paint

    def _draw_annotation_block(
        self,
        canvas: Canvas,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        sample_name: str,
        file_name: str,
        structure_png: bytes | None,
        anchor_bottom: bool,
        font_bold: str,
    ) -> None:
        """Draw the identity lines above the structure inside a free area of the plot.

        The frame is sized to the content it ends up holding rather than to the
        whole free area, so a molecule that is much wider than tall does not sit in
        a half-empty box.
        """
        pad = 8.0
        avail_w = width - 2 * pad
        avail_h = height - 2 * pad
        if avail_w <= 0 or avail_h <= 0:
            return

        lines = self._identity_lines(sample_name, file_name)
        text_h, text_w, text_size = self._identity_metrics(lines, avail_w, font_bold)

        structure_w = structure_h = 0.0
        if structure_png is not None:
            img_w, img_h = self._png_size(structure_png)
            aspect = (img_h / img_w) if img_w else 1.0
            structure_max_h = avail_h - text_h - pad
            if structure_max_h > 24.0 and aspect > 0:
                structure_w = min(avail_w, structure_max_h / aspect)
                structure_h = structure_w * aspect
            else:
                structure_png = None

        content_w = max(structure_w, text_w)
        content_h = text_h + (pad + structure_h if structure_png is not None else 0.0)
        frame_w = content_w + 2 * pad
        frame_h = content_h + 2 * pad
        # Sit on the edge of the gap the renderer picked, so the block lands in
        # the corner of the axes instead of floating in the middle of the space.
        frame_y = y if anchor_bottom else y + height - frame_h

        canvas.saveState()
        canvas.setFillColor(colors.white)
        canvas.setStrokeColor(colors.HexColor("#BFBFBF"))
        canvas.setLineWidth(0.5)
        canvas.roundRect(x, frame_y, frame_w, frame_h, 4, stroke=1, fill=1)

        self._draw_identity_lines(
            canvas,
            lines,
            x=x + pad,
            top=frame_y + frame_h - pad,
            max_width=text_w,
            size=text_size,
            font_name=font_bold,
        )
        if structure_png is not None:
            self._draw_structure(
                canvas,
                structure_png,
                x=x + pad,
                y=frame_y + pad,
                max_width=content_w,
                max_height=structure_h,
            )
        canvas.restoreState()

    # Width the floating block asks for, as a fraction of the page, plus the
    # vertical allowance for the two identity lines and the frame padding.
    _BLOCK_TARGET_WIDTH = 0.26
    _BLOCK_TEXT_ALLOWANCE = 40.0

    @classmethod
    def _annotation_target(cls, structure_png: bytes | None) -> tuple[float, float]:
        """Ask the renderer for a gap shaped like the block we are going to draw."""
        width_pt = _LAND_W * cls._BLOCK_TARGET_WIDTH
        if structure_png is None:
            return (width_pt * 0.8 / _LAND_W, cls._BLOCK_TEXT_ALLOWANCE / _LAND_H)

        img_w, img_h = cls._png_size(structure_png)
        aspect = img_h / img_w if img_w else 1.0
        height_pt = width_pt * aspect + cls._BLOCK_TEXT_ALLOWANCE
        return (width_pt / _LAND_W, min(max(height_pt / _LAND_H, 0.08), 0.5))

    @staticmethod
    def _png_size(png_bytes: bytes) -> tuple[int, int]:
        """Read pixel dimensions straight from the PNG IHDR chunk."""
        try:
            width, height = struct.unpack(">II", png_bytes[16:24])
        except Exception:  # noqa: BLE001
            return (760, 760)
        return (int(width) or 760, int(height) or 760)

    def _draw_structure(
        self,
        canvas: Canvas,
        png_bytes: bytes,
        *,
        x: float,
        y: float,
        max_width: float,
        max_height: float,
    ) -> None:
        """Draw the molecule centred in the given area, keeping its aspect ratio."""
        from reportlab.lib.utils import ImageReader  # noqa: PLC0415

        img_w, img_h = self._png_size(png_bytes)
        scale = min(max_width / img_w, max_height / img_h)
        draw_w = img_w * scale
        draw_h = img_h * scale
        canvas.drawImage(
            ImageReader(io.BytesIO(png_bytes)),
            x + (max_width - draw_w) / 2.0,
            y + (max_height - draw_h) / 2.0,
            width=draw_w,
            height=draw_h,
            preserveAspectRatio=True,
            mask="auto",
        )

    # Identity lines: file identifier on top, sample designation underneath —
    # the same two values the portrait pages print in their header, drawn in one
    # uniform style so neither reads as more important than the other.
    _IDENTITY_FONT_SIZE = 11.5
    _MIN_FONT_SIZE = 6.0

    @staticmethod
    def _identity_lines(sample_name: str, file_name: str) -> list[str]:
        """Return the identity lines in display order, skipping empty values."""
        return [line for line in (file_name, sample_name) if line]

    @staticmethod
    def _without_spectrum_suffix(file_name: str) -> str:
        """Drop a known spectrum-file extension, leaving any other dots alone."""
        stem, dot, suffix = file_name.rpartition(".")
        if dot and f".{suffix.lower()}" in _IDENTITY_STRIPPED_SUFFIXES:
            return stem
        return file_name

    @classmethod
    def _identity_metrics(
        cls, lines: list[str], max_width: float, font_name: str
    ) -> tuple[float, float, float]:
        """Return (total height, widest line, shared font size).

        One size is fitted for every line, so a long file name shrinks the sample
        designation with it rather than the two drifting apart.
        """
        if not lines:
            return (0.0, 0.0, cls._IDENTITY_FONT_SIZE)

        size = min(
            cls._fit_font_size(line, font_name, cls._IDENTITY_FONT_SIZE, max_width)
            for line in lines
        )
        height = len(lines) * size * 1.25 + (len(lines) - 1) * 2.0
        widest = max(pdfmetrics.stringWidth(line, font_name, size) for line in lines)
        return (height, min(widest, max_width), size)

    @classmethod
    def _draw_identity_lines(
        cls,
        canvas: Canvas,
        lines: list[str],
        *,
        x: float,
        top: float,
        max_width: float,
        size: float,
        font_name: str,
    ) -> None:
        """Draw the identity lines from `top` downwards in one uniform style."""
        canvas.setFont(font_name, size)
        canvas.setFillColor(colors.black)
        cursor = top
        for line in lines:
            cursor -= size
            canvas.drawString(x, cursor, cls._clip_text(line, font_name, size, max_width))
            cursor -= size * 0.25 + 2.0

    @classmethod
    def _fit_font_size(cls, text: str, font_name: str, max_size: float, max_width: float) -> float:
        """Largest size (down to _MIN_FONT_SIZE) at which the text still fits."""
        size = max_size
        while size > cls._MIN_FONT_SIZE and pdfmetrics.stringWidth(text, font_name, size) > (
            max_width
        ):
            size -= 0.5
        return size

    @staticmethod
    def _clip_text(text: str, font_name: str, size: float, max_width: float) -> str:
        """Truncate with an ellipsis when even the smallest size overflows."""
        if pdfmetrics.stringWidth(text, font_name, size) <= max_width:
            return text
        clipped = text
        while clipped and pdfmetrics.stringWidth(clipped + "…", font_name, size) > max_width:
            clipped = clipped[:-1]
        return clipped + "…" if clipped else ""

    @staticmethod
    def _header_identifiers(project: Project, spectrum: Spectrum) -> tuple[str, str]:
        """Return (sample designation, file identifier) — the two header values."""
        project_metadata = getattr(project, "metadata", None)
        file_name = (
            project_metadata.file_name if project_metadata and project_metadata.file_name else ""
        )
        sample_name = (
            project_metadata.title
            if project_metadata and project_metadata.title
            else (spectrum.title or "")
        )
        return (sample_name or "", file_name or project.name)

    @classmethod
    def _structure_png_bytes(
        cls, project: Project, options: ReportOptions, *, trim: bool = False
    ) -> bytes | None:
        """Render the project's molecule to PNG bytes, or None when there is none.

        Args:
            trim: Crop the empty border a molecule renderer leaves around the
                drawing, so the image fills whatever box it is given.
        """
        from chemistry.structure_renderer import render_to_svg, svg_to_png_bytes  # noqa: PLC0415

        mol_block = getattr(project, "mol_block", "")
        if not options.include_structures:
            return None
        if not (project.smiles or mol_block or project.structure_image):
            return None

        png_bytes: bytes | None = None
        if project.smiles or mol_block:
            svg = render_to_svg(smiles=project.smiles, mol_block=mol_block, size=(380, 380))
            if svg:
                png_bytes = svg_to_png_bytes(svg, 760, 760)
        if not png_bytes and project.structure_image:
            png_bytes = project.structure_image
        if png_bytes and trim:
            png_bytes = cls._trim_png_border(png_bytes)
        return png_bytes

    @staticmethod
    def _trim_png_border(png_bytes: bytes) -> bytes:
        """Crop transparent (or white) padding around the drawing.

        Returns the input unchanged if anything goes wrong — an untrimmed
        structure is a cosmetic loss, a failed export is not.
        """
        try:
            from PIL import Image as PILImage  # noqa: PLC0415

            with PILImage.open(io.BytesIO(png_bytes)) as image:
                rgba = image.convert("RGBA")
                bbox = rgba.getchannel("A").getbbox()
                if bbox is None or bbox == (0, 0, rgba.width, rgba.height):
                    # Opaque render — fall back to the bounds of non-white pixels.
                    grey = rgba.convert("L").point(lambda value: 255 - value)
                    bbox = grey.getbbox() or bbox
                if bbox is None:
                    return png_bytes
                margin = 4
                cropped = rgba.crop(
                    (
                        max(bbox[0] - margin, 0),
                        max(bbox[1] - margin, 0),
                        min(bbox[2] + margin, rgba.width),
                        min(bbox[3] + margin, rgba.height),
                    )
                )
                buffer = io.BytesIO()
                cropped.save(buffer, format="PNG")
                return buffer.getvalue()
        except Exception:  # noqa: BLE001
            return png_bytes

    def _append_header_section(
        self,
        story: list,
        project: Project,
        spectrum,
        title_style: ParagraphStyle,
        subtitle_style: ParagraphStyle,
    ) -> None:
        """Append the report header section.

        Left column: file identifier (bold, large).
        Right column: sample designation from the spectrum title (bold, right-aligned).
        """
        title_right_style = ParagraphStyle(
            "ReportTitleRight",
            parent=title_style,
            alignment=TA_RIGHT,
            spaceAfter=0,
        )
        spectrum_title, file_name = self._header_identifiers(project, spectrum)
        left_para = Paragraph(file_name, title_style)
        right_para = Paragraph(spectrum_title, title_right_style)
        header_row = Table(
            [[left_para, right_para]],
            colWidths=[_PORT_TEXT_W * 0.6, _PORT_TEXT_W * 0.4],
        )
        header_row.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )
        story.append(header_row)
        story.append(HRFlowable(width="100%", thickness=1, color=colors.black, spaceAfter=6))

    def _append_spectrum_section(
        self,
        story: list,
        wavenumbers,
        intensities,
        peaks,
        caption_style: ParagraphStyle,
        *,
        dpi: int,
        y_unit,
        is_dip_spectrum: bool = False,
        text_width: float,
        text_height: float | None = None,
        x_min: float = 400.0,
        x_max: float = 3800.0,
        y_view_range: tuple[float, float] | None = None,
        diagnostic_regions: tuple[object, ...] = (),
        split_at: float | None = 2000.0,
        label_placements: dict | None = None,
    ) -> None:
        """Append the rendered spectrum image section."""
        # Compute figsize in inches from the available frame dimensions.
        # ReportLab Frame has 6pt default padding on each side, so usable area
        # is text_width/text_height minus 12pt (left+right or top+bottom).
        _frame_pad = 12.0  # 6pt × 2 sides
        if text_height is not None:
            # Full-page mode: fill the usable frame area
            fig_w_in = (text_width - _frame_pad) / 72.0
            fig_h_in = (text_height - _frame_pad) / 72.0
        else:
            fig_w_in = _RENDERER_FIG_W
            fig_h_in = _RENDERER_FIG_H

        png_bytes = SpectrumRenderer().render_to_bytes(
            wavenumbers,
            intensities,
            peaks,
            dpi=dpi,
            y_unit=y_unit,
            is_dip_spectrum=is_dip_spectrum,
            figsize=(fig_w_in, fig_h_in),
            x_min=x_min,
            x_max=x_max,
            y_view_range=y_view_range,
            diagnostic_regions=diagnostic_regions,
            split_at=split_at,
            label_placements=label_placements,
        )
        img_buf = io.BytesIO(png_bytes)

        # Scale image to fill the usable frame area, preserving exact figsize aspect ratio
        aspect = fig_h_in / fig_w_in
        usable_w = text_width - _frame_pad if text_height is not None else text_width
        usable_h = text_height - _frame_pad if text_height is not None else None
        embed_w = usable_w
        embed_h = embed_w * aspect
        if usable_h is not None and embed_h > usable_h:
            embed_h = usable_h
            embed_w = embed_h / aspect

        img = Image(img_buf, width=embed_w, height=embed_h)
        story.append(img)

        if text_height is None:
            # Caption only when not filling a full page
            story.append(Paragraph("Figure 1 \u2014 IR spectrum", caption_style))
            story.append(Spacer(1, 0.4 * cm))

    def _append_peak_table_section(
        self,
        story: list,
        sorted_peaks,
        section_style: ParagraphStyle,
        table_header_style: ParagraphStyle,
        table_cell_style: ParagraphStyle,
        table_cell_right: ParagraphStyle,
        *,
        is_dip_spectrum: bool = False,
    ) -> None:
        """Append the peak assignments table."""
        intensity_labels = classify_peak_intensities(
            sorted_peaks,
            is_dip_spectrum=is_dip_spectrum,
        )

        # Narrow numeric columns leave the assignment text as much width as
        # possible, so multi-vibration assignments stay on one line.
        col_pos_w = 1.9 * cm
        col_cls_w = 1.15 * cm

        def _make_header() -> list:
            return [
                Paragraph("Position (cm\u207b\u00b9)", table_header_style),
                Paragraph("Int.", table_header_style),
                Paragraph("Assignment", table_header_style),
            ]

        data_rows = []
        for peak in sorted_peaks:
            cls_str = intensity_labels.get(id(peak), "")
            data_rows.append(
                [
                    Paragraph(str(int(round(peak.position))), table_cell_right),
                    Paragraph(cls_str, table_cell_right),
                    Paragraph(peak_assignment_text(peak), table_cell_style),
                ]
            )

        story.append(Paragraph("Peak assignments", section_style))

        # Short lists read best as a single full-width column.
        max_rows_single = 14
        if len(data_rows) <= max_rows_single:
            table = Table(
                [_make_header()] + data_rows,
                colWidths=[col_pos_w, col_cls_w, _PORT_TEXT_W - col_pos_w - col_cls_w],
            )
            ts = TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8E8E8")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ]
            )
            for i in range(len(data_rows)):
                if i % 2 == 1:
                    ts.add("BACKGROUND", (0, i + 1), (-1, i + 1), colors.HexColor("#F5F5F5"))
            table.setStyle(ts)
            story.append(table)
            return

        # Longer lists use a single two-column table that flows directly under
        # the metadata/structure (so both stay on the same page when they fit)
        # and splits across pages only when necessary, repeating the header.
        # The first half of the rows fills the left column, the second half the
        # right, so each column stays sorted by wavenumber.
        gap_w = 0.4 * cm
        half_assign_w = (_PORT_TEXT_W - 2 * (col_pos_w + col_cls_w) - gap_w) / 2.0
        n = len(data_rows)
        n_rows = -(-n // 2)  # ceil → left column length

        wide_data = [_make_header() + [""] + _make_header()]
        for i in range(n_rows):
            left = data_rows[i]
            right_idx = i + n_rows
            right = data_rows[right_idx] if right_idx < n else ["", "", ""]
            wide_data.append([*left, "", *right])

        wide_table = Table(
            wide_data,
            colWidths=[
                col_pos_w,
                col_cls_w,
                half_assign_w,
                gap_w,
                col_pos_w,
                col_cls_w,
                half_assign_w,
            ],
            repeatRows=1,
        )
        ts = TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                # Header shading on the two 3-column groups (skip the gap column).
                ("BACKGROUND", (0, 0), (2, 0), colors.HexColor("#E8E8E8")),
                ("BACKGROUND", (4, 0), (6, 0), colors.HexColor("#E8E8E8")),
                # Grid on each column group only, so the gap column has no borders.
                ("GRID", (0, 0), (2, -1), 0.25, colors.lightgrey),
                ("GRID", (4, 0), (6, -1), 0.25, colors.lightgrey),
                ("LEFTPADDING", (3, 0), (3, -1), 0),
                ("RIGHTPADDING", (3, 0), (3, -1), 0),
            ]
        )
        for i in range(n_rows):
            if i % 2 == 1:
                ts.add("BACKGROUND", (0, i + 1), (2, i + 1), colors.HexColor("#F5F5F5"))
                ts.add("BACKGROUND", (4, i + 1), (6, i + 1), colors.HexColor("#F5F5F5"))
        wide_table.setStyle(ts)
        story.append(wide_table)

    def _append_metadata_and_structure_section(
        self,
        story: list,
        project: Project,
        spectrum,
        key_style: ParagraphStyle,
        val_style: ParagraphStyle,
        options: ReportOptions,
    ) -> None:
        """Metadata table on the left, molecule structure image on the right."""
        # ── Build metadata rows ──────────────────────────────────────────────
        project_metadata = getattr(project, "metadata", None)
        meta_rows: list = []

        def _add_row(key: str, value: str | None) -> None:
            if value:
                meta_rows.append([Paragraph(key, key_style), Paragraph(value, val_style)])

        # The sample designation is the spectrum title — the same value the
        # header prints top-right.
        sample_name, file_name = self._header_identifiers(project, spectrum)
        client = (
            project_metadata.extra.get("omnic_client")
            if project_metadata and project_metadata.extra
            else None
        )
        order = (
            project_metadata.extra.get("omnic_order")
            if project_metadata and project_metadata.extra
            else None
        )
        acquired_at = project_metadata.acquired_at if project_metadata else spectrum.acquired_at
        resolution = (
            project_metadata.resolution
            if project_metadata and project_metadata.resolution is not None
            else spectrum.extra_metadata.get("resolution_cm")
        )
        instrument = (
            project_metadata.instrument if project_metadata and project_metadata.instrument else ""
        )
        comment = (
            project_metadata.comments if project_metadata and project_metadata.comments else ""
        )

        _add_row("Sample", sample_name)
        _add_row("File", file_name)
        _add_row("Operator", project_metadata.operator if project_metadata else None)
        _add_row(
            "Instrument", instrument or str(spectrum.extra_metadata.get("instrument_serial", ""))
        )
        _add_row("Client", client or spectrum.extra_metadata.get("omnic_custom_info_2"))
        _add_row("Order", order or spectrum.extra_metadata.get("omnic_custom_info_1"))
        if acquired_at:
            _add_row("Acquired", acquired_at.strftime("%Y-%m-%d %H:%M"))
        if resolution is not None:
            _add_row("Resolution", f"{resolution:.3f} cm\u207b\u00b9")
        if comment or spectrum.extra_metadata.get("omnic_comment"):
            _add_row("Comment", comment or spectrum.extra_metadata.get("omnic_comment"))
        _add_row("Y unit", spectrum.y_unit.value)
        _x_lo, _x_hi = options.view_x_range if options.view_x_range else (400.0, 3800.0)
        _add_row(
            "X range",
            f"{max(_x_lo, _x_hi):.0f} \u2013 {min(_x_lo, _x_hi):.0f} cm\u207b\u00b9",
        )

        # ── Try to render molecule structure (right column) ──────────────────
        png_bytes = self._structure_png_bytes(project, options)

        # ── Decide layout ────────────────────────────────────────────────────
        if png_bytes:
            left_col_w = _PORT_TEXT_W * 0.58
            right_col_w = _PORT_TEXT_W - left_col_w
        else:
            left_col_w = _PORT_TEXT_W
            right_col_w = 0.0

        key_col_w = 4.0 * cm
        val_col_w = left_col_w - key_col_w

        if meta_rows:
            meta_subtable = Table(meta_rows, colWidths=[key_col_w, val_col_w])
            meta_subtable.setStyle(
                TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("TOPPADDING", (0, 0), (-1, -1), 2),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                        ("LEFTPADDING", (0, 0), (-1, -1), 0),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ]
                )
            )
        else:
            meta_subtable = Spacer(left_col_w, 1)

        if png_bytes:
            img_w_px, img_h_px = self._png_size(png_bytes)

            max_w = right_col_w - 0.3 * cm  # small inset from column edge
            max_h = 7.0 * cm
            if img_w_px > 0 and img_h_px > 0:
                scale = min(max_w / img_w_px, max_h / img_h_px)
                embed_w = img_w_px * scale
                embed_h = img_h_px * scale
            else:
                embed_w = embed_h = max_w

            right_cell: object = Image(io.BytesIO(png_bytes), width=embed_w, height=embed_h)

            two_col = Table(
                [[meta_subtable, right_cell]],
                colWidths=[left_col_w, right_col_w],
            )
            two_col.setStyle(
                TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("ALIGN", (1, 0), (1, 0), "CENTER"),
                        ("TOPPADDING", (0, 0), (-1, -1), 0),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                        ("LEFTPADDING", (0, 0), (-1, -1), 0),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ]
                )
            )
            story.append(two_col)
        else:
            story.append(meta_subtable)

        story.append(Spacer(1, 0.4 * cm))
