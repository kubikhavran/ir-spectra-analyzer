"""Tests for JCAMP-DX reader."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest


def test_jcamp_reader_raises_on_missing_file() -> None:
    from file_io.jcamp_reader import JCAMPReader

    reader = JCAMPReader()
    with pytest.raises(FileNotFoundError):
        reader.read(Path("/nonexistent/file.jdx"))


def test_jcamp_reader_parses_nist_like_xydata_and_metadata(tmp_path: Path) -> None:
    from core.spectrum import SpectralUnit
    from file_io.jcamp_reader import JCAMPReader

    path = tmp_path / "nist_like.jdx"
    path.write_text(
        """##TITLE=Example compound
##JCAMP-DX=4.24
##DATA TYPE=INFRARED SPECTRUM
##ORIGIN=NIST example
##OWNER=NIST Standard Reference Data Program
Collection (C) 2018 copyright notice
##STATE=liquid
##SAMPLING PROCEDURE=liquid neat
##XUNITS=1/CM
##YUNITS=ABSORBANCE
##XFACTOR=1.0
##YFACTOR=0.1
##DELTAX=4
##FIRSTX=400
##LASTX=412
##NPOINTS=4
##XYDATA=(X++(Y..Y))
400 1 2 3 4
##END=
""",
        encoding="utf-8",
    )

    spectrum = JCAMPReader().read(path)

    assert spectrum.title == "Example compound"
    assert spectrum.y_unit == SpectralUnit.ABSORBANCE
    assert np.allclose(spectrum.wavenumbers, [400.0, 404.0, 408.0, 412.0])
    assert np.allclose(spectrum.intensities, [0.1, 0.2, 0.3, 0.4])
    assert spectrum.extra_metadata["state"] == "liquid"
    assert spectrum.extra_metadata["sampling_procedure"] == "liquid neat"
    assert "NIST Standard Reference Data Program" in spectrum.extra_metadata["owner"]
    assert "liquid neat" in spectrum.comments


def test_jcamp_reader_parses_xypoints_and_converts_micrometers_to_wavenumbers(
    tmp_path: Path,
) -> None:
    from core.spectrum import SpectralUnit
    from file_io.jcamp_reader import JCAMPReader

    path = tmp_path / "xy_points.dx"
    path.write_text(
        """##TITLE=Micrometer IR
##XUNITS=MICROMETERS
##YUNITS=%T
##XYPOINTS=(XY..XY)
2.5 90
5.0 75
10.0 50
##END=
""",
        encoding="utf-8",
    )

    spectrum = JCAMPReader().read(path)

    assert spectrum.y_unit == SpectralUnit.TRANSMITTANCE
    assert np.allclose(spectrum.wavenumbers, [1000.0, 2000.0, 4000.0])
    assert np.allclose(spectrum.intensities, [50.0, 75.0, 90.0])


def test_jcamp_reader_parses_peak_table_pairs(tmp_path: Path) -> None:
    from file_io.jcamp_reader import JCAMPReader

    path = tmp_path / "peak_table.jdx"
    path.write_text(
        """##TITLE=Peak table
##XUNITS=1/CM
##YUNITS=ABSORBANCE
##PEAK TABLE=(XY..XY)
4000, 0.10, 3000, 0.20, 1500, 0.50
##END=
""",
        encoding="utf-8",
    )

    spectrum = JCAMPReader().read(path)

    assert np.allclose(spectrum.wavenumbers, [1500.0, 3000.0, 4000.0])
    assert np.allclose(spectrum.intensities, [0.50, 0.20, 0.10])


def test_format_registry_reads_jcamp_extensions(tmp_path: Path) -> None:
    from file_io.format_registry import FormatRegistry

    jdx_path = tmp_path / "sample.jdx"
    dx_path = tmp_path / "sample.dx"
    content = """##TITLE=Registry
##XUNITS=1/CM
##YUNITS=ABSORBANCE
##XYPOINTS=(XY..XY)
1000 0.1 1200 0.2
##END=
"""
    jdx_path.write_text(content, encoding="utf-8")
    dx_path.write_text(content, encoding="utf-8")

    registry = FormatRegistry()
    jdx_spectrum = registry.read(jdx_path)
    dx_spectrum = registry.read(dx_path)

    assert jdx_spectrum.title == "Registry"
    assert dx_spectrum.title == "Registry"
    assert np.allclose(jdx_spectrum.wavenumbers, [1000.0, 1200.0])
    assert np.allclose(dx_spectrum.intensities, [0.1, 0.2])
