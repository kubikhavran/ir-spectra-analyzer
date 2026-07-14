"""Tests for the structured CSV analysis export."""

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


def _read_sections(path: Path) -> dict[str, list[list[str]]]:
    """Split the CSV into named sections keyed by their single-cell header row."""
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))
    sections: dict[str, list[list[str]]] = {}
    current: str | None = None
    for row in rows:
        if not row or all(cell == "" for cell in row):
            current = None
            continue
        if len(row) == 1 and current is None:
            current = row[0]
            sections[current] = []
            continue
        if current is not None:
            sections[current].append(row)
    return sections


def test_csv_export_has_metadata_peak_and_spectrum_sections(tmp_path: Path) -> None:
    """The CSV must carry metadata, the peak table, and full X/Y data."""
    peaks = [
        Peak(position=1712.6, intensity=11.2, label="1713"),
        Peak(position=2954.8, intensity=5.1, vibration_ids=[1], vibration_labels=["ν(C-H)"]),
        Peak(position=1456.4, intensity=3.7, vibration_ids=[2], vibration_labels=["δ(CH₂)"]),
    ]
    project = Project(name="Sample-1", spectrum=_make_spectrum(SpectralUnit.ABSORBANCE))
    project.metadata.operator = "J. Doe"

    output_path = tmp_path / "analysis.csv"
    CSVExporter().export(peaks, output_path, project.spectrum, project=project)

    sections = _read_sections(output_path)
    assert "Metadata" in sections
    assert ["Operator", "J. Doe"] in sections["Metadata"]

    # Peak table: only assigned peaks, PDF-consistent ordering (descending)
    peak_rows = sections["Peak assignments"][1:]  # skip column header
    assert [row[0] for row in peak_rows] == ["2955", "1456"]
    assert peak_rows[0][4] == "ν(C-H)"

    # Full spectrum data present and plottable
    spectrum_rows = sections["Spectrum data"][1:]
    assert len(spectrum_rows) == 4
    assert spectrum_rows[0] == ["4000.00", "95.000000"]


def test_csv_export_can_include_unassigned_peaks(tmp_path: Path) -> None:
    """With include_unassigned=True, peaks without assignments are exported too."""
    peaks = [
        Peak(position=1712.6, intensity=11.2, label="1713"),
        Peak(position=2954.8, intensity=5.1, vibration_ids=[1], vibration_labels=["ν(C-H)"]),
    ]

    output_path = tmp_path / "all_peaks.csv"
    CSVExporter().export(
        peaks,
        output_path,
        _make_spectrum(SpectralUnit.ABSORBANCE),
        include_unassigned=True,
    )

    sections = _read_sections(output_path)
    peak_rows = sections["Peak assignments"][1:]
    assert [row[0] for row in peak_rows] == ["2955", "1713"]


def test_csv_export_can_omit_spectrum_data(tmp_path: Path) -> None:
    """include_spectrum_data=False keeps the file compact."""
    peaks = [Peak(position=1456.4, intensity=3.7, vibration_labels=["δ(CH₂)"])]
    output_path = tmp_path / "no_data.csv"
    CSVExporter().export(peaks, output_path, _make_spectrum(), include_spectrum_data=False)

    sections = _read_sections(output_path)
    assert "Spectrum data" not in sections
    assert "Peak assignments" in sections
