"""
CSVExporter — Export analysis to a structured, columnar CSV/TXT file.

Zodpovědnost:
- Stejná data jako XLSX export (metadata, peaky, plná X/Y data spektra)
- Tři bloky vedle sebe, každý ve vlastních sloupcích — nic není v jedné buňce
- Středník jako výchozí oddělovač (české Excely ho rovnou rozdělí do sloupců)
- Volitelně jen tabulka píků nebo jen data spektra (pro Origin, MestReNova, Python)
- Volitelná desetinná čárka (český Excel jinak čísla s tečkou nepozná)
"""

from __future__ import annotations

import csv
import math
from itertools import zip_longest
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


#: What a CSV file contains.
MODE_COMBINED = "combined"  # metadata, peaks and spectrum side by side
MODE_PEAKS_ONLY = "peaks_only"  # just the peak table
MODE_SPECTRUM_ONLY = "spectrum_only"  # just wavenumber / intensity
CSV_MODES = (MODE_COMBINED, MODE_PEAKS_ONLY, MODE_SPECTRUM_ONLY)


class CSVExporter:
    """Exports the full analysis to a structured, columnar CSV file."""

    def export(
        self,
        peaks: list[Peak],
        output_path: Path,
        spectrum: Spectrum | None = None,
        delimiter: str = ";",
        include_header: bool = True,
        include_unassigned: bool = False,
        project: Project | None = None,
        include_spectrum_data: bool = True,
        mode: str = MODE_COMBINED,
        decimal_separator: str = ".",
    ) -> None:
        """Export the analysis to a columnar CSV file.

        The three datasets (metadata, peak table, full spectrum) are written
        side by side, each in its own columns and separated by one blank
        spacer column, so a spreadsheet shows a clean structured layout.

        Args:
            peaks: List of peaks to export.
            output_path: Destination file path.
            spectrum: Spectrum providing X/Y data and dip/absorption polarity.
            delimiter: Field delimiter character (default ``;`` for Excel).
            include_header: Whether to include the column headers.
            include_unassigned: Whether to include peaks without vibration assignments.
            project: Optional project for editable metadata (sample, operator…).
            include_spectrum_data: Whether to include the full X/Y data columns.
            mode: ``"combined"`` (metadata + peaks + spectrum side by side),
                ``"peaks_only"`` or ``"spectrum_only"`` (one plain table).
            decimal_separator: ``"."`` or ``","``. A comma suits a Czech Excel,
                which reads "1.5" as text.

        Raises:
            ValueError: For an unknown mode or separator, a decimal comma with a
                comma delimiter (the columns could not be told apart), or a
                spectrum-only export without a spectrum.
        """
        if mode not in CSV_MODES:
            raise ValueError(f"Unknown CSV mode: {mode!r}")
        if decimal_separator not in (".", ","):
            raise ValueError(f"Unknown decimal separator: {decimal_separator!r}")
        if decimal_separator == delimiter:
            raise ValueError("The decimal separator and the delimiter must differ")
        if mode == MODE_SPECTRUM_ONLY and spectrum is None:
            raise ValueError("A spectrum-only export needs a spectrum")

        def _number(value: float, decimals: int) -> str:
            numeric = float(value)
            if not math.isfinite(numeric):
                return ""
            text = f"{numeric:.{decimals}f}"
            return text.replace(".", ",") if decimal_separator == "," else text

        y_unit_label = intensity_unit_label(spectrum)

        # ── Build each block as a list of equal-width rows ──────────────────
        metadata_block: list[list[str]] = [
            [label, neutralize_spreadsheet_formula(value)]
            for label, value in collect_export_metadata(project, spectrum)
        ]
        metadata_header = ["Field", "Value"]

        assignment_rows = build_peak_assignment_rows(
            peaks,
            is_dip_spectrum=spectrum.is_dip_spectrum if spectrum is not None else False,
            include_unassigned=include_unassigned,
        )
        peaks_block: list[list[str]] = [
            [
                str(row.position),
                _number(row.intensity, 4),
                row.intensity_label,
                neutralize_spreadsheet_formula(row.assignment),
            ]
            for row in assignment_rows
        ]
        peaks_header = [
            "Position (cm⁻¹)",
            f"Intensity ({y_unit_label})",
            "Rel. intensity",
            "Assignment",
        ]

        spectrum_block: list[list[str]] = []
        spectrum_header = ["Wavenumber (cm⁻¹)", f"Intensity ({y_unit_label})"]
        wants_spectrum = include_spectrum_data or mode == MODE_SPECTRUM_ONLY
        if wants_spectrum and spectrum is not None:
            spectrum_block = [
                [_number(wn, 2), _number(intensity, 6)]
                for wn, intensity in zip(spectrum.wavenumbers, spectrum.intensities, strict=True)
            ]

        if mode == MODE_PEAKS_ONLY:
            blocks = [(peaks_header, peaks_block, 4)]
        elif mode == MODE_SPECTRUM_ONLY:
            blocks = [(spectrum_header, spectrum_block, 2)]
        else:
            blocks = [(metadata_header, metadata_block, 2), (peaks_header, peaks_block, 4)]
            if include_spectrum_data and spectrum is not None:
                blocks.append((spectrum_header, spectrum_block, 2))

        with atomic_output_path(output_path) as temp_path:
            with temp_path.open("w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f, delimiter=delimiter)

                if include_header:
                    header_row: list[str] = []
                    for i, (header, _block, _width) in enumerate(blocks):
                        if i > 0:
                            header_row.append("")  # blank spacer column
                        header_row.extend(header)
                    writer.writerow(header_row)

                block_rows = [block for _header, block, _width in blocks]
                block_widths = [width for _header, _block, width in blocks]
                for combined in zip_longest(*block_rows, fillvalue=None):
                    out_row: list[str] = []
                    for i, (cells, width) in enumerate(zip(combined, block_widths, strict=True)):
                        if i > 0:
                            out_row.append("")  # blank spacer column
                        out_row.extend(cells if cells is not None else [""] * width)
                    writer.writerow(out_row)
                f.flush()
