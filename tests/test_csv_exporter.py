"""Tests for the structured columnar CSV analysis export."""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from core.peak import Peak
from core.project import Project
from core.spectrum import SpectralUnit, Spectrum
from file_io.csv_exporter import CSVExporter


def _make_spectrum(y_unit: SpectralUnit = SpectralUnit.TRANSMITTANCE) -> Spectrum:
    return Spectrum(
        wavenumbers=np.array([4000.0, 3000.0, 2000.0, 1000.0]),
        intensities=np.array([95.0, 75.0, 55.0, 35.0]),
        y_unit=y_unit,
    )


def _read(path: Path) -> list[list[str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.reader(handle, delimiter=";"))


def test_csv_export_is_columnar_with_three_side_by_side_blocks(tmp_path: Path) -> None:
    """Metadata, peaks and spectrum sit in their own columns, separated by spacers."""
    peaks = [
        Peak(position=1712.6, intensity=11.2, label="1713"),  # unassigned
        Peak(position=2954.8, intensity=5.1, vibration_ids=[1], vibration_labels=["ν(C-H)"]),
        Peak(position=1456.4, intensity=3.7, vibration_ids=[2], vibration_labels=["δ(CH₂)"]),
    ]
    project = Project(name="Sample-1", spectrum=_make_spectrum(SpectralUnit.ABSORBANCE))
    project.metadata.title = "LF_647"
    project.metadata.file_name = "Sample-1"
    project.metadata.operator = "J. Doe"

    output_path = tmp_path / "analysis.csv"
    CSVExporter().export(peaks, output_path, project.spectrum, project=project)

    rows = _read(output_path)
    header = rows[0]
    # Metadata block | spacer | peaks block | spacer | spectrum block
    assert header[0:2] == ["Field", "Value"]
    assert header[2] == ""
    assert header[3:7] == [
        "Position (cm⁻¹)",
        "Intensity (Absorbance)",
        "Rel. intensity",
        "Assignment",
    ]
    assert header[7] == ""
    assert header[8:10] == ["Wavenumber (cm⁻¹)", "Intensity (Absorbance)"]

    # First data row combines first metadata, first (assigned) peak, first spectrum point
    first = rows[1]
    assert first[0:2] == ["Sample", "LF_647"]  # sample designation = spectrum title
    assert rows[2][0:2] == ["File", "Sample-1"]
    assert first[3] == "2955"  # highest-wavenumber assigned peak
    assert first[8] == "4000.00"


def test_csv_export_omits_unassigned_peaks_by_default(tmp_path: Path) -> None:
    peaks = [
        Peak(position=1712.6, intensity=11.2, label="1713"),
        Peak(position=2954.8, intensity=5.1, vibration_ids=[1], vibration_labels=["ν(C-H)"]),
    ]
    output_path = tmp_path / "assigned.csv"
    CSVExporter().export(peaks, output_path, _make_spectrum(SpectralUnit.ABSORBANCE))

    rows = _read(output_path)
    positions = [r[3] for r in rows[1:] if len(r) > 3 and r[3]]
    assert positions == ["2955"]


def test_csv_export_can_include_unassigned_peaks(tmp_path: Path) -> None:
    peaks = [
        Peak(position=1712.6, intensity=11.2, label="1713"),
        Peak(position=2954.8, intensity=5.1, vibration_ids=[1], vibration_labels=["ν(C-H)"]),
    ]
    output_path = tmp_path / "all.csv"
    CSVExporter().export(
        peaks,
        output_path,
        _make_spectrum(SpectralUnit.ABSORBANCE),
        include_unassigned=True,
    )

    rows = _read(output_path)
    positions = [r[3] for r in rows[1:] if len(r) > 3 and r[3]]
    assert positions == ["2955", "1713"]


def test_csv_export_can_omit_spectrum_data(tmp_path: Path) -> None:
    peaks = [Peak(position=1456.4, intensity=3.7, vibration_labels=["δ(CH₂)"])]
    output_path = tmp_path / "no_data.csv"
    CSVExporter().export(peaks, output_path, _make_spectrum(), include_spectrum_data=False)

    header = _read(output_path)[0]
    assert "Wavenumber (cm⁻¹)" not in header
    assert "Position (cm⁻¹)" in header
