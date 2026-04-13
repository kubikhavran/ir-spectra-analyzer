"""SearchEngine — Vyhledávání podobných spekter v databázi."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from matching.preprocessing import prepare_for_matching
from matching.similarity import STANDARD_GRID, cosine_similarity


@dataclass
class MatchResult:
    """Single spectral match result.

    Attributes:
        ref_id: Reference spectrum database ID.
        name: Reference spectrum name.
        score: Cosine similarity score [0, 1].
        description: Optional reference description.
    """

    ref_id: int
    name: str
    score: float
    description: str = ""


class SearchEngine:
    """Spectral database search engine.

    Usage:
        engine = SearchEngine()
        engine.load_references(db.get_reference_spectra())
        results = engine.search(query_wavenumbers, query_intensities, top_n=10)
    """

    def __init__(self, grid: np.ndarray = STANDARD_GRID) -> None:
        self._grid = grid
        self._references: list[dict] = []
        self._ref_vectors: list[np.ndarray] = []
        self._vector_cache: dict[tuple[int, str], np.ndarray] = {}

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
            cache_key = self._cache_key_for_ref(ref)
            if cache_key not in self._vector_cache:
                self._vector_cache[cache_key] = prepare_for_matching(
                    ref["wavenumbers"],
                    ref["intensities"],
                    self._grid,
                    y_unit=ref.get("y_unit"),
                )
            self._ref_vectors.append(self._vector_cache[cache_key])

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

        query_vec = prepare_for_matching(
            query_wavenumbers,
            query_intensities,
            self._grid,
            y_unit=query_y_unit,
        )

        scored: list[MatchResult] = []
        for ref, ref_vec in zip(self._references, self._ref_vectors, strict=True):
            score = cosine_similarity(query_vec, ref_vec)
            scored.append(
                MatchResult(
                    ref_id=ref["id"],
                    name=ref["name"],
                    score=score,
                    description=ref.get("description", ""),
                )
            )

        scored.sort(key=lambda r: r.score, reverse=True)
        if top_n is None:
            return scored
        return scored[:top_n]

    @property
    def n_references(self) -> int:
        """Number of loaded reference spectra."""
        return len(self._references)

    def clear_cache(self) -> None:
        """Drop cached preprocessed reference vectors."""
        self._vector_cache.clear()

    @staticmethod
    def _cache_key_for_ref(ref: dict) -> tuple[int, str]:
        """Return the cache key for a reference spectrum."""
        y_unit = getattr(ref.get("y_unit"), "value", ref.get("y_unit", ""))
        return int(ref["id"]), str(y_unit)
