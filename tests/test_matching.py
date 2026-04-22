"""Tests for v0.3.0 spectral matching: database, preprocessing, similarity, search engine."""

from __future__ import annotations

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _gaussian(wn: np.ndarray, center: float, width: float = 50.0) -> np.ndarray:
    return np.exp(-0.5 * ((wn - center) / width) ** 2)


def _make_db(tmp_path):
    from storage.database import Database

    db = Database(db_path=tmp_path / "test.db")
    db.initialize()
    return db


# ---------------------------------------------------------------------------
# Database CRUD
# ---------------------------------------------------------------------------


def test_add_and_get_reference_spectra(tmp_path):
    db = _make_db(tmp_path)
    wn = np.linspace(400.0, 4000.0, 100)
    ints = np.random.default_rng(0).random(100)
    ref_id = db.add_reference_spectrum("Sample A", wn, ints, description="Test sample")
    refs = db.get_reference_spectra()
    assert any(r["id"] == ref_id and r["name"] == "Sample A" for r in refs)
    db.close()


def test_reference_spectrum_arrays_roundtrip(tmp_path):
    db = _make_db(tmp_path)
    wn = np.linspace(400.0, 4000.0, 200)
    ints = np.sin(wn / 500.0)
    db.add_reference_spectrum("Sine", wn, ints)
    refs = db.get_reference_spectra()
    loaded = next(r for r in refs if r["name"] == "Sine")
    assert np.allclose(loaded["wavenumbers"], wn)
    assert np.allclose(loaded["intensities"], ints)
    db.close()


def test_delete_reference_spectrum(tmp_path):
    db = _make_db(tmp_path)
    wn = np.linspace(400.0, 4000.0, 50)
    ints = np.ones(50)
    ref_id = db.add_reference_spectrum("ToDelete", wn, ints)
    db.delete_reference_spectrum(ref_id)
    refs = db.get_reference_spectra()
    assert not any(r["id"] == ref_id for r in refs)
    db.close()


def test_empty_reference_spectra(tmp_path):
    db = _make_db(tmp_path)
    assert db.get_reference_spectra() == []
    db.close()


def test_reference_metadata_and_feature_rows_roundtrip_without_full_blob_load(tmp_path):
    from matching.feature_store import MATCH_FEATURE_VERSION

    db = _make_db(tmp_path)
    wn = np.linspace(400.0, 4000.0, 64)
    ints = np.sin(wn / 500.0)
    ref_id = db.add_reference_spectrum(
        "Metadata Only",
        wn,
        ints,
        source=str(tmp_path / "library" / "sample.spa"),
        y_unit="Absorbance",
    )

    metadata_rows = db.get_reference_metadata()
    assert metadata_rows[0]["id"] == ref_id
    assert metadata_rows[0]["n_points"] == len(wn)
    assert "wavenumbers" not in metadata_rows[0]
    assert "intensities" not in metadata_rows[0]

    feature_vector = np.linspace(0.0, 1.0, 12, dtype=np.float32)
    db.upsert_reference_feature(
        ref_id,
        feature_version=MATCH_FEATURE_VERSION,
        feature_vector=feature_vector,
    )

    search_rows = db.get_reference_search_rows(feature_version=MATCH_FEATURE_VERSION)
    assert len(search_rows) == 1
    assert search_rows[0]["id"] == ref_id
    assert search_rows[0]["feature_vector"].dtype == np.float32
    assert np.allclose(search_rows[0]["feature_vector"], feature_vector)

    hydrated = db.get_reference_spectrum_by_id(ref_id)
    assert hydrated is not None
    assert np.allclose(hydrated["wavenumbers"], wn)
    assert np.allclose(hydrated["intensities"], ints)
    db.close()


# ---------------------------------------------------------------------------
# Similarity functions
# ---------------------------------------------------------------------------


def test_cosine_similarity_identical():
    from matching.similarity import cosine_similarity

    v = np.array([1.0, 2.0, 3.0])
    assert cosine_similarity(v, v) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal():
    from matching.similarity import cosine_similarity

    a = np.array([1.0, 0.0])
    b = np.array([0.0, 1.0])
    assert cosine_similarity(a, b) == pytest.approx(0.0)


def test_cosine_similarity_zero_vector():
    from matching.similarity import cosine_similarity

    a = np.zeros(5)
    b = np.ones(5)
    assert cosine_similarity(a, b) == pytest.approx(0.0)


def test_cosine_similarity_clipped_non_negative():
    from matching.similarity import cosine_similarity

    # Anti-parallel vectors: score should be clipped to 0, not go negative
    a = np.array([1.0, 0.0])
    b = np.array([-1.0, 0.0])
    assert cosine_similarity(a, b) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# SearchEngine
# ---------------------------------------------------------------------------


def test_search_engine_empty_returns_empty():
    from matching.search_engine import SearchEngine

    engine = SearchEngine()
    engine.load_references([])
    wn = np.linspace(400.0, 4000.0, 100)
    results = engine.search(wn, np.ones(100))
    assert results == []


def test_search_engine_finds_identical_spectrum(tmp_path):
    """The best match for a query should be its own reference entry."""
    from matching.search_engine import SearchEngine

    wn = np.linspace(400.0, 4000.0, 3601)
    query_ints = _gaussian(wn, 1700.0)
    noise_ints = _gaussian(wn, 1000.0)

    refs = [
        {
            "id": 1,
            "name": "Target",
            "wavenumbers": wn,
            "intensities": query_ints,
            "description": "",
        },
        {"id": 2, "name": "Noise", "wavenumbers": wn, "intensities": noise_ints, "description": ""},
    ]
    engine = SearchEngine()
    engine.load_references(refs)
    results = engine.search(wn, query_ints, top_n=2)
    assert results[0].name == "Target"
    assert results[0].score > results[1].score


