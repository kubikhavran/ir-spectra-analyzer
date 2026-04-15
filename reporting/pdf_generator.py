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
from dataclasses import dataclass
from pathlib import Path

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

from core.project import Project
from reporting.spectrum_renderer import SpectrumRenderer

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


# Matplotlib figsize used in SpectrumRenderer — needed to preserve aspect ratio
_RENDERER_FIG_W = 7.5
_RENDERER_FIG_H = 3.2
_FIG_ASPECT = _RENDERER_FIG_H / _RENDERER_FIG_W  # height / width ratio

_MARGIN = 2 * cm

# Landscape A4 (page 1 — spectrum)
_LAND_W, _LAND_H = landscape(A4)
_LAND_TEXT_W = _LAND_W - 2 * _MARGIN
_LAND_TEXT_H = _LAND_H - 2 * _MARGIN - 0.5 * cm  # leave room for footer

# Portrait A4 (pages 2+)
_PORT_W, _PORT_H = A4
_PORT_TEXT_W = _PORT_W - 2 * _MARGIN


@dataclass
class ReportOptions:
    """Options controlling what sections appear in the PDF report.

    Attributes:
        include_structures: If True, include molecular structure images for peaks with SMILES.
        include_peak_table: If True, include the peak assignments table.
        include_metadata: If True, include the project/spectrum metadata table.
        dpi: Resolution for the spectrum image (default 150).
    """

    include_structures: bool = True
    include_peak_table: bool = True
    include_metadata: bool = True
    dpi: int = 150


