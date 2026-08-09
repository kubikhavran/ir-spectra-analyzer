"""Spectra with blanked (NaN) regions must survive the whole pipeline.

OMNIC writes NaN where a region was masked out because the solvent absorbs
completely — the lab library is full of chloroform-cast films with gaps around
3016, 1216, 757 and 669 cm^-1. Before v0.25.0 such a file could not be plotted,
exported or saved.
"""

import numpy as np
import pytest

from core.project import Project
from core.spectrum import SpectralUnit, Spectrum
from storage.project_serializer import ProjectSerializer


def _blanked_spectrum() -> Spectrum:
    wavenumbers = np.linspace(400.0, 4000.0, 1201)
    intensities = 100.0 - 40.0 * np.exp(-(((wavenumbers - 1700.0) / 40.0) ** 2))
    # Two blanked bands, as a solvent-masked measurement would have.
    intensities[(wavenumbers > 1205) & (wavenumbers < 1226)] = np.nan
    intensities[(wavenumbers > 715) & (wavenumbers < 799)] = np.nan
    return Spectrum(
        wavenumbers=wavenumbers, intensities=intensities, y_unit=SpectralUnit.TRANSMITTANCE
    )


def test_project_roundtrip_preserves_blanked_points():
    """JSON has no NaN literal, so blanked points travel as null."""
    spectrum = _blanked_spectrum()
    project = Project(name="blanked", spectrum=spectrum)

    import tempfile
    from pathlib import Path

    path = Path(tempfile.mkdtemp()) / "p.irproj"
    ProjectSerializer().save(project, path)
    loaded = ProjectSerializer().load(path)

    assert np.isnan(loaded.spectrum.intensities).sum() == np.isnan(spectrum.intensities).sum()
    assert np.array_equal(loaded.spectrum.intensities, spectrum.intensities, equal_nan=True)


def test_saved_project_is_standards_compliant_json(tmp_path):
    """The file must parse with a strict reader — no bare NaN tokens."""
    import json

    path = tmp_path / "p.irproj"
    ProjectSerializer().save(Project(name="b", spectrum=_blanked_spectrum()), path)

    with path.open(encoding="utf-8") as handle:
        data = json.load(handle, parse_constant=lambda c: pytest.fail(f"non-standard token {c}"))

    assert None in data["project"]["spectrum"]["intensities"]


def test_infinite_intensities_are_still_rejected(tmp_path):
    wavenumbers = np.linspace(400.0, 4000.0, 10)
    intensities = np.full(10, 1.0)
    intensities[3] = np.inf
    spectrum = Spectrum(
        wavenumbers=wavenumbers, intensities=intensities, y_unit=SpectralUnit.ABSORBANCE
    )

    with pytest.raises(ValueError, match="JSON compliant"):
        ProjectSerializer().save(Project(name="bad", spectrum=spectrum), tmp_path / "p.irproj")


def test_functional_group_scoring_survives_blanked_regions():
    from processing.functional_group_scoring import score_functional_groups

    analysis = score_functional_groups(_blanked_spectrum())

    assert analysis is not None
    for result in analysis.results:
        assert np.isfinite(result.score)


def test_pdf_export_survives_blanked_regions(tmp_path):
    from core.peak import Peak
    from reporting.report_builder import ReportBuilder

    spectrum = _blanked_spectrum()
    project = Project(name="blanked", spectrum=spectrum)
    project.peaks = [Peak(position=1700.0, intensity=60.0), Peak(position=2900.0, intensity=99.0)]

    output = tmp_path / "report.pdf"
    ReportBuilder().build(project, output)

    assert output.stat().st_size > 1000


def test_peak_labels_stay_on_screen_for_blanked_regions(qtbot):
    """A NaN y-span put every label at NaN coordinates, so they vanished."""
    from core.peak import Peak
    from ui.spectrum_widget import SpectrumWidget

    widget = SpectrumWidget()
    qtbot.addWidget(widget)
    widget.set_spectrum(_blanked_spectrum())
    widget.set_peaks([Peak(position=1700.0, intensity=60.0), Peak(position=2900.0, intensity=99.0)])

    label_positions = [item._data_y for item in widget._peak_items if hasattr(item, "_data_y")]
    assert label_positions
    assert all(np.isfinite(y) for y in label_positions)


def test_match_feature_vector_is_finite_for_blanked_regions():
    from matching.feature_store import compute_search_vector

    spectrum = _blanked_spectrum()
    vector = compute_search_vector(
        spectrum.wavenumbers, spectrum.intensities, y_unit=spectrum.y_unit
    )

    assert np.all(np.isfinite(vector))