def test_search_engine_top_n_limit():
    from matching.search_engine import SearchEngine

    wn = np.linspace(400.0, 4000.0, 100)
    refs = [
        {
            "id": i,
            "name": f"Ref{i}",
            "wavenumbers": wn,
            "intensities": np.random.default_rng(i).random(100),
            "description": "",
        }
        for i in range(20)
    ]
    engine = SearchEngine()
    engine.load_references(refs)
    results = engine.search(wn, np.ones(100), top_n=5)
    assert len(results) == 5


def test_search_engine_results_sorted_descending():
    from matching.search_engine import SearchEngine

    wn = np.linspace(400.0, 4000.0, 100)
    refs = [
        {
            "id": i,
            "name": f"Ref{i}",
            "wavenumbers": wn,
            "intensities": np.random.default_rng(i).random(100),
            "description": "",
        }
        for i in range(5)
    ]
    engine = SearchEngine()
    engine.load_references(refs)
    results = engine.search(wn, np.ones(100))
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_search_engine_n_references():
    from matching.search_engine import SearchEngine

    wn = np.linspace(400.0, 4000.0, 100)
    refs = [
        {
            "id": i,
            "name": f"R{i}",
            "wavenumbers": wn,
            "intensities": np.ones(100),
            "description": "",
        }
        for i in range(3)
    ]
    engine = SearchEngine()
    engine.load_references(refs)
    assert engine.n_references == 3


def test_search_engine_reuses_cached_reference_vectors(monkeypatch):
    from matching.search_engine import SearchEngine

    calls: list[tuple[int, str | None]] = []

    def _fake_prepare(wavenumbers, intensities, grid, y_unit=None):
        calls.append((len(wavenumbers), None if y_unit is None else str(y_unit)))
        return np.full_like(grid, float(len(calls)), dtype=np.float64)

    monkeypatch.setattr("matching.search_engine.prepare_for_matching", _fake_prepare)

    wn = np.linspace(400.0, 4000.0, 10)
    refs = [
        {
            "id": 1,
            "name": "Ref1",
            "wavenumbers": wn,
            "intensities": np.ones_like(wn),
            "description": "",
            "y_unit": "Absorbance",
        },
        {
            "id": 2,
            "name": "Ref2",
            "wavenumbers": wn,
            "intensities": np.ones_like(wn) * 2,
            "description": "",
            "y_unit": "Transmittance",
        },
    ]
    engine = SearchEngine()

    engine.load_references(refs)
    assert len(calls) == 2

    engine.load_references(refs)
    assert len(calls) == 2

    updated_refs = [dict(ref) for ref in refs]
    updated_refs[1]["y_unit"] = "Absorbance"
    engine.load_references(updated_refs)
    assert len(calls) == 3

    engine.clear_cache()
    engine.load_references(refs)
    assert len(calls) == 5


def test_search_engine_reranks_close_candidates_on_fine_grid():
    from matching.search_engine import SearchEngine

    wn = np.linspace(400.0, 4000.0, 3601)

    def _narrow_gaussian(center: float) -> np.ndarray:
        return np.exp(-0.5 * ((wn - center) / 1.5) ** 2)

    query = _narrow_gaussian(1712.0)
    target = _narrow_gaussian(1710.0)
    distractor = _narrow_gaussian(1709.5)

    refs = [
        {
            "id": 1,
            "name": "target",
            "wavenumbers": wn,
            "intensities": target,
            "y_unit": "Absorbance",
        },
        {
            "id": 2,
            "name": "distractor",
            "wavenumbers": wn,
            "intensities": distractor,
            "y_unit": "Absorbance",
        },
    ]
    engine = SearchEngine()
    engine.load_references(refs)

    coarse_results = engine.search(wn, query, top_n=2, query_y_unit="Absorbance")
    assert coarse_results[0].name == "distractor"

    reranked = engine.rerank_candidates(
        wn,
        query,
        refs,
        query_y_unit="Absorbance",
        coarse_scores={result.ref_id: result.score for result in coarse_results},
    )

    assert reranked[0].name == "target"
    assert reranked[0].score > reranked[1].score


def test_search_engine_real_fixture_exact_match_has_meaningful_gap():
    """Real reference spectra should not collapse into indistinguishable near-1.0 scores."""
    from pathlib import Path

    from file_io.format_registry import FormatRegistry
    from matching.search_engine import SearchEngine

    folder = Path(__file__).resolve().parent / "fixtures/reference library_1"
    fmt = FormatRegistry()
    references = []
    for idx, path in enumerate(sorted(folder.glob("*.SPA")), start=1):
        spectrum = fmt.read(path)
        references.append(
            {
                "id": idx,
                "name": path.stem,
                "wavenumbers": spectrum.wavenumbers,
                "intensities": spectrum.intensities,
                "description": "",
                "y_unit": spectrum.y_unit.value,
            }
        )

    query = fmt.read(folder / "FER60-SE.SPA")
    engine = SearchEngine()
    engine.load_references(references)
    results = engine.search(
        query.wavenumbers,
        query.intensities,
        top_n=3,
        query_y_unit=query.y_unit,
    )

    assert results[0].name == "FER60-SE"
    assert results[0].score == pytest.approx(1.0)
    assert results[1].score < 0.9
