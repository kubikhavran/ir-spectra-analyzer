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

    def load_references(self, references: list[dict]) -> None:
        """Load reference spectra from database rows.

        Args:
            references: List of dicts from Database.get_reference_spectra().
                        Each must have keys: id, name, wavenumbers, intensities,
                        and optionally description.
        """
        self._references = references
        self._ref_vectors = [
            prepare_for_matching(ref["wavenumbers"], ref["intensities"], self._grid)
            for ref in references
        ]

    def search(
        self,
        query_wavenumbers: np.ndarray,
        query_intensities: np.ndarray,
        top_n: int = 10,
    ) -> list[MatchResult]:
        """Search for the top-N most similar reference spectra.

        Args:
            query_wavenumbers: Query spectrum X-axis.
            query_intensities: Query spectrum Y-axis.
            top_n: Maximum number of results to return.

        Returns:
            List of MatchResult sorted by score descending.
        """
        if not self._references:
            return []

        query_vec = prepare_for_matching(query_wavenumbers, query_intensities, self._grid)

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
        return scored[:top_n]

    @property
    def n_references(self) -> int:
        """Number of loaded reference spectra."""
        return len(self._references)
