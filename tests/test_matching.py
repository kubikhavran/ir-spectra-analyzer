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


@pytest.mark.parametrize("descending", [False, True])
def test_matching_partial_range_flat_transmittance_has_no_artificial_cutoff_band(descending):
    """Out-of-range target points must continue the baseline, not become zero-percent T."""
    from core.spectrum import SpectralUnit
    from matching.preprocessing import prepare_for_matching

    source_axis = np.linspace(650.0, 4000.0, 3351)
    if descending:
        source_axis = source_axis[::-1]
    target_axis = np.linspace(400.0, 4000.0, 3601)
    flat_transmittance = np.full_like(source_axis, 100.0)

    feature = prepare_for_matching(
        source_axis,
        flat_transmittance,
        target_axis,
        y_unit=SpectralUnit.TRANSMITTANCE,
    )

    assert np.allclose(feature, 0.0, atol=1e-12)


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
    # On the 8 cm⁻¹ search grid these two bands are nearly indistinguishable —
    # that is what the fine-grid rerank exists to resolve.
    coarse_by_name = {result.name: result.score for result in coarse_results}
    assert abs(coarse_by_name["target"] - coarse_by_name["distractor"]) < 0.01

    reranked = engine.rerank_candidates(
        wn,
        query,
        refs,
        query_y_unit="Absorbance",
        coarse_scores={result.ref_id: result.score for result in coarse_results},
    )

    assert reranked[0].name == "target"
    assert reranked[0].score > reranked[1].score


@pytest.mark.lab_fixtures
def test_search_engine_real_fixture_exact_match_has_meaningful_gap():
    """Real reference spectra should not collapse into indistinguishable near-1.0 scores."""
    from pathlib import Path

    from file_io.format_registry import FormatRegistry
    from matching.search_engine import SearchEngine

    folder = Path(__file__).resolve().parent / "fixtures/reference library_1"
    if not (folder / "FER60-SE.SPA").exists():
        pytest.skip("lab reference library is not part of the repository")
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


# ── Substituent-swap matching (fingerprint region + intensity compression) ────


def _fixture_refs(exclude: str):
    """Load every lab fixture except one as reference rows."""
    from pathlib import Path

    from file_io.spa_reader import SPAReader

    folder = Path(__file__).resolve().parent / "fixtures/reference library_1"
    rows = []
    for idx, path in enumerate(sorted(folder.glob("*.SPA")), start=1):
        if path.stem == exclude:
            continue
        spectrum = SPAReader().read(path)
        rows.append(
            {
                "id": idx,
                "name": path.stem,
                "wavenumbers": spectrum.wavenumbers,
                "intensities": spectrum.intensities,
                "y_unit": spectrum.y_unit,
            }
        )
    return rows


def test_one_dominant_extra_band_no_longer_sinks_an_otherwise_identical_spectrum():
    """Intensity compression keeps a single strong extra band from rescaling everything.

    A spectrum is normalized by its strongest band, so an azide-like band the
    reference lacks used to shrink every shared band and collapse the score.
    """
    from matching.feature_store import compute_rerank_vector
    from matching.search_engine import SearchEngine

    wn = np.arange(400.0, 4001.0, 1.0)
    shared = np.zeros_like(wn)
    for center, height in [(700.0, 0.4), (1100.0, 0.6), (1450.0, 0.35), (1600.0, 0.5)]:
        shared = shared + height * np.exp(-0.5 * ((wn - center) / 5.0) ** 2)
    with_extra = shared + 2.5 * np.exp(-0.5 * ((wn - 2100.0) / 5.0) ** 2)

    def _pre_v22_vector(intensities: np.ndarray) -> np.ndarray:
        """The metric this replaced: peak-normalized signal plus a derivative channel."""
        from scipy.signal import savgol_filter

        signal = intensities - float(np.min(intensities))
        signal = signal - savgol_filter(signal, 151, 3, mode="interp")
        signal = np.clip(signal, 0.0, None)
        signal = signal / (float(np.max(signal)) or 1.0)
        vector = np.concatenate((signal, np.gradient(signal) * 0.5))
        return vector / np.linalg.norm(vector)

    engine = SearchEngine()
    score = engine._score_pair(
        compute_rerank_vector(wn, with_extra, y_unit="Absorbance"),
        compute_rerank_vector(wn, shared, y_unit="Absorbance"),
    )
    previous = float(np.dot(_pre_v22_vector(with_extra), _pre_v22_vector(shared)))

    assert score > previous + 0.25, (
        f"expected a clear gain over the old metric (old {previous:.2f}, new {score:.2f})"
    )
    assert score > 0.7


