"""
XLSXExporter — Export analysis to a structured Microsoft Excel workbook.

Zodpovědnost:
- Tři listy: Metadata, Peaks, Spectrum (plná X/Y data)
- Formátování buněk (tučné záhlaví, zamrzlé řádky, šířky sloupců, číselné
  formáty, filtr a střídání řádků v tabulce píků)
- Struktura molekuly vedle metadat, pokud ji projekt má
- Volitelný graf spektra (osa vlnočtů klesá zleva doprava jako v IR zvyklostech)

Závislost: openpyxl
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from core.peak import Peak
from core.peak_assignments import (
    build_peak_assignment_rows,
    collect_export_metadata,
    intensity_unit_label,
)
from core.spectrum import Spectrum
from file_io.atomic_output import atomic_output_path
from file_io.spreadsheet_safety import neutralize_spreadsheet_formula

if TYPE_CHECKING:
    from core.project import Project


# Number formats: whole wavenumbers for peaks, two decimals for the spectrum
# axis; intensities on the %-scale need two decimals, absorbance four.
_POSITION_FORMAT = "0"
_WAVENUMBER_FORMAT = "0.00"
_PERCENT_FORMAT = "0.00"
_ABSORBANCE_FORMAT = "0.0000"
_ZEBRA_FILL = "F2F5F8"
_STRUCTURE_ANCHOR = "D3"
_STRUCTURE_MAX_PX = 320


def _intensity_format(spectrum: Spectrum | None) -> str:
    return (
        _PERCENT_FORMAT if spectrum is not None and spectrum.is_dip_spectrum else _ABSORBANCE_FORMAT
    )


class XLSXExporter:
    """Exports the full analysis to a formatted Excel (.xlsx) workbook."""

    def export(
        self,
        peaks: list[Peak],
        output_path: Path,
        spectrum: Spectrum | None = None,
        include_unassigned: bool = False,
        project: Project | None = None,
        include_chart: bool = False,
    ) -> None:
        """Export the analysis to an xlsx workbook.

        Args:
            peaks: List of peaks to export.
            output_path: Destination .xlsx file path.
            spectrum: Spectrum providing X/Y data and dip/absorption polarity.
            include_unassigned: Whether to include peaks without vibration assignments.
            project: Optional project for editable metadata (sample, operator…).
            include_chart: Add a chart of the spectrum to the Spectrum sheet.
        """
        import openpyxl  # noqa: PLC0415
        from openpyxl.styles import Alignment, Font, PatternFill  # noqa: PLC0415

        header_font = Font(bold=True, color="FFFFFF")
        header_fill = PatternFill("solid", fgColor="374A6B")
        title_font = Font(bold=True, size=13)
        y_unit_label = intensity_unit_label(spectrum)
        intensity_format = _intensity_format(spectrum)
        zebra_fill = PatternFill("solid", fgColor=_ZEBRA_FILL)

        def _style_header(ws, row: int, n_cols: int) -> None:
            for col in range(1, n_cols + 1):
                cell = ws.cell(row=row, column=col)
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = Alignment(horizontal="center", vertical="center")

        def _autosize(ws, max_width: int = 60) -> None:
            for col in ws.columns:
                length = 0
                letter = col[0].column_letter
                for cell in col:
                    if cell.value is not None:
                        length = max(length, len(str(cell.value)))
                ws.column_dimensions[letter].width = min(length + 2, max_width)

        wb = openpyxl.Workbook()

        # ── Metadata sheet ──────────────────────────────────────────────────
        meta_ws = wb.active
        meta_ws.title = "Metadata"
        meta_ws.cell(row=1, column=1, value="IR spectrum analysis").font = title_font
        meta_ws.cell(row=3, column=1, value="Field")
        meta_ws.cell(row=3, column=2, value="Value")
        _style_header(meta_ws, 3, 2)
        for offset, (label, value) in enumerate(
            collect_export_metadata(project, spectrum), start=4
        ):
            meta_ws.cell(row=offset, column=1, value=label).font = Font(bold=True)
            meta_ws.cell(
                row=offset,
                column=2,
                value=neutralize_spreadsheet_formula(value),
            )
        _autosize(meta_ws)
        self._insert_structure(meta_ws, project)

        # ── Peaks sheet (assigned peaks unless explicitly asked otherwise) ──
        peaks_ws = wb.create_sheet("Peaks")
        peaks_headers = [
            "Position (cm⁻¹)",
            f"Intensity ({y_unit_label})",
            "Rel. intensity",
            "Assignment",
        ]
        for col, header in enumerate(peaks_headers, start=1):
            peaks_ws.cell(row=1, column=col, value=header)
        _style_header(peaks_ws, 1, len(peaks_headers))

        assignment_rows = build_peak_assignment_rows(
            peaks,
            is_dip_spectrum=spectrum.is_dip_spectrum if spectrum is not None else False,
            include_unassigned=include_unassigned,
        )
        for row, assignment_row in enumerate(assignment_rows, start=2):
            position_cell = peaks_ws.cell(row=row, column=1, value=assignment_row.position)
            position_cell.number_format = _POSITION_FORMAT
            intensity_cell = peaks_ws.cell(
                row=row, column=2, value=round(assignment_row.intensity, 4)
            )
            intensity_cell.number_format = intensity_format
            peaks_ws.cell(row=row, column=3, value=assignment_row.intensity_label)
            peaks_ws.cell(
                row=row,
                column=4,
                value=neutralize_spreadsheet_formula(assignment_row.assignment),
            )
            if row % 2 == 1:  # every other data row, starting with the second
                for col in range(1, len(peaks_headers) + 1):
                    peaks_ws.cell(row=row, column=col).fill = zebra_fill
        peaks_ws.freeze_panes = "A2"
        last_row = max(len(assignment_rows) + 1, 1)
        peaks_ws.auto_filter.ref = f"A1:D{last_row}"
        _autosize(peaks_ws)

        # ── Spectrum sheet (full X/Y data, plottable) ───────────────────────
        if spectrum is not None:
            self._write_spectrum_sheet(wb, spectrum, y_unit_label, include_chart=include_chart)

        with atomic_output_path(output_path) as temp_path:
            wb.save(temp_path)

    @staticmethod
    def _structure_png(project: Project | None) -> bytes | None:
        """PNG of the project's structure, or None when it has none or it fails."""
        if project is None:
            return None
        smiles = str(getattr(project, "smiles", "") or "")
        mol_block = str(getattr(project, "mol_block", "") or "")
        if smiles or mol_block:
            try:
                from chemistry.structure_renderer import render_structure  # noqa: PLC0415

                art = render_structure(smiles, mol_block, max_px=_STRUCTURE_MAX_PX)
            except Exception:  # noqa: BLE001 — a picture must never stop the export
                art = None
            if art is not None and art.png:
                return bytes(art.png)
        legacy = bytes(getattr(project, "structure_image", b"") or b"")
        return legacy or None

    @classmethod
    def _insert_structure(cls, ws, project: Project | None) -> None:
        """Place the molecule beside the metadata table."""
        png = cls._structure_png(project)
        if not png:
            return
        from io import BytesIO  # noqa: PLC0415

        from openpyxl.drawing.image import Image  # noqa: PLC0415

        try:
            image = Image(BytesIO(png))
        except Exception:  # noqa: BLE001 — an unreadable legacy image is skipped
            return
        scale = min(1.0, _STRUCTURE_MAX_PX / max(image.width, image.height, 1))
        image.width = int(image.width * scale)
        image.height = int(image.height * scale)
        ws.add_image(image, _STRUCTURE_ANCHOR)

    @staticmethod
    def _write_spectrum_sheet(
        wb, spectrum: Spectrum, y_unit_label: str, *, include_chart: bool = False
    ) -> None:
        import math  # noqa: PLC0415

        from openpyxl.styles import Alignment, Font, PatternFill  # noqa: PLC0415

        ws = wb.create_sheet("Spectrum")
        ws.cell(row=1, column=1, value="Wavenumber (cm⁻¹)")
        ws.cell(row=1, column=2, value=f"Intensity ({y_unit_label})")
        for col in (1, 2):
            cell = ws.cell(row=1, column=col)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="374A6B")
            cell.alignment = Alignment(horizontal="center")

        intensity_format = _intensity_format(spectrum)
        for row, (wn, intensity) in enumerate(
            zip(spectrum.wavenumbers, spectrum.intensities, strict=True), start=2
        ):
            x_cell = ws.cell(row=row, column=1, value=round(float(wn), 2))
            x_cell.number_format = _WAVENUMBER_FORMAT
            value = float(intensity)
            # A blanked (NaN) point is an empty cell: a gap, not a number.
            y_cell = ws.cell(
                row=row, column=2, value=round(value, 6) if math.isfinite(value) else None
            )
            y_cell.number_format = intensity_format

        ws.freeze_panes = "A2"
        ws.column_dimensions["A"].width = 20
        ws.column_dimensions["B"].width = 22
        if include_chart:
            XLSXExporter._add_spectrum_chart(ws, spectrum, y_unit_label)

    @staticmethod
    def _add_spectrum_chart(ws, spectrum: Spectrum, y_unit_label: str) -> None:
        """A line chart of the spectrum with the wavenumber axis running 4000 → 400."""
        from openpyxl.chart import Reference, ScatterChart, Series  # noqa: PLC0415

        last_row = spectrum.n_points + 1
        chart = ScatterChart()
        chart.title = str(spectrum.title or "IR spectrum")
        chart.style = 2
        chart.height = 11
        chart.width = 24
        chart.legend = None
        chart.x_axis.title = "Wavenumber (cm⁻¹)"
        chart.y_axis.title = y_unit_label
        # IR convention: high wavenumbers on the left.
        chart.x_axis.scaling.orientation = "maxMin"
        chart.x_axis.delete = False
        chart.y_axis.delete = False
        x_values = Reference(ws, min_col=1, min_row=2, max_row=last_row)
        y_values = Reference(ws, min_col=2, min_row=2, max_row=last_row)
        series = Series(y_values, x_values)
        series.marker.symbol = "none"
        series.smooth = False
        series.graphicalProperties.line.solidFill = "1F6FB2"
        series.graphicalProperties.line.width = 12700  # 1 pt
        chart.series.append(series)
        ws.add_chart(chart, "D2")
