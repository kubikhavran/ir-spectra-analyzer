"""
CSVExporter — Export peakové tabulky do CSV/TXT.

Zodpovědnost:
- Export seznamu peaků s přiřazenými vibracemi do CSV
- Konfigurovatelný oddělovač (čárka, tabulátor, středník)
- Volitelné záhlaví s metadaty spektra
"""

from __future__ import annotations

import csv
from pathlib import Path

from core.peak import Peak
from core.spectrum import Spectrum


class CSVExporter:
    """Exports peak table to CSV or tab-delimited text file."""

    def export(
        self,
        peaks: list[Peak],
        output_path: Path,
        spectrum: Spectrum | None = None,
        delimiter: str = ",",
        include_header: bool = True,
    ) -> None:
        """Export peaks to a CSV file.

        Args:
            peaks: List of peaks to export.
            output_path: Destination file path.
            spectrum: Optional spectrum for metadata header.
            delimiter: Field delimiter character.
            include_header: Whether to include column headers.
        """
        with output_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, delimiter=delimiter)
            if include_header:
                writer.writerow(["Position (cm⁻¹)", "Intensity", "Label", "Vibration"])
            for peak in peaks:
                writer.writerow(
                    [
                        f"{peak.position:.2f}",
                        f"{peak.intensity:.4f}",
                        peak.label,
                        " / ".join(peak.vibration_labels),
                    ]
                )
