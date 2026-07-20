"""
CSVExporter — Export analysis to a structured, columnar CSV/TXT file.

Zodpovědnost:
- Stejná data jako XLSX export (metadata, peaky, plná X/Y data spektra)
- Tři bloky vedle sebe, každý ve vlastních sloupcích — nic není v jedné buňce
- Středník jako výchozí oddělovač (české Excely ho rovnou rozdělí do sloupců)
"""

from __future__ import annotations

import csv
from itertools import zip_longest
from pathlib import Path
from typing import TYPE_CHECKING

from core.peak import Peak
from core.peak_assignments import build_peak_assignment_rows, collect_export_metadata
from core.spectrum import Spectrum

if TYPE_CHECKING:
    from core.project import Project


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
        """
        y_unit_label = spectrum.y_unit.value if spectrum is not None else "Intensity"

        # ── Build each block as a list of equal-width rows ──────────────────
        metadata_block: list[list[str]] = [
            [label, value] for label, value in collect_export_metadata(project, spectrum)
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
                f"{row.intensity:.4f}",
                row.intensity_label,
                row.assignment,
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
        if include_spectrum_data and spectrum is not None:
            spectrum_block = [
                [f"{float(wn):.2f}", f"{float(intensity):.6f}"]
                for wn, intensity in zip(spectrum.wavenumbers, spectrum.intensities, strict=True)
            ]

        blocks = [(metadata_header, metadata_block, 2), (peaks_header, peaks_block, 4)]
        if include_spectrum_data and spectrum is not None:
            blocks.append((spectrum_header, spectrum_block, 2))

        with output_path.open("w", newline="", encoding="utf-8-sig") as f:
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
