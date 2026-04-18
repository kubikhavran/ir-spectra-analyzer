"""
XLSXExporter — Export peakové tabulky do Microsoft Excel formátu.

Zodpovědnost:
- Export peaků do formátovaného .xlsx souboru
- Formátování buněk (tučné záhlaví, zarovnání čísel)
- Metadata spektra v prvních řádcích

Závislost: openpyxl
"""

from __future__ import annotations

from pathlib import Path

from core.peak import Peak
from core.spectrum import Spectrum


class XLSXExporter:
    """Exports peak table to a formatted Excel (.xlsx) workbook."""

    def export(
        self,
        peaks: list[Peak],
        output_path: Path,
        spectrum: Spectrum | None = None,
    ) -> None:
        """Export peaks to an xlsx workbook.

        Args:
            peaks: List of peaks to export.
            output_path: Destination .xlsx file path.
            spectrum: Optional spectrum for metadata rows.
        """
        import openpyxl  # noqa: PLC0415
        from openpyxl.styles import Font  # noqa: PLC0415

        wb = openpyxl.Workbook()

        # Create Peaks sheet
        peaks_ws = wb.active
        peaks_ws.title = "Peaks"

        # Peaks headers
        peaks_headers = ["Position (cm⁻¹)", "Intensity", "Label", "Vibration"]
        for col, header in enumerate(peaks_headers, start=1):
            cell = peaks_ws.cell(row=1, column=col, value=header)
            cell.font = Font(bold=True)

        # Peaks data
        for row, peak in enumerate(peaks, start=2):
            peaks_ws.cell(row=row, column=1, value=round(peak.position, 2))
            peaks_ws.cell(row=row, column=2, value=round(peak.intensity, 4))
            peaks_ws.cell(row=row, column=3, value=peak.label)
            peaks_ws.cell(row=row, column=4, value=" / ".join(peak.vibration_labels))

        # Auto-adjust column widths for Peaks sheet (outside row loop — O(n) not O(n²))
        for col in peaks_ws.columns:
            max_length = 0
            column = col[0].column_letter
            for cell in col:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except (AttributeError, TypeError):
                    pass
            peaks_ws.column_dimensions[column].width = max_length + 2

        # Create Spectrum sheet if spectrum is provided
        if spectrum is not None:
            spectrum_ws = wb.create_sheet("Spectrum")

            # Spectrum headers
            spectrum_headers = ["Wavenumber (cm⁻¹)", "Intensity"]
            for col, header in enumerate(spectrum_headers, start=1):
                cell = spectrum_ws.cell(row=1, column=col, value=header)
                cell.font = Font(bold=True)

            # Spectrum data
            for row, (wn, intensity) in enumerate(
                zip(spectrum.wavenumbers, spectrum.intensities, strict=True), start=2
            ):
                spectrum_ws.cell(row=row, column=1, value=round(wn, 2))
                spectrum_ws.cell(row=row, column=2, value=round(intensity, 6))

            # Auto-adjust column widths for Spectrum sheet
            for col in spectrum_ws.columns:
                max_length = 0
                column = col[0].column_letter
                for cell in col:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except (AttributeError, TypeError):
                        pass
                adjusted_width = max_length + 2
                spectrum_ws.column_dimensions[column].width = adjusted_width

        wb.save(output_path)
