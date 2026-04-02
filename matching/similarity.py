"""
Similarity — Algoritmy podobnosti spekter.

Zodpovědnost:
- Pearsonova korelace
- Euklidovská vzdálenost
- Spectral Angle Mapper (SAM)
- Normalizovaná křížová korelace (NCC)

Plánováno pro v0.3.0.
"""

from __future__ import annotations

import numpy as np


def pearson_correlation(a: np.ndarray, b: np.ndarray) -> float:
    """Compute Pearson correlation coefficient between two spectra."""
    return float(np.corrcoef(a, b)[0, 1])


def spectral_angle_mapper(a: np.ndarray, b: np.ndarray) -> float:
    """Compute Spectral Angle Mapper (SAM) similarity score [0, 1].

    Returns:
        Score where 1 = identical spectra, 0 = orthogonal spectra.
    """
    dot = float(np.dot(a, b))
    norm_a = float(np.linalg.norm(a))
    norm_b = float(np.linalg.norm(b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    cos_angle = dot / (norm_a * norm_b)
    return float(1.0 - np.arccos(np.clip(cos_angle, -1.0, 1.0)) / np.pi)


# Standard matching grid (400 to 4000 cm⁻¹, 1 cm⁻¹ step)
STANDARD_GRID = np.arange(400.0, 4001.0, 1.0)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two already-aligned spectral vectors.

    Args:
        a: First intensity vector.
        b: Second intensity vector (same length as a).

    Returns:
        Cosine similarity in [0, 1]. 1 = identical direction, 0 = orthogonal.
    """
    norm_a = float(np.linalg.norm(a))
    norm_b = float(np.linalg.norm(b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.clip(np.dot(a, b) / (norm_a * norm_b), 0.0, 1.0))
