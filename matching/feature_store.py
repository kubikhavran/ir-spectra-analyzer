"""Persistent feature helpers for spectral-library search."""

from __future__ import annotations

import numpy as np

from matching.preprocessing import prepare_for_matching

# Coarser grid than the original 1 cm^-1 matching path. This keeps the
# indexed feature vectors compact enough for large in-memory library matrices.
SEARCH_GRID = np.arange(400.0, 4001.0, 8.0, dtype=np.float64)
MATCH_FEATURE_VERSION = 1


def compute_search_vector(
    wavenumbers: np.ndarray,
    intensities: np.ndarray,
    *,
    y_unit: object | None = None,
) -> np.ndarray:
    """Return the normalized search feature vector for a spectrum."""
    vector = prepare_for_matching(
        wavenumbers,
        intensities,
        SEARCH_GRID,
        y_unit=y_unit,
    )
    return np.asarray(vector, dtype=np.float32)


def decode_feature_vector(blob: bytes) -> np.ndarray:
    """Decode a stored feature-vector BLOB into a writable float32 ndarray."""
    return np.frombuffer(blob, dtype=np.float32).copy()
