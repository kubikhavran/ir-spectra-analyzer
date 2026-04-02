"""Tests for project JSON serialization/deserialization."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

from core.peak import Peak
from core.project import Project
from core.spectrum import SpectralUnit, Spectrum, XAxisUnit
from storage.project_serializer import ProjectSerializer


def _make_project() -> Project:
    wn = np.linspace(400.0, 4000.0, 10)
    intensities = np.linspace(0.0, 1.0, 10)
    spectrum = Spectrum(
        wavenumbers=wn,
        intensities=intensities,
        title="Test Spectrum",
        y_unit=SpectralUnit.ABSORBANCE,
        x_unit=XAxisUnit.WAVENUMBER,
        comments="test comments",
        extra_metadata={"instrument_serial": "XYZ123"},
    )
    proj = Project(name="Test", spectrum=spectrum)
    proj.peaks.append(Peak(position=1000.0, intensity=0.5, label="P1", vibration_id=42))
    return proj


def test_project_serializer_roundtrip(tmp_path):
    project = _make_project()
    serializer = ProjectSerializer()
    file_path = tmp_path / "project.irproj"

    serializer.save(project, file_path)
    loaded = serializer.load(file_path)

    assert loaded.name == project.name
    assert loaded.spectrum is not None
    assert np.allclose(loaded.spectrum.wavenumbers, project.spectrum.wavenumbers)
    assert len(loaded.peaks) == 1
    assert loaded.peaks[0].label == "P1"
    assert loaded.peaks[0].vibration_id == 42


def test_project_serializer_with_corrected_spectrum(tmp_path):
    project = _make_project()
    corrected = Spectrum(
        wavenumbers=project.spectrum.wavenumbers,
        intensities=project.spectrum.intensities - 0.1,
        title="Corrected",
    )
    project.corrected_spectrum = corrected

    serializer = ProjectSerializer()
    file_path = tmp_path / "project_corrected.irproj"

    serializer.save(project, file_path)
    loaded = serializer.load(file_path)

    assert loaded.corrected_spectrum is not None
    assert np.allclose(loaded.corrected_spectrum.intensities, corrected.intensities)


def test_project_serializer_bad_format_raises(tmp_path):
    file_path = tmp_path / "bad_project.irproj"
    file_path.write_text('{"format": "bad-format", "version": 1, "project": {}}', encoding="utf-8")

    serializer = ProjectSerializer()
    with pytest.raises(ValueError, match="Unsupported project format"):
        serializer.load(file_path)


def test_project_serializer_unsupported_version_raises(tmp_path):
    file_path = tmp_path / "bad_version.irproj"
    file_path.write_text(
        '{"format": "ir-spectra-analyzer-project", "version": 999, "project": {}}',
        encoding="utf-8",
    )

    serializer = ProjectSerializer()
    with pytest.raises(ValueError, match="Unsupported project version"):
        serializer.load(file_path)


def test_project_serializer_file_not_found(tmp_path):
    """Loading a non-existent file raises FileNotFoundError."""
    serializer = ProjectSerializer()
    with pytest.raises(FileNotFoundError):
        serializer.load(tmp_path / "does_not_exist.irproj")


def test_project_serializer_no_spectrum(tmp_path):
    """Project with no spectrum serializes and loads correctly."""
    proj = Project(name="Empty", spectrum=None)
    serializer = ProjectSerializer()
    file_path = tmp_path / "empty.irproj"
    serializer.save(proj, file_path)
    loaded = serializer.load(file_path)
    assert loaded.name == "Empty"
    assert loaded.spectrum is None
    assert loaded.peaks == []


def test_project_serializer_extra_metadata_roundtrip(tmp_path):
    """extra_metadata dict survives save/load."""
    project = _make_project()
    project.spectrum.extra_metadata["resolution_cm"] = 4.0
    project.spectrum.extra_metadata["instrument_serial"] = "iS10-ABC"
    serializer = ProjectSerializer()
    file_path = tmp_path / "meta.irproj"
    serializer.save(project, file_path)
    loaded = serializer.load(file_path)
    assert loaded.spectrum.extra_metadata["resolution_cm"] == pytest.approx(4.0)
    assert loaded.spectrum.extra_metadata["instrument_serial"] == "iS10-ABC"


def test_project_serializer_source_path_roundtrip(tmp_path):
    """source_path survives save/load."""
    from pathlib import Path  # noqa: PLC0415

    project = _make_project()
    project.spectrum.source_path = Path("/lab/data/sample.spa")
    serializer = ProjectSerializer()
    file_path = tmp_path / "path.irproj"
    serializer.save(project, file_path)
    loaded = serializer.load(file_path)
    assert loaded.spectrum.source_path == Path("/lab/data/sample.spa")


def test_project_serializer_empty_peaks(tmp_path):
    """Project with empty peaks list serializes correctly."""
    project = _make_project()
    project.peaks.clear()
    serializer = ProjectSerializer()
    file_path = tmp_path / "nope.irproj"
    serializer.save(project, file_path)
    loaded = serializer.load(file_path)
    assert loaded.peaks == []


def test_project_serializer_vibration_assignment_roundtrip(tmp_path):
    """vibration_id and label survive save/load."""
    project = _make_project()
    # peak already has vibration_id=42 and label="P1" from _make_project
    serializer = ProjectSerializer()
    file_path = tmp_path / "vib.irproj"
    serializer.save(project, file_path)
    loaded = serializer.load(file_path)
    assert loaded.peaks[0].vibration_id == 42
    assert loaded.peaks[0].label == "P1"


def test_project_serializer_smiles_roundtrip(tmp_path):
    """smiles field survives save/load."""
    project = _make_project()
    project.peaks[0].smiles = "CCO"
    serializer = ProjectSerializer()
    file_path = tmp_path / "smiles.irproj"
    serializer.save(project, file_path)
    loaded = serializer.load(file_path)
    assert loaded.peaks[0].smiles == "CCO"
