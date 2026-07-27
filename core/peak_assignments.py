"""Shared formatting helpers for exported peak-assignment tables."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from core.peak import Peak

if TYPE_CHECKING:
    from core.project import Project
    from core.spectrum import Spectrum


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


def collect_export_metadata(
    project: Project | None,
    spectrum: Spectrum | None,
) -> list[tuple[str, str]]:
    """Build ordered (label, value) metadata rows shared by CSV and XLSX exports.

    Mirrors exactly the header block shown on the PDF report's second page:
    sample, file, operator, instrument, client, order, acquisition time,
    resolution, comment, Y unit and X range. Empty fields are omitted.
    """
    rows: list[tuple[str, str]] = []

    def _add(label: str, value: object) -> None:
        if value is None:
            return
        text = str(value).strip()
        if text:
            rows.append((label, text))

    metadata = getattr(project, "metadata", None)
    extra = getattr(spectrum, "extra_metadata", {}) or {}
    meta_extra = getattr(metadata, "extra", {}) or {}

    file_name = getattr(metadata, "file_name", "") or ""
    # "Sample" is the spectrum title; "File" is the measurement file identifier.
    sample_name = getattr(metadata, "title", "") or getattr(spectrum, "title", "") or ""
    project_name = getattr(project, "name", "") or ""
    _add("Sample", sample_name)
    _add("File", file_name or project_name)
    _add("Operator", getattr(metadata, "operator", ""))
    _add(
        "Instrument",
        getattr(metadata, "instrument", "") or extra.get("instrument_serial"),
    )
    _add("Client", meta_extra.get("omnic_client") or extra.get("omnic_custom_info_2"))
    _add("Order", meta_extra.get("omnic_order") or extra.get("omnic_custom_info_1"))

    acquired_at = getattr(metadata, "acquired_at", None) or getattr(spectrum, "acquired_at", None)
    if acquired_at is not None:
        _add("Acquired", acquired_at.strftime("%Y-%m-%d %H:%M"))

    resolution = getattr(metadata, "resolution", None)
    if resolution is None:
        resolution = extra.get("resolution_cm")
    if resolution is not None:
        try:
            _add("Resolution (cm⁻¹)", f"{float(resolution):.3f}")
        except (TypeError, ValueError):
            _add("Resolution (cm⁻¹)", resolution)

    _add("Comment", getattr(metadata, "comments", "") or extra.get("omnic_comment"))

    if spectrum is not None:
        _add("Y unit", spectrum.y_unit.value)
        try:
            wavenumbers = list(spectrum.wavenumbers)
            if wavenumbers:
                x_lo, x_hi = float(min(wavenumbers)), float(max(wavenumbers))
                _add("X range (cm⁻¹)", f"{max(x_lo, x_hi):.0f} – {min(x_lo, x_hi):.0f}")
        except (TypeError, ValueError):
            pass

    return rows


def build_peak_assignment_rows(
    peaks: Sequence[Peak], *, is_dip_spectrum: bool, include_unassigned: bool = False
) -> list[PeakAssignmentRow]:
    """Build export rows that match the PDF peak-assignment table."""
    selected_peaks = sorted(
        (peak for peak in peaks if include_unassigned or peak_has_assignment(peak)),
        key=lambda peak: peak.position,
        reverse=True,
    )
    intensity_labels = classify_peak_intensities(selected_peaks, is_dip_spectrum=is_dip_spectrum)
    return [
        PeakAssignmentRow(
            peak=peak,
            position=int(round(peak.position)),
            intensity=peak.intensity,
            intensity_label=intensity_labels.get(id(peak), ""),
            assignment=peak_assignment_text(peak),
        )
        for peak in selected_peaks
    ]
