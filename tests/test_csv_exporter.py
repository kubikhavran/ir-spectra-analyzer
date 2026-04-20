"""Tests for CSV peak-assignment export formatting."""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from core.peak import Peak
from core.spectrum import SpectralUnit, Spectrum
from file_io.csv_exporter import CSVExporter


def _make_spectrum(y_unit: SpectralUnit = SpectralUnit.TRANSMITTANCE) -> Spectrum:
    return Spectrum(
        wavenumbers=np.array([4000.0, 3000.0, 2000.0, 1000.0]),
        intensities=np.array([95.0, 75.0, 55.0, 35.0]),
        y_unit=y_unit,
    )


def test_csv_export_matches_pdf_peak_assignment_table(tmp_path: Path) -> None:
    """CSV export should only include assigned peaks with PDF-style columns."""
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

    output_path = tmp_path / "assignments.csv"
    CSVExporter().export(peaks, output_path, _make_spectrum(SpectralUnit.ABSORBANCE))

    with output_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))

    assert rows == [
        ["Position (cm⁻¹)", "Intensity", "Int.", "Assignment"],
        ["2955", "5.1000", "vs", "ν(C-H)"],
        ["1456", "3.7000", "s", "δ(CH₂)"],
    ]
