"""Tests for read-only consensus interpretation analysis."""

from __future__ import annotations

from matching.search_engine import MatchResult


def _make_band(
    *,
    band_id: str,
    label: str,
    confidence: float,
    role: str = "supporting",
    range_min: float = 2200.0,
    range_max: float = 2270.0,
    suggested_preset_names: tuple[str, ...] = (),
):
    from core.functional_groups import DiagnosticBandMatch

    return DiagnosticBandMatch(
        band_id=band_id,
        label=label,
        range_min=range_min,
        range_max=range_max,
        role=role,
        confidence=confidence,
        presence=confidence / 100.0,
        intensity_match=0.8,
        shape_match=0.8,
        center_fit=0.8,
        matched_wavenumber=(range_min + range_max) / 2.0,
        matched_intensity=0.6,
        expected_intensity="s",
        observed_intensity_class="s",
        color="#1ABC9C",
        suggested_preset_names=suggested_preset_names,
        source_refs=(),
        source_links=(),
    )


def test_build_consensus_analysis_combines_groups_matches_and_assignments():
    from core.functional_groups import FunctionalGroupScore
    from core.peak import Peak
    from core.project import Project
    from processing.consensus_analysis import build_consensus_analysis

    peak = Peak(
        position=2245.0,
        intensity=0.9,
        vibration_labels=["ν(C≡N) –C≡N"],
        vibration_ids=[1],
    )
    result = FunctionalGroupScore(
        group_id="nitrile",
        group_name="Nitrile",
        color="#1ABC9C",
        score=72.0,
        summary="",
        bands=(
            _make_band(
                band_id="nitrile_stretch",
                label="C≡N stretch",
                confidence=81.0,
                role="required",
                suggested_preset_names=("ν(C≡N) –C≡N",),
            ),
        ),
    )
    analysis = build_consensus_analysis(
        Project(name="Consensus", peaks=[peak]),
        functional_group_results=[result],
        match_results=[MatchResult(ref_id=1, name="Nitrile standard", score=0.78)],
    )

    assert analysis.overall_score > 50.0
    assert analysis.hypotheses[0].hypothesis_id == "nitrile"
    assert "Nitrile" in analysis.headline
    assert "Nitrile standard" in analysis.headline
    assert any(
        evidence.kind == "assigned_peak"
        for evidence in analysis.hypotheses[0].supporting_evidence
    )
    assert analysis.top_matches[0].label == "Nitrile standard"


def test_build_consensus_analysis_flags_close_library_matches_as_conflict():
    from core.functional_groups import FunctionalGroupScore
    from processing.consensus_analysis import build_consensus_analysis

    analysis = build_consensus_analysis(
        None,
        functional_group_results=[
            FunctionalGroupScore(
                group_id="aromatic_ring",
                group_name="Aromatic Ring",
                color="#566573",
                score=61.0,
                summary="",
                bands=(),
            ),
            FunctionalGroupScore(
                group_id="benzene",
                group_name="Benzene",
                color="#2E86C1",
                score=56.0,
                summary="",
                bands=(),
            ),
        ],
        match_results=[
            MatchResult(ref_id=1, name="Candidate A", score=0.66),
            MatchResult(ref_id=2, name="Candidate B", score=0.63),
        ],
    )

    assert any("split" in evidence.label.lower() for evidence in analysis.conflicts)
    assert any("library matches are close" in evidence.label.lower() for evidence in analysis.conflicts)
