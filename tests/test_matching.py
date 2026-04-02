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
