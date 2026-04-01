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
