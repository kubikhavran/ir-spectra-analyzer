"""Tests for copying vibration assignments from a matched project."""

from __future__ import annotations

from core.peak import Peak
from processing.assignment_transfer import plan_assignment_transfer


def _ref() -> list[Peak]:
    return [
        Peak(position=1712.0, intensity=0.5, vibration_labels=["ν(C=O)"], vibration_ids=[1]),
        Peak(position=2958.0, intensity=0.3, vibration_labels=["νas(CH₂)"], vibration_ids=[2]),
        Peak(position=699.0, intensity=0.4, vibration_labels=["γ(C-H)"], vibration_ids=[3]),
        Peak(position=1600.0, intensity=0.2),  # unassigned → never transferred
    ]


def test_transfer_maps_nearest_peaks_within_tolerance():
    current = [
        Peak(position=1715.0, intensity=0.5),  # 3 from 1712 → ν(C=O)
        Peak(position=2953.0, intensity=0.3),  # 5 from 2958 → νas(CH₂)
        Peak(position=705.0, intensity=0.4),  # 6 from 699 → γ(C-H)
        Peak(position=1200.0, intensity=0.2),  # no ref within ±8 → nothing
    ]
    transfers = plan_assignment_transfer(current, _ref(), tolerance=8.0)
    got = {round(t.peak.position): t.vibration_labels[0] for t in transfers}
    assert got == {1715: "ν(C=O)", 2953: "νas(CH₂)", 705: "γ(C-H)"}


def test_transfer_skips_already_assigned_by_default():
    current = [
        Peak(position=1715.0, intensity=0.5, vibration_labels=["kept"]),  # already assigned
        Peak(position=699.0, intensity=0.4),
    ]
    transfers = plan_assignment_transfer(current, _ref(), tolerance=8.0)
    positions = {round(t.peak.position) for t in transfers}
    assert positions == {699}  # 1715 left untouched


def test_transfer_overwrite_allows_reassignment():
    current = [Peak(position=1715.0, intensity=0.5, vibration_labels=["old"])]
    transfers = plan_assignment_transfer(current, _ref(), tolerance=8.0, overwrite=True)
    assert len(transfers) == 1
    assert transfers[0].vibration_labels == ["ν(C=O)"]


def test_transfer_respects_tolerance_window():
    current = [Peak(position=1730.0, intensity=0.5)]  # 18 away from 1712 → out of ±8
    assert plan_assignment_transfer(current, _ref(), tolerance=8.0) == []
    # widening the window catches it
    assert len(plan_assignment_transfer(current, _ref(), tolerance=20.0)) == 1


def test_transfer_never_reuses_a_current_peak():
    ref = [
        Peak(position=1700.0, intensity=0.5, vibration_labels=["A"], vibration_ids=[1]),
        Peak(position=1702.0, intensity=0.5, vibration_labels=["B"], vibration_ids=[2]),
    ]
    current = [Peak(position=1701.0, intensity=0.5)]  # only one peak for two ref bands
    transfers = plan_assignment_transfer(current, ref, tolerance=8.0)
    assert len(transfers) == 1  # the closer ref (1700, dist 1) wins
    assert transfers[0].vibration_labels == ["A"]
