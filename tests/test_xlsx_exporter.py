"""
Test XLSXExporter — testování exportu do Excel formátu.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from core.peak import Peak
from core.spectrum import Spectrum
from file_io.xlsx_exporter import XLSXExporter


class TestXLSXExporter:
    """Test XLSX export functionality."""

    def test_export_peaks_only(self) -> None:
        """Test export with peaks but no spectrum."""
        peaks = [
            Peak(
                position=1650.5,
                intensity=0.85,
                label="C=O stretch",
                vibration_ids=[1],
                vibration_labels=["C=O stretch"],
            ),
            Peak(
                position=2950.0,
                intensity=0.92,
                label="C-H stretch",
                vibration_ids=[2],
                vibration_labels=["C-H stretch"],
            ),
        ]

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            exporter = XLSXExporter()
            exporter.export(peaks, tmp_path)

            # Verify file was created
            assert tmp_path.exists()

            # Basic verification that it's a valid Excel file
            import openpyxl  # noqa: PLC0415

            wb = openpyxl.load_workbook(tmp_path)
            assert "Peaks" in wb.sheetnames

            peaks_ws = wb["Peaks"]
            assert peaks_ws.cell(1, 1).value == "Position (cm⁻¹)"
            assert peaks_ws.cell(1, 2).value == "Intensity"
            assert peaks_ws.cell(1, 3).value == "Int."
            assert peaks_ws.cell(1, 4).value == "Assignment"

            # Check data rows
            assert peaks_ws.cell(2, 1).value == 2950
            assert peaks_ws.cell(2, 2).value == 0.92
            assert peaks_ws.cell(2, 3).value == "vs"
            assert peaks_ws.cell(2, 4).value == "C-H stretch"

            assert peaks_ws.cell(3, 1).value == 1650
            assert peaks_ws.cell(3, 2).value == 0.85
            assert peaks_ws.cell(3, 3).value == "vs"
            assert peaks_ws.cell(3, 4).value == "C=O stretch"

        finally:
            tmp_path.unlink(missing_ok=True)

    def test_export_with_spectrum(self) -> None:
        """Test export with both peaks and spectrum data."""
        import numpy as np  # noqa: PLC0415

        wavenumbers = np.linspace(4000, 400, 100)
        intensities = np.random.random(100)
        spectrum = Spectrum(
            wavenumbers=wavenumbers,
            intensities=intensities,
            title="Test Spectrum",
        )

        peaks = [Peak(position=1650.5, intensity=0.85)]

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            exporter = XLSXExporter()
            exporter.export(peaks, tmp_path, spectrum)

            import openpyxl  # noqa: PLC0415

            wb = openpyxl.load_workbook(tmp_path)
            assert "Peaks" in wb.sheetnames
            assert "Spectrum" in wb.sheetnames

            # Check spectrum sheet
            spectrum_ws = wb["Spectrum"]
            assert spectrum_ws.cell(1, 1).value == "Wavenumber (cm⁻¹)"
            assert spectrum_ws.cell(1, 2).value == "Intensity"
            assert spectrum_ws.cell(2, 1).value == 4000.0  # first wavenumber
            assert isinstance(spectrum_ws.cell(2, 2).value, float)  # intensity value

        finally:
            tmp_path.unlink(missing_ok=True)

    def test_export_empty_peaks(self) -> None:
        """Test export with no peaks."""
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            exporter = XLSXExporter()
            exporter.export([], tmp_path)

            import openpyxl  # noqa: PLC0415

            wb = openpyxl.load_workbook(tmp_path)
            peaks_ws = wb["Peaks"]

            # Should have headers but no data rows
            assert peaks_ws.cell(1, 1).value == "Position (cm⁻¹)"
            assert peaks_ws.cell(2, 1).value is None  # no data

        finally:
            tmp_path.unlink(missing_ok=True)

    def test_export_matches_pdf_peak_assignment_table(self) -> None:
        """Peaks sheet should use the same assignment-table format as the PDF export."""
        peaks = [
            Peak(position=1712.6, intensity=11.2, label="1713"),
            Peak(
                position=2954.8,
                intensity=5.1,
                vibration_ids=[1],
                vibration_labels=["ν(C-H)"],
            ),
            Peak(
                position=1456.4,
                intensity=3.7,
                vibration_ids=[2],
                vibration_labels=["δ(CH₂)"],
            ),
        ]
        spectrum = Spectrum(wavenumbers=[4000.0, 3000.0], intensities=[1.0, 2.0])

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            XLSXExporter().export(peaks, tmp_path, spectrum)

            import openpyxl  # noqa: PLC0415

            wb = openpyxl.load_workbook(tmp_path)
            peaks_ws = wb["Peaks"]

            assert peaks_ws.cell(1, 1).value == "Position (cm⁻¹)"
            assert peaks_ws.cell(1, 2).value == "Intensity"
            assert peaks_ws.cell(1, 3).value == "Int."
            assert peaks_ws.cell(1, 4).value == "Assignment"

            assert peaks_ws.cell(2, 1).value == 2955
            assert peaks_ws.cell(2, 2).value == 5.1
            assert peaks_ws.cell(2, 3).value == "vs"
            assert peaks_ws.cell(2, 4).value == "ν(C-H)"

            assert peaks_ws.cell(3, 1).value == 1456
            assert peaks_ws.cell(3, 2).value == 3.7
            assert peaks_ws.cell(3, 3).value == "s"
            assert peaks_ws.cell(3, 4).value == "δ(CH₂)"

            assert peaks_ws.cell(4, 1).value is None

        finally:
            tmp_path.unlink(missing_ok=True)
