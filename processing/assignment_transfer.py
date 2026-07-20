"""Transfer vibration assignments from a previously analysed spectrum.

Pure, Qt-free logic that maps the assigned peaks of a reference project onto the
peaks of the current spectrum by nearest wavenumber within a tolerance window,
so a repeat sample does not have to be annotated from scratch.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from core.peak import Peak


@dataclass(frozen=True)
class AssignmentTransfer:
    """One planned copy of a reference peak's assignment onto a current peak."""

    peak: Peak  # current-spectrum peak that will receive the labels
    vibration_labels: list[str]
    vibration_ids: list[int | None]
    source_position: float  # reference peak position (for reporting)


def _has_assignment(peak: Peak) -> bool:
    return bool(peak.vibration_labels) or peak.vibration_id is not None


def plan_assignment_transfer(
    current_peaks: Sequence[Peak],
    reference_peaks: Sequence[Peak],
    *,
    tolerance: float = 8.0,
    overwrite: bool = False,
) -> list[AssignmentTransfer]:
    """Plan which current peaks receive which reference assignments.

    Each assigned reference peak is matched to the nearest eligible current peak
    within ``tolerance`` cm⁻¹. Matching is greedy by distance so a peak is never
    used twice and the closest pairs win. By default already-assigned current
    peaks are left untouched.

    Args:
        current_peaks: Peaks of the spectrum being analysed (receivers).
        reference_peaks: Peaks of the matched, previously analysed project.
        tolerance: Maximum wavenumber difference (cm⁻¹) for a pair to match.
        overwrite: When False, current peaks that already have an assignment are
            skipped; when True they may be overwritten.

    Returns:
        A list of AssignmentTransfer, one per matched pair.
    """
    ref_with_labels = [peak for peak in reference_peaks if peak.vibration_labels]
    eligible_current = [peak for peak in current_peaks if overwrite or not _has_assignment(peak)]
    if not ref_with_labels or not eligible_current:
        return []

    # All candidate pairs within tolerance, closest first.
    pairs: list[tuple[float, int, int]] = []
    for ri, ref in enumerate(ref_with_labels):
        for ci, cur in enumerate(eligible_current):
            distance = abs(ref.position - cur.position)
            if distance <= tolerance:
                pairs.append((distance, ri, ci))
    pairs.sort(key=lambda item: item[0])

    used_ref: set[int] = set()
    used_cur: set[int] = set()
    transfers: list[AssignmentTransfer] = []
    for _distance, ri, ci in pairs:
        if ri in used_ref or ci in used_cur:
            continue
        used_ref.add(ri)
        used_cur.add(ci)
        ref = ref_with_labels[ri]
        transfers.append(
            AssignmentTransfer(
                peak=eligible_current[ci],
                vibration_labels=list(ref.vibration_labels),
                vibration_ids=list(ref.vibration_ids)
                if ref.vibration_ids
                else [None] * len(ref.vibration_labels),
                source_position=ref.position,
            )
        )

    # Present in the current spectrum's natural order (descending wavenumber).
    transfers.sort(key=lambda t: t.peak.position, reverse=True)
    return transfers
