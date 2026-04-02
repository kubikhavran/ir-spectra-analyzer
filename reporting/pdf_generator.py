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

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from chemistry.structure_renderer import render_smiles_to_png
from core.project import Project
from reporting.spectrum_renderer import SpectrumRenderer


@dataclass
class ReportOptions:
    """Options controlling what sections appear in the PDF report.

    Attributes:
        include_structures: If True, include molecular structure images for peaks with SMILES.
        dpi: Resolution for the spectrum image (default 150).
    """

    include_structures: bool = True
    dpi: int = 150


_PAGE_W, _PAGE_H = A4
_MARGIN = 2 * cm
_TEXT_W = _PAGE_W - 2 * _MARGIN


def _footer(canvas, doc) -> None:  # type: ignore[no-untyped-def]
    """Draw footer on every page."""
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.gray)
    y = _MARGIN - 0.5 * cm
    canvas.line(_MARGIN, y + 0.35 * cm, _PAGE_W - _MARGIN, y + 0.35 * cm)
    canvas.drawString(_MARGIN, y, "IR Spectra Analyzer")
    page_text = f"Page {doc.page}"
    canvas.drawRightString(_PAGE_W - _MARGIN, y, page_text)
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

        spectrum = project.spectrum
        styles = getSampleStyleSheet()

        title_style = ParagraphStyle(
            "ReportTitle",
            parent=styles["Normal"],
            fontSize=14,
            fontName="Helvetica-Bold",
            spaceAfter=4,
        )
        subtitle_style = ParagraphStyle(
            "ReportSubtitle",
            parent=styles["Normal"],
            fontSize=10,
            textColor=colors.gray,
            spaceAfter=6,
        )
        key_style = ParagraphStyle(
            "MetaKey",
            parent=styles["Normal"],
            fontSize=9,
            fontName="Helvetica-Bold",
        )
        val_style = ParagraphStyle(
            "MetaVal",
            parent=styles["Normal"],
            fontSize=9,
        )
        caption_style = ParagraphStyle(
            "Caption",
            parent=styles["Normal"],
            fontSize=8,
            fontName="Helvetica-Oblique",
            textColor=colors.gray,
            alignment=TA_CENTER,
        )
        section_style = ParagraphStyle(
            "SectionHeading",
            parent=styles["Normal"],
            fontSize=11,
            fontName="Helvetica-Bold",
            spaceBefore=6,
            spaceAfter=4,
        )
        table_header_style = ParagraphStyle(
            "TableHeader",
            parent=styles["Normal"],
            fontSize=9,
            fontName="Helvetica-Bold",
        )
        table_cell_style = ParagraphStyle(
            "TableCell",
            parent=styles["Normal"],
            fontSize=9,
        )
        table_cell_right = ParagraphStyle(
            "TableCellRight",
            parent=styles["Normal"],
            fontSize=9,
            alignment=TA_RIGHT,
        )

        story = []

        # --- 1. Header block ---
        filename = spectrum.source_path.name if spectrum.source_path else "—"
        story.append(Paragraph(project.name, title_style))
        story.append(Paragraph(filename, subtitle_style))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.black, spaceAfter=6))

        # --- 2. Metadata table ---
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

        if meta_rows:
            key_col_w = 4 * cm
            val_col_w = _TEXT_W - key_col_w
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

        # --- 3. Spectrum image ---
        png_bytes = SpectrumRenderer().render_to_bytes(
            spectrum.wavenumbers,
            spectrum.intensities,
            project.peaks,
            dpi=150,
            y_unit=spectrum.y_unit,
        )
        img_buf = io.BytesIO(png_bytes)
        img_height = _TEXT_W * (7 / 16)
        img = Image(img_buf, width=_TEXT_W, height=img_height)
        story.append(img)
        story.append(Paragraph("Figure 1 \u2014 IR spectrum", caption_style))
        story.append(Spacer(1, 0.4 * cm))

        # --- 4. Peaks table ---
        if project.peaks:
            story.append(Paragraph("Peak assignments", section_style))

            col_pos_w = 2.5 * cm
            col_int_w = 2.5 * cm
            col_fwhm_w = 2.5 * cm
            col_assign_w = _TEXT_W - col_pos_w - col_int_w - col_fwhm_w

            header_row = [
                Paragraph("Position (cm\u207b\u00b9)", table_header_style),
                Paragraph("Intensity", table_header_style),
                Paragraph("FWHM (cm\u207b\u00b9)", table_header_style),
                Paragraph("Assignment", table_header_style),
            ]

            sorted_peaks = sorted(project.peaks, key=lambda p: p.position, reverse=True)

            data_rows = []
            for peak in sorted_peaks:
                fwhm_str = f"{peak.fwhm:.2f}" if peak.fwhm is not None else "\u2014"
                data_rows.append(
                    [
                        Paragraph(f"{peak.position:.2f}", table_cell_right),
                        Paragraph(f"{peak.intensity:.4f}", table_cell_right),
                        Paragraph(fwhm_str, table_cell_right),
                        Paragraph(peak.display_label, table_cell_style),
                    ]
                )

            table_data = [header_row] + data_rows
            peaks_table = Table(
                table_data,
                colWidths=[col_pos_w, col_int_w, col_fwhm_w, col_assign_w],
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
            # Alternating row backgrounds for data rows
            for i, _ in enumerate(data_rows):
                row_idx = i + 1  # skip header
                if i % 2 == 1:
                    ts.add("BACKGROUND", (0, row_idx), (-1, row_idx), colors.HexColor("#F5F5F5"))
            peaks_table.setStyle(ts)
            story.append(peaks_table)

            # --- 5. Molecular structures ---
            if options.include_structures:
                peaks_with_smiles = [p for p in sorted_peaks if p.smiles]
                if peaks_with_smiles:
                    struct_rows = []
                    for peak in peaks_with_smiles:
                        png_bytes = render_smiles_to_png(peak.smiles, size=(105, 105))
                        if png_bytes is None:
                            continue
                        left_text = (
                            f"Position: {peak.position:.2f} cm\u207b\u00b9<br/>"
                            f"Assignment: {peak.display_label}"
                        )
                        mol_img = Image(io.BytesIO(png_bytes), width=3.5 * cm, height=3.5 * cm)
                        struct_rows.append([Paragraph(left_text, table_cell_style), mol_img])
                    if struct_rows:
                        story.append(Spacer(1, 0.4 * cm))
                        story.append(Paragraph("Molecular structures", section_style))
                        left_col_w = _TEXT_W - 4 * cm
                        right_col_w = 4 * cm
                        struct_table = Table(
                            struct_rows,
                            colWidths=[left_col_w, right_col_w],
                        )
                        struct_table.setStyle(
                            TableStyle(
                                [
                                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                                ]
                            )
                        )
                        story.append(struct_table)

        doc = SimpleDocTemplate(
            str(output_path),
            pagesize=A4,
            leftMargin=_MARGIN,
            rightMargin=_MARGIN,
            topMargin=_MARGIN,
            bottomMargin=_MARGIN + 0.5 * cm,
        )
        doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