def test_fingerprint_score_isolates_the_skeleton_region():
    """The skeleton score must ignore bands outside 400-1600 cm-1."""
    from matching.feature_store import compute_fingerprint_vector
    from matching.search_engine import SearchEngine

    wn = np.arange(400.0, 4001.0, 1.0)
    skeleton = np.zeros_like(wn)
    for center in (700.0, 1100.0, 1450.0):
        skeleton = skeleton + 0.5 * np.exp(-0.5 * ((wn - center) / 5.0) ** 2)
    plus_azide = skeleton + 2.5 * np.exp(-0.5 * ((wn - 2100.0) / 5.0) ** 2)

    engine = SearchEngine()
    fingerprint = engine._score_pair(
        compute_fingerprint_vector(wn, plus_azide, y_unit="Absorbance"),
        compute_fingerprint_vector(wn, skeleton, y_unit="Absorbance"),
    )
    assert fingerprint > 0.98, f"skeleton region must be unaffected (got {fingerprint:.3f})"


def test_search_shortlists_on_the_better_of_both_views():
    """A candidate that only agrees on the skeleton must survive the shortlist."""
    from matching.search_engine import SearchEngine

    wn = np.arange(400.0, 4001.0, 1.0)

    def _bands(centers, heights):
        out = np.zeros_like(wn)
        for center, height in zip(centers, heights, strict=True):
            out = out + height * np.exp(-0.5 * ((wn - center) / 5.0) ** 2)
        return out

    skeleton = _bands([700.0, 1100.0, 1450.0], [0.4, 0.6, 0.4])
    query = skeleton + _bands([2100.0], [2.5])  # sample carries the azide
    same_skeleton = skeleton  # reference without it
    unrelated = _bands([900.0, 1250.0, 3300.0], [0.5, 0.5, 0.5])

    engine = SearchEngine()
    engine.load_references(
        [
            {
                "id": 1,
                "name": "same skeleton",
                "wavenumbers": wn,
                "intensities": same_skeleton,
                "y_unit": "Absorbance",
            },
            {
                "id": 2,
                "name": "unrelated",
                "wavenumbers": wn,
                "intensities": unrelated,
                "y_unit": "Absorbance",
            },
        ]
    )
    results = engine.search(wn, query, top_n=2, query_y_unit="Absorbance")

    assert results[0].name == "same skeleton"
    assert results[0].fingerprint_score > results[0].score
    assert results[0].ranking_score == results[0].fingerprint_score


@pytest.mark.lab_fixtures
def test_real_substituent_pair_reaches_the_top_of_the_hit_list():
    """PAR1507-MK (OMe) must be findable for PAR1706-HA (N3).

    Before v0.22.0 this pair scored 47 % and ranked 67th of 201 references, well
    outside the 20 results the panel shows.
    """
    from pathlib import Path

    from file_io.spa_reader import SPAReader
    from matching.search_engine import SearchEngine

    folder = Path(__file__).resolve().parent / "fixtures/reference library_1"
    if not (folder / "PAR1706-HA.SPA").exists():
        pytest.skip("lab fixture pair not present")
    query = SPAReader().read(folder / "PAR1706-HA.SPA")
    references = _fixture_refs("PAR1706-HA")

    engine = SearchEngine()
    engine.load_references(references)
    shortlist = engine.search(
        query.wavenumbers, query.intensities, top_n=25, query_y_unit=query.y_unit
    )
    by_id = {row["id"]: row for row in references}
    results = engine.rerank_candidates(
        query.wavenumbers,
        query.intensities,
        [by_id[result.ref_id] for result in shortlist],
        query_y_unit=query.y_unit,
        coarse_scores={result.ref_id: result.score for result in shortlist},
    )

    names = [result.name for result in results]
    assert "PAR1507-MK" in names[:3], f"expected the pair near the top, got {names[:5]}"
    target = next(result for result in results if result.name == "PAR1507-MK")
    # The skeleton agrees better than the whole spectrum — the swap signature.
    assert target.fingerprint_score > 0.85
    # The margin used to read ~0.20 only because out-of-range grid points were
    # filled with a numeric zero: PAR1706-HA stops at 3800 cm^-1 while
    # PAR1507-MK reaches 4000, so the whole-spectrum score was pushed down by
    # that artificial edge rather than by chemistry.  With the edge-hold fill
    # the whole-spectrum score is no longer penalised and the honest margin is
    # around 0.08.
    assert target.fingerprint_score - target.score > 0.05