def _classify_peak_intensities(peaks: list, is_dip_spectrum: bool) -> dict[int, str]:
    """Return a {id(peak): label} mapping where label is 'w', 'm', 's', or 'vs'.

    Classification is relative to the strongest absorption in the set:
    - vs : >= 90 % of max absorption depth
    - s  : 70–90 %
    - m  : 40–70 %
    - w  :  0–40 %

    For %Transmittance (dip) spectra the absorption depth is approximated as
    (100 - intensity); for Absorbance spectra the intensity value is used directly.
    """
    if not peaks:
        return {}

    if is_dip_spectrum:
        depths = {id(p): max(0.0, 100.0 - p.intensity) for p in peaks}
    else:
        depths = {id(p): max(0.0, p.intensity) for p in peaks}

    max_depth = max(depths.values()) or 1.0

    result: dict[int, str] = {}
    for peak in peaks:
        rel = depths[id(peak)] / max_depth * 100.0
        if rel >= 90.0:
            result[id(peak)] = "vs"
        elif rel >= 70.0:
            result[id(peak)] = "s"
        elif rel >= 40.0:
            result[id(peak)] = "m"
        else:
            result[id(peak)] = "w"
    return result


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

        # Page 1: title + spectrum on landscape page
        self._append_header_section(
            story,
            project,
            spectrum,
            title_style,
            subtitle_style,
        )

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
        )

        # Switch to portrait for subsequent pages, then page break
        story.append(NextPageTemplate("portrait"))
        story.append(PageBreak())

        # Page 2+: metadata, peak table, structures
        if options.include_metadata:
            self._append_metadata_section(
                story,
                project,
                spectrum,
                key_style,
                val_style,
            )

        sorted_peaks = sorted(project.peaks, key=lambda p: p.position, reverse=True)
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
        if options.include_structures and (project.smiles or project.structure_image):
            self._append_structure_section(
                story,
                project,
                section_style,
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

        doc = BaseDocTemplate(
            str(output_path),
            pagesize=landscape(A4),
            leftMargin=_MARGIN,
            rightMargin=_MARGIN,
            topMargin=_MARGIN,
            bottomMargin=_MARGIN + 0.5 * cm,
        )
        doc.addPageTemplates([land_template, port_template])
        doc.build(story)

    def _append_header_section(
        self,
        story: list,
        project: Project,
        spectrum,
        title_style: ParagraphStyle,
        subtitle_style: ParagraphStyle,
    ) -> None:
        """Append the report header section."""
        filename = spectrum.source_path.name if spectrum.source_path else "—"
        story.append(Paragraph(project.name, title_style))
        story.append(Paragraph(filename, subtitle_style))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.black, spaceAfter=6))

    def _append_metadata_section(
        self,
        story: list,
        project: Project,
        spectrum,
        key_style: ParagraphStyle,
        val_style: ParagraphStyle,
    ) -> None:
        """Append the metadata table section if rows are available."""
        meta_rows = []

        def _add_row(key: str, value: str | None) -> None:
            if value:
                meta_rows.append([Paragraph(key, key_style), Paragraph(value, val_style)])

        _add_row("Sample", project.name)
        if spectrum.source_path:
            _add_row("File", spectrum.source_path.name)
        if spectrum.acquired_at:
            _add_row("Acquired", spectrum.acquired_at.strftime("%Y-%m-%d %H:%M"))
        serial = spectrum.extra_metadata.get("instrument_serial")
        if serial:
            _add_row("Instrument S/N", str(serial))
        resolution = spectrum.extra_metadata.get("resolution_cm")
        if resolution is not None:
            _add_row("Resolution", f"{resolution:.3f} cm\u207b\u00b9")
        _add_row("Y unit", spectrum.y_unit.value)
        _add_row(
            "X range",
            f"{spectrum.wavenumbers[0]:.1f} \u2013 {spectrum.wavenumbers[-1]:.1f} cm\u207b\u00b9",
        )
        _add_row("Points", str(spectrum.n_points))

        if not meta_rows:
            return

        key_col_w = 4 * cm
        val_col_w = _PORT_TEXT_W - key_col_w
        meta_table = Table(meta_rows, colWidths=[key_col_w, val_col_w])
        meta_table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 2),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ]
            )
        )
        story.append(meta_table)
        story.append(Spacer(1, 0.3 * cm))

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
    ) -> None:
        """Append the rendered spectrum image section."""
        png_bytes = SpectrumRenderer().render_to_bytes(
            wavenumbers,
            intensities,
            peaks,
            dpi=dpi,
            y_unit=y_unit,
            is_dip_spectrum=is_dip_spectrum,
        )
        img_buf = io.BytesIO(png_bytes)
        # Preserve the natural aspect ratio of the Matplotlib figure
        img_height = text_width * _FIG_ASPECT
        img = Image(img_buf, width=text_width, height=img_height)
        story.append(img)
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
        story.append(Paragraph("Peak assignments", section_style))

        intensity_labels = _classify_peak_intensities(sorted_peaks, is_dip_spectrum)

        col_pos_w = 2.5 * cm
        col_int_w = 2.5 * cm
        col_cls_w = 1.5 * cm
        col_assign_w = _PORT_TEXT_W - col_pos_w - col_int_w - col_cls_w

        header_row = [
            Paragraph("Position (cm\u207b\u00b9)", table_header_style),
            Paragraph("Intensity", table_header_style),
            Paragraph("Int.", table_header_style),
            Paragraph("Assignment", table_header_style),
        ]

        data_rows = []
        for peak in sorted_peaks:
            cls_str = intensity_labels.get(id(peak), "")
            data_rows.append(
                [
                    Paragraph(str(int(round(peak.position))), table_cell_right),
                    Paragraph(f"{peak.intensity:.4f}", table_cell_right),
                    Paragraph(cls_str, table_cell_right),
                    Paragraph(peak.display_label, table_cell_style),
                ]
            )

        table_data = [header_row] + data_rows
        peaks_table = Table(
            table_data,
            colWidths=[col_pos_w, col_int_w, col_cls_w, col_assign_w],
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
        for i, _ in enumerate(data_rows):
            row_idx = i + 1
            if i % 2 == 1:
                ts.add("BACKGROUND", (0, row_idx), (-1, row_idx), colors.HexColor("#F5F5F5"))
        peaks_table.setStyle(ts)
        story.append(peaks_table)

    def _append_structure_section(
        self,
        story: list,
        project: Project,
        section_style: ParagraphStyle,
    ) -> None:
        """Append a single proposed molecular structure section."""
        png_bytes: bytes | None = None

        # Prefer stored image bytes (works without RDKit)
        if project.structure_image:
            png_bytes = project.structure_image
        elif project.smiles:
            from chemistry.structure_renderer import render_smiles_to_png  # noqa: PLC0415

            png_bytes = render_smiles_to_png(project.smiles, size=(300, 300))

        if not png_bytes:
            return

        img_size = 8 * cm
        mol_img = Image(io.BytesIO(png_bytes), width=img_size, height=img_size)

        story.append(Spacer(1, 0.4 * cm))
        story.append(Paragraph("Proposed Molecular Structure", section_style))
        story.append(mol_img)
