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
            assert peaks_ws.cell(1, 3).value == "Label"
            assert peaks_ws.cell(1, 4).value == "Vibration"

            # Check data rows
            assert peaks_ws.cell(2, 1).value == 1650.5
            assert peaks_ws.cell(2, 2).value == 0.85
            assert peaks_ws.cell(2, 3).value == "C=O stretch"
            assert peaks_ws.cell(2, 4).value == "C=O stretch"  # vibration name when assigned

            assert peaks_ws.cell(3, 1).value == 2950.0
            assert peaks_ws.cell(3, 2).value == 0.92
            assert peaks_ws.cell(3, 3).value == "C-H stretch"
            assert peaks_ws.cell(3, 4).value == "C-H stretch"

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
