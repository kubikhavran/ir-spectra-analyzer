"""SearchEngine — Vyhledávání podobných spekter v databázi."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from matching.feature_store import (
    SEARCH_GRID,
    compute_fingerprint_vector,
    compute_rerank_vector,
    compute_search_vector,
)
from matching.preprocessing import FINGERPRINT_RANGE, prepare_for_matching


@dataclass
class MatchResult:
    """Single spectral match result.

    Attributes:
        ref_id: Reference spectrum database ID.
        name: Reference spectrum name.
        score: Whole-spectrum similarity score [0, 1].
        description: Optional reference description.
        fingerprint_score: Similarity over the skeleton region only [0, 1]. A
            high fingerprint score with a clearly lower whole-spectrum score is
            the signature of the same compound carrying a different substituent.
    """

    ref_id: int
    name: str
    score: float
    description: str = ""
    fingerprint_score: float = 0.0

    @property
    def ranking_score(self) -> float:
        """Score used for ordering: the better of the two views."""
        return max(float(self.score), float(self.fingerprint_score))


class SearchEngine:
    """Spectral database search engine.

    Usage:
        engine = SearchEngine()
        engine.load_references(db.get_reference_spectra())
        results = engine.search(query_wavenumbers, query_intensities, top_n=10)
    """

    def __init__(self, grid: np.ndarray = SEARCH_GRID) -> None:
        self._grid = grid
        self._references: list[dict] = []
        self._ref_vectors: list[np.ndarray] = []
        self._ref_matrix: np.ndarray | None = None
        self._fingerprint_matrix: np.ndarray | None = None
        self._vector_cache: dict[tuple[int, str], np.ndarray] = {}
        self._rerank_vector_cache: dict[tuple[int, str], np.ndarray] = {}
        self._fingerprint_vector_cache: dict[tuple[int, str], np.ndarray] = {}

    def _fingerprint_mask(self, length: int) -> np.ndarray | None:
        """Return the boolean mask selecting the skeleton region of a vector.

        Feature vectors are the preprocessed signal normalized as a whole, so
        slicing one and renormalizing yields exactly the vector that would come
        from preprocessing with ``region=FINGERPRINT_RANGE``. That keeps the
        skeleton score free — no second vector has to be stored per reference.
        """
        if self._grid.size != length:
            return None
        lo, hi = min(FINGERPRINT_RANGE), max(FINGERPRINT_RANGE)
        mask = (self._grid >= lo) & (self._grid <= hi)
        return mask if mask.any() else None

    @staticmethod
    def _normalize_rows(matrix: np.ndarray) -> np.ndarray:
        """L2-normalize each row, leaving all-zero rows untouched."""
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        return matrix / np.where(norms > 0.0, norms, 1.0)

    def load_references(self, references: list[dict]) -> None:
        """Load reference spectra from database rows.

        Args:
            references: List of dicts from Database.get_reference_spectra().
                        Each must have keys: id, name, wavenumbers, intensities,
                        and optionally description.
        """
        self._references = references
        self._ref_vectors = []
        for ref in references:
            feature_vector = ref.get("feature_vector")
            if isinstance(feature_vector, np.ndarray):
                vector = np.asarray(feature_vector, dtype=np.float32)
            else:
                cache_key = self._cache_key_for_ref(ref)
                if cache_key not in self._vector_cache:
                    self._vector_cache[cache_key] = np.asarray(
                        prepare_for_matching(
                            ref["wavenumbers"],
                            ref["intensities"],
                            self._grid,
                            y_unit=ref.get("y_unit"),
                        ),
                        dtype=np.float32,
                    )
                vector = self._vector_cache[cache_key]
            self._ref_vectors.append(vector)

        if self._ref_vectors:
            self._ref_matrix = np.vstack(self._ref_vectors).astype(np.float32, copy=False)
            mask = self._fingerprint_mask(self._ref_matrix.shape[1])
            self._fingerprint_matrix = (
                self._normalize_rows(self._ref_matrix[:, mask]) if mask is not None else None
            )
        else:
            self._ref_matrix = None
            self._fingerprint_matrix = None

    def search(
        self,
        query_wavenumbers: np.ndarray,
        query_intensities: np.ndarray,
        top_n: int | None = 10,
        query_y_unit: object | None = None,
    ) -> list[MatchResult]:
        """Search for the top-N most similar reference spectra.

        Args:
            query_wavenumbers: Query spectrum X-axis.
            query_intensities: Query spectrum Y-axis.
            top_n: Maximum number of results to return. `None` returns all results.

        Returns:
            List of MatchResult sorted by score descending.
        """
        if not self._references:
            return []

        query_vec = (
            compute_search_vector(
                query_wavenumbers,
                query_intensities,
                y_unit=query_y_unit,
            )
            if np.array_equal(self._grid, SEARCH_GRID)
            else np.asarray(
                prepare_for_matching(
                    query_wavenumbers,
                    query_intensities,
                    self._grid,
                    y_unit=query_y_unit,
                ),
                dtype=np.float32,
            )
        )

        scores = self._compute_scores(query_vec)
        fingerprint_scores = self._compute_fingerprint_scores(query_vec)
        # Shortlist on the better of the two views, so a compound whose skeleton
        # matches but whose substituent differs is not dropped before reranking.
        ranking = np.maximum(scores, fingerprint_scores)
        if top_n is None or top_n >= len(ranking):
            order = np.argsort(ranking)[::-1]
        else:
            keep = max(int(top_n), 1)
            candidate_idx = np.argpartition(ranking, -keep)[-keep:]
            order = candidate_idx[np.argsort(ranking[candidate_idx])[::-1]]

        return [
            MatchResult(
                ref_id=self._references[idx]["id"],
                name=self._references[idx]["name"],
                score=float(scores[idx]),
                description=self._references[idx].get("description", ""),
                fingerprint_score=float(fingerprint_scores[idx]),
            )
            for idx in order
        ]

    @property
    def n_references(self) -> int:
        """Number of loaded reference spectra."""
        return len(self._references)

    def clear_cache(self) -> None:
        """Drop cached preprocessed reference vectors."""
        self._vector_cache.clear()
        self._rerank_vector_cache.clear()
        self._fingerprint_vector_cache.clear()
        self._ref_matrix = None
        self._fingerprint_matrix = None

    def rerank_candidates(
        self,
        query_wavenumbers: np.ndarray,
        query_intensities: np.ndarray,
        candidates: list[dict],
        *,
        query_y_unit: object | None = None,
        coarse_scores: dict[int, float] | None = None,
    ) -> list[MatchResult]:
        """Refine a shortlist using a finer 1 cm⁻¹ feature grid."""
        if not candidates:
            return []

        query_vec = compute_rerank_vector(
            query_wavenumbers,
            query_intensities,
            y_unit=query_y_unit,
        )
        query_fp = compute_fingerprint_vector(
            query_wavenumbers,
            query_intensities,
            y_unit=query_y_unit,
        )
        reranked: list[MatchResult] = []
        for candidate in candidates:
            cache_key = self._cache_key_for_ref(candidate)
            if cache_key not in self._rerank_vector_cache:
                self._rerank_vector_cache[cache_key] = compute_rerank_vector(
                    candidate["wavenumbers"],
                    candidate["intensities"],
                    y_unit=candidate.get("y_unit"),
                )
            if cache_key not in self._fingerprint_vector_cache:
                self._fingerprint_vector_cache[cache_key] = compute_fingerprint_vector(
                    candidate["wavenumbers"],
                    candidate["intensities"],
                    y_unit=candidate.get("y_unit"),
                )
            fine_score = self._score_pair(query_vec, self._rerank_vector_cache[cache_key])
            coarse_score = (
                None if coarse_scores is None else coarse_scores.get(int(candidate["id"]))
            )
            score = (
                fine_score
                if coarse_score is None
                else self._combine_scores(float(coarse_score), fine_score)
            )
            reranked.append(
                MatchResult(
                    ref_id=int(candidate["id"]),
                    name=str(candidate["name"]),
                    score=score,
                    description=str(candidate.get("description", "")),
                    fingerprint_score=self._score_pair(
                        query_fp, self._fingerprint_vector_cache[cache_key]
                    ),
                )
            )

        reranked.sort(key=lambda result: result.ranking_score, reverse=True)
        return reranked

    def _compute_fingerprint_scores(self, query_vec: np.ndarray) -> np.ndarray:
        """Return skeleton-region cosine scores, or zeros when unavailable."""
        mask = self._fingerprint_mask(query_vec.size)
        if self._fingerprint_matrix is None or mask is None:
            return np.zeros(len(self._references), dtype=np.float32)
        query_fp = query_vec[mask].astype(np.float32, copy=False)
        norm = float(np.linalg.norm(query_fp))
        if norm == 0.0:
            return np.zeros(len(self._references), dtype=np.float32)
        return np.clip(self._fingerprint_matrix @ (query_fp / norm), 0.0, 1.0)

    def _compute_scores(self, query_vec: np.ndarray) -> np.ndarray:
        """Return cosine scores against the loaded reference matrix."""
        if self._ref_matrix is not None:
            return np.clip(self._ref_matrix @ query_vec.astype(np.float32, copy=False), 0.0, 1.0)

        scored = [
            float(
                np.clip(
                    np.dot(query_vec, ref_vec)
                    / max(
                        float(np.linalg.norm(query_vec)) * float(np.linalg.norm(ref_vec)),
                        1e-12,
                    ),
                    0.0,
                    1.0,
                )
            )
            for ref_vec in self._ref_vectors
        ]
        return np.asarray(scored, dtype=np.float32)

    @staticmethod
    def _score_pair(query_vec: np.ndarray, ref_vec: np.ndarray) -> float:
        """Return a clipped cosine score for one normalized vector pair."""
        return float(
            np.clip(
                np.dot(
                    query_vec.astype(np.float32, copy=False), ref_vec.astype(np.float32, copy=False)
                ),
                0.0,
                1.0,
            )
        )

    @staticmethod
    def _combine_scores(coarse_score: float, fine_score: float) -> float:
        """Blend coarse shortlist scoring with fine-grid reranking."""
        return float(np.clip(coarse_score * 0.35 + fine_score * 0.65, 0.0, 1.0))

    @staticmethod
    def _cache_key_for_ref(ref: dict) -> tuple[int, str]:
        """Return the cache key for a reference spectrum."""
        y_unit = getattr(ref.get("y_unit"), "value", ref.get("y_unit", ""))
        return int(ref["id"]), str(y_unit)
