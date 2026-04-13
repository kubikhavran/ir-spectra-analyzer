"""Presentation helpers for interpreting similarity scores."""

from __future__ import annotations

THRESHOLD_EXCELLENT = 0.90
THRESHOLD_STRONG = 0.70
THRESHOLD_POSSIBLE = 0.40


def match_quality_label(score: float) -> str:
    """Return a user-facing quality band for a similarity score."""
    if score >= THRESHOLD_EXCELLENT:
        return "Excellent"
    if score >= THRESHOLD_STRONG:
        return "Strong"
    if score >= THRESHOLD_POSSIBLE:
        return "Possible"
    return "Weak"


def match_quality_color(score: float) -> str:
    """Return a stable UI color for a similarity quality band."""
    quality = match_quality_label(score)
    if quality == "Excellent":
        return "#2E7D32"
    if quality == "Strong":
        return "#1565C0"
    if quality == "Possible":
        return "#E65100"
    return "#616161"
