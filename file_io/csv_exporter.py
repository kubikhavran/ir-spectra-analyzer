"""
CSVExporter — Export analysis to a structured CSV/TXT file.

Zodpovědnost:
- Export metadat spektra, peakové tabulky a plných X/Y dat do jednoho CSV
- Konfigurovatelný oddělovač (čárka, tabulátor, středník)
- Sekce oddělené prázdným řádkem, aby šlo spektrum vykreslit např. v Excelu
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import TYPE_CHECKING

from core.peak import Peak
from core.peak_assignments import build_peak_assignment_rows, collect_export_metadata
from core.spectrum import Spectrum

if TYPE_CHECKING:
    from core.project import Project


class CSVExporter:
    """Exports the full analysis to a structured CSV / tab-delimited text file."""

    def export(
        self,
        peaks: list[Peak],
        output_path: Path,
        spectrum: Spectrum | None = None,
        delimiter: str = ",",
        include_header: bool = True,
        include_unassigned: bool = False,
        project: Project | None = None,
        include_spectrum_data: bool = True,
    ) -> None:
        """Export the analysis to a CSV file.

        The file is written in three sections separated by blank rows:
        metadata, the peak-assignment table, and the full spectrum X/Y data
        (so the customer can plot the spectrum directly in a spreadsheet).

        Args:
            peaks: List of peaks to export.
            output_path: Destination file path.
            spectrum: Spectrum providing X/Y data and dip/absorption polarity.
            delimiter: Field delimiter character.
            include_header: Whether to include the section/column headers.
            include_unassigned: Whether to include peaks without vibration assignments.
            project: Optional project for editable metadata (sample, operator…).
            include_spectrum_data: Whether to append the full X/Y data section.
        """
        is_dip = spectrum.is_dip_spectrum if spectrum is not None else False
        y_unit_label = spectrum.y_unit.value if spectrum is not None else "Intensity"

        assignment_rows = build_peak_assignment_rows(
            peaks,
            is_dip_spectrum=is_dip,
            include_unassigned=include_unassigned,
        )

        with output_path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f, delimiter=delimiter)

            # ── Metadata section ────────────────────────────────────────────
            metadata_rows = collect_export_metadata(project, spectrum)
            if metadata_rows:
                if include_header:
                    writer.writerow(["Metadata"])
                    writer.writerow(["Field", "Value"])
                for label, value in metadata_rows:
                    writer.writerow([label, value])
                writer.writerow([])

            # ── Peak-assignment section ─────────────────────────────────────
            if include_header:
                writer.writerow(["Peak assignments"])
                writer.writerow(
                    [
                        "Position (cm⁻¹)",
                        f"Intensity ({y_unit_label})",
                        "Rel. intensity",
                        "Assignments",
                        "Assignment",
                    ]
                )
            for row in assignment_rows:
                assignment_count = len(row.peak.vibration_labels) or (1 if row.assignment else 0)
                writer.writerow(
                    [
                        str(row.position),
                        f"{row.intensity:.4f}",
                        row.intensity_label,
                        assignment_count,
                        row.assignment,
                    ]
                )

            # ── Full spectrum data section ──────────────────────────────────
            if include_spectrum_data and spectrum is not None:
                writer.writerow([])
                if include_header:
                    writer.writerow(["Spectrum data"])
                    writer.writerow(["Wavenumber (cm⁻¹)", f"Intensity ({y_unit_label})"])
                for wn, intensity in zip(spectrum.wavenumbers, spectrum.intensities, strict=True):
                    writer.writerow([f"{float(wn):.2f}", f"{float(intensity):.6f}"])
