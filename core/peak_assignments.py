"""Shared formatting helpers for exported peak-assignment tables."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from core.peak import Peak


@dataclass(frozen=True)
class PeakAssignmentRow:
    """One exported peak-assignment row shared by PDF/CSV/XLSX."""

    peak: Peak
    position: int
    intensity: float
    intensity_label: str
    assignment: str


def peak_has_assignment(peak: Peak) -> bool:
    """Return True when a peak has a real vibration assignment."""
    return bool(peak.vibration_labels) or peak.vibration_id is not None


def peak_assignment_text(peak: Peak) -> str:
    """Return assignment-only text without numeric fallback labels."""
    if peak.vibration_labels:
        return " / ".join(peak.vibration_labels)
    if peak.vibration_id is not None:
        return peak.label
    return ""


def classify_peak_intensities(peaks: Sequence[Peak], *, is_dip_spectrum: bool) -> dict[int, str]:
    """Return a {id(peak): label} mapping where label is 'w', 'm', 's', or 'vs'."""
    if not peaks:
        return {}

    if is_dip_spectrum:
        depths = {id(peak): max(0.0, 100.0 - peak.intensity) for peak in peaks}
    else:
        depths = {id(peak): max(0.0, peak.intensity) for peak in peaks}

    max_depth = max(depths.values()) or 1.0

    result: dict[int, str] = {}
    for peak in peaks:
        rel = depths[id(peak)] / max_depth * 100.0
        if rel >= 90.0:
            result[id(peak)] = "vs"
        elif rel >= 70.0:
            result[id(peak)] = "s"
        elif rel >= 40.0:
            result[id(peak)] = "m"
        else:
            result[id(peak)] = "w"
    return result


def build_peak_assignment_rows(
    peaks: Sequence[Peak], *, is_dip_spectrum: bool
) -> list[PeakAssignmentRow]:
    """Build export rows that match the PDF peak-assignment table."""
    assigned_peaks = sorted(
        (peak for peak in peaks if peak_has_assignment(peak)),
        key=lambda peak: peak.position,
        reverse=True,
    )
    intensity_labels = classify_peak_intensities(assigned_peaks, is_dip_spectrum=is_dip_spectrum)
    return [
        PeakAssignmentRow(
            peak=peak,
            position=int(round(peak.position)),
            intensity=peak.intensity,
            intensity_label=intensity_labels.get(id(peak), ""),
            assignment=peak_assignment_text(peak),
        )
        for peak in assigned_peaks
    ]
