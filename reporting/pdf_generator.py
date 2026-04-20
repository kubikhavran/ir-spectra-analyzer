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

from core.peak_assignments import (
    build_peak_assignment_rows,
    classify_peak_intensities,
    peak_assignment_text,
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
    """

    include_structures: bool = True
    include_peak_table: bool = True
    include_metadata: bool = True
    dpi: int = 150
    view_x_range: tuple[float, float] | None = None


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
        """Append the report header section.

        Left column: project/sample name (bold, large).
        Right column: spectrum title / internal lab code (bold, right-aligned).
        """
        title_right_style = ParagraphStyle(
            "ReportTitleRight",
            parent=title_style,
            alignment=TA_RIGHT,
            spaceAfter=0,
        )
        left_para = Paragraph(project.name, title_style)
        right_para = Paragraph(spectrum.title or "", title_right_style)
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
        story.append(Paragraph("Peak assignments", section_style))

        intensity_labels = classify_peak_intensities(
            sorted_peaks,
            is_dip_spectrum=is_dip_spectrum,
        )

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
                    Paragraph(peak_assignment_text(peak), table_cell_style),
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
        from chemistry.structure_renderer import render_to_svg, svg_to_png_bytes  # noqa: PLC0415

        # ── Build metadata rows ──────────────────────────────────────────────
        meta_rows: list = []

        def _add_row(key: str, value: str | None) -> None:
            if value:
                meta_rows.append([Paragraph(key, key_style), Paragraph(value, val_style)])

        _add_row("Sample", project.name)
        _add_row("Client", spectrum.extra_metadata.get("omnic_custom_info_2"))
        _add_row("Order", spectrum.extra_metadata.get("omnic_custom_info_1"))
        if spectrum.acquired_at:
            _add_row("Acquired", spectrum.acquired_at.strftime("%Y-%m-%d %H:%M"))
        resolution = spectrum.extra_metadata.get("resolution_cm")
        if resolution is not None:
            _add_row("Resolution", f"{resolution:.3f} cm\u207b\u00b9")
        omnic_comment = spectrum.extra_metadata.get("omnic_comment")
        if omnic_comment:
            _add_row("Comment", omnic_comment)
        _add_row("Y unit", spectrum.y_unit.value)
        _x_lo, _x_hi = options.view_x_range if options.view_x_range else (400.0, 3800.0)
        _add_row(
            "X range",
            f"{max(_x_lo, _x_hi):.0f} \u2013 {min(_x_lo, _x_hi):.0f} cm\u207b\u00b9",
        )

        # ── Try to render molecule structure (right column) ──────────────────
        mol_block = getattr(project, "mol_block", "")
        has_structure = options.include_structures and (
            project.smiles or mol_block or project.structure_image
        )

        png_bytes: bytes | None = None
        if has_structure:
            if project.smiles or mol_block:
                svg = render_to_svg(
                    smiles=project.smiles,
                    mol_block=mol_block,
                    size=(380, 380),
                )
                if svg:
                    png_bytes = svg_to_png_bytes(svg, 760, 760)
            if not png_bytes and project.structure_image:
                png_bytes = project.structure_image

        # ── Decide layout ────────────────────────────────────────────────────
        if has_structure and png_bytes:
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

        if has_structure and png_bytes:
            try:
                img_w_px, img_h_px = struct.unpack(">II", png_bytes[16:24])
            except Exception:  # noqa: BLE001
                img_w_px = img_h_px = 760

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
