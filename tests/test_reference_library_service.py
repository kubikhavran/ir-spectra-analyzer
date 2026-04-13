"""Tests for bundled reference-library discovery and similarity search."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from app.reference_library_service import ReferenceLibraryService
from core.spectrum import SpectralUnit
from storage.database import Database


@pytest.fixture
def db():
    """Provide an in-memory database for reference-library integration tests."""
    database = Database(":memory:")
    database.initialize()
    yield database
    database.close()


def test_search_engine_aligns_transmittance_with_absorbance():
    """Matching should compare equivalent band shapes consistently across common IR units."""
    from matching.search_engine import SearchEngine

    wavenumbers = np.linspace(400.0, 4000.0, 1200)
    absorbance_like = np.exp(-0.5 * ((wavenumbers - 1710.0) / 28.0) ** 2)
    transmittance_like = 100.0 - absorbance_like * 35.0
    distractor = np.exp(-0.5 * ((wavenumbers - 1200.0) / 35.0) ** 2)

    refs = [
        {
            "id": 1,
            "name": "target",
            "wavenumbers": wavenumbers,
            "intensities": absorbance_like,
            "y_unit": SpectralUnit.ABSORBANCE.value,
        },
        {
            "id": 2,
            "name": "distractor",
            "wavenumbers": wavenumbers,
            "intensities": distractor,
            "y_unit": SpectralUnit.ABSORBANCE.value,
        },
    ]
    engine = SearchEngine()
    engine.load_references(refs)

    results = engine.search(
        wavenumbers,
        transmittance_like,
        top_n=2,
        query_y_unit=SpectralUnit.TRANSMITTANCE,
    )

    assert results[0].name == "target"
    assert results[0].score > results[1].score
    assert results[0].score > 0.95


def test_reference_library_service_auto_imports_fixture_folder_and_finds_exact_match(db):
    """Bundled `reference library_1` should auto-import and return the exact file as top hit."""
    from file_io.format_registry import FormatRegistry

    project_root = Path(__file__).resolve().parent / "fixtures"
    service = ReferenceLibraryService(db, project_root=project_root)
    fixture_folder = project_root / "reference library_1"
    query_path = fixture_folder / "FER58-SE.SPA"
    spectrum = FormatRegistry().read(query_path)

    outcome = service.search_spectrum(spectrum, top_n=5, auto_import_project_library=True)

    assert outcome.library_folder == fixture_folder.resolve()
    assert outcome.imported_summary is not None
    assert outcome.imported_summary.imported == len(list(fixture_folder.glob("*.SPA")))
    assert outcome.reference_count == outcome.imported_summary.imported
    assert outcome.results
    assert outcome.results[0].name == "FER58-SE"
    assert outcome.results[0].score == pytest.approx(1.0)


def test_ensure_project_library_imported_syncs_missing_fixture_files_even_when_db_non_empty(db):
    """A pre-populated DB must not block bundled-library sync."""
    from file_io.format_registry import FormatRegistry

    project_root = Path(__file__).resolve().parent / "fixtures"
    fixture_folder = project_root / "reference library_1"
    service = ReferenceLibraryService(db, project_root=project_root)

    manual_wn = np.linspace(400.0, 4000.0, 64)
    manual_ints = np.ones(64, dtype=np.float64)
    db.add_reference_spectrum(
        "Manual Only",
        manual_wn,
        manual_ints,
        source="manual.spa",
        y_unit=SpectralUnit.ABSORBANCE.value,
    )

    summary = service.ensure_project_library_imported()

    assert summary is not None
    assert summary.imported == len(list(fixture_folder.glob("*.SPA")))
    assert len(db.get_reference_spectra()) == summary.imported + 1

    query = FormatRegistry().read(fixture_folder / "FER58-SE.SPA")
    outcome = service.search_spectrum(query, top_n=3, auto_import_project_library=True)

    assert outcome.imported_summary is not None
    assert outcome.imported_summary.imported == 0
    assert outcome.imported_summary.skipped == len(list(fixture_folder.glob("*.SPA")))
    assert outcome.results[0].name == "FER58-SE"


def test_selected_library_folder_filters_references_and_persists_setting(db, tmp_path):
    """The active library folder should scope the visible/searchable references."""
    folder_a = tmp_path / "library_a"
    folder_b = tmp_path / "library_b"
    folder_a.mkdir()
    folder_b.mkdir()

    wn = np.linspace(400.0, 4000.0, 32)
    ints = np.linspace(0.0, 1.0, 32)
    db.add_reference_spectrum(
        "A-1",
        wn,
        ints,
        source=str(folder_a / "A-1.SPA"),
        y_unit=SpectralUnit.ABSORBANCE.value,
    )
    db.add_reference_spectrum(
        "B-1",
        wn,
        ints,
        source=str(folder_b / "B-1.SPA"),
        y_unit=SpectralUnit.ABSORBANCE.value,
    )

    settings = SimpleNamespace(
        values={}, get=lambda key, default=None: settings.values.get(key, default)
    )

    def _set(key, value):
        settings.values[key] = value

    settings.set = _set
    service = ReferenceLibraryService(db, settings=settings)

    selected = service.set_selected_library_folder(folder_a)

    assert selected == folder_a.resolve()
    assert settings.values["reference_library_folder"] == str(folder_a.resolve())
    assert [ref["name"] for ref in service.get_library_references()] == ["A-1"]
