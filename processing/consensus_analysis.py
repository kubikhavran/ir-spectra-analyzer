"""Build a read-only consensus interpretation from existing analysis outputs."""

from __future__ import annotations

from collections.abc import Sequence

from core.consensus import ConsensusAnalysis, ConsensusEvidence, ConsensusHypothesis
from core.functional_groups import FunctionalGroupScore
from core.project import Project
from matching.quality import match_quality_label
from matching.search_engine import MatchResult


def build_consensus_analysis(
    project: Project | None,
    functional_group_results: Sequence[FunctionalGroupScore] = (),
    match_results: Sequence[MatchResult] = (),
) -> ConsensusAnalysis:
    """Combine current chemistry evidence into one ranked interpretation summary."""
    peaks = [] if project is None else list(project.peaks)
    top_groups = _select_top_groups(functional_group_results)
    hypotheses = tuple(
        _build_hypothesis(result, peaks, match_results[0] if match_results else None)
        for result in top_groups
    )

    confirmed = tuple(
        ConsensusEvidence(
            kind="functional_group",
            label=result.group_name,
            score=float(result.score),
            details=_feature_summary(result),
            target_id=result.group_id,
        )
        for result in functional_group_results[:6]
        if result.score >= 55.0
    )
    uncertain = tuple(
        ConsensusEvidence(
            kind="functional_group",
            label=result.group_name,
            score=float(result.score),
            details=_feature_summary(result),
            target_id=result.group_id,
        )
        for result in functional_group_results[:6]
        if 30.0 <= result.score < 55.0
    )
    top_matches = tuple(
        ConsensusEvidence(
            kind="library_match",
            label=match.name,
            score=match.score * 100.0,
            details=_match_details(match),
            target_id=int(match.ref_id),
        )
        for match in match_results[:3]
    )

    conflicts = list(_aggregate_conflicts(functional_group_results, match_results))
    if hypotheses:
        conflicts.extend(hypotheses[0].conflicting_evidence[:2])
    conflicts_tuple = tuple(conflicts[:4])

    overall_score = _overall_score(
        project,
        functional_group_results=functional_group_results,
        match_results=match_results,
        hypotheses=hypotheses,
    )
    headline = _build_headline(hypotheses, top_matches)
    summary = _build_summary(
        project,
        functional_group_results=functional_group_results,
        match_results=match_results,
        overall_score=overall_score,
    )

    return ConsensusAnalysis(
        overall_score=overall_score,
        headline=headline,
        summary=summary,
        hypotheses=hypotheses,
        confirmed_features=confirmed,
        uncertain_features=uncertain,
        conflicts=conflicts_tuple,
        top_matches=top_matches,
    )


def _select_top_groups(
    functional_group_results: Sequence[FunctionalGroupScore],
) -> list[FunctionalGroupScore]:
    if not functional_group_results:
        return []
    cutoff = max(30.0, functional_group_results[0].score - 40.0)
    return [
        result
        for result in functional_group_results[:5]
        if result.score >= cutoff
    ][:3]


def _build_hypothesis(
    result: FunctionalGroupScore,
    peaks: Sequence,
    top_match: MatchResult | None,
) -> ConsensusHypothesis:
    assignment_evidence = _assignment_evidence(result, peaks)
    supporting: list[ConsensusEvidence] = [
        ConsensusEvidence(
            kind="matched_band",
            label=band.label,
            score=float(band.confidence),
            details=f"{band.range_min:.0f}–{band.range_max:.0f} cm-1",
            target_id=result.group_id,
        )
        for band in result.matched_bands[:3]
    ]
    supporting.extend(assignment_evidence[:2])
    if top_match is not None and top_match.score >= 0.55:
        supporting.append(
            ConsensusEvidence(
                kind="library_match",
                label=f"Library hit: {top_match.name}",
                score=top_match.score * 100.0,
                details=_match_details(top_match),
                target_id=int(top_match.ref_id),
            )
        )

    conflicting = [
        ConsensusEvidence(
            kind="missing_band",
            label=band.label,
            score=max(0.0, 100.0 - float(band.confidence)),
            details=f"Expected in {band.range_min:.0f}–{band.range_max:.0f} cm-1",
            target_id=result.group_id,
        )
        for band in result.missing_bands[:3]
    ]

    checks: list[ConsensusEvidence] = [
        ConsensusEvidence(
            kind="recommended_check",
            label=f"Inspect {band.range_min:.0f}–{band.range_max:.0f} cm-1",
            score=100.0 - float(band.confidence),
            details=band.label,
            target_id=result.group_id,
        )
        for band in result.missing_bands[:2]
    ]
    if not assignment_evidence and result.suggested_bands:
        band = result.suggested_bands[0]
        checks.append(
            ConsensusEvidence(
                kind="recommended_check",
                label=f"Assign a peak in {band.range_min:.0f}–{band.range_max:.0f} cm-1",
                score=float(band.confidence),
                details=band.label,
                target_id=result.group_id,
            )
        )

    score = _hypothesis_score(
        result,
        assignment_hits=len(assignment_evidence),
        missing_required=len(result.missing_bands),
    )
    return ConsensusHypothesis(
        hypothesis_id=result.group_id,
        title=result.group_name,
        score=score,
        summary=_feature_summary(result),
        supporting_evidence=tuple(supporting),
        conflicting_evidence=tuple(conflicting),
        recommended_checks=tuple(checks[:3]),
    )


def _assignment_evidence(result: FunctionalGroupScore, peaks: Sequence) -> list[ConsensusEvidence]:
    evidence: list[ConsensusEvidence] = []
    for peak in peaks:
        if not getattr(peak, "vibration_labels", ()):
            continue
        peak_labels = set(getattr(peak, "vibration_labels", ()))
        for band in result.suggested_bands:
            if not band.covers_wavenumber(float(getattr(peak, "position", 0.0))):
                continue
            overlap = peak_labels.intersection(band.suggested_preset_names)
            if not overlap:
                continue
            preset_name = sorted(overlap)[0]
            evidence.append(
                ConsensusEvidence(
                    kind="assigned_peak",
                    label=f"Peak {peak.position:.0f} cm-1",
                    score=float(band.confidence),
                    details=f'Assigned "{preset_name}" and aligns with {band.label}',
                    target_id=result.group_id,
                )
            )
            break
    return evidence


def _hypothesis_score(
    result: FunctionalGroupScore,
    *,
    assignment_hits: int,
    missing_required: int,
) -> float:
    support_bonus = min(len(result.matched_bands) * 4.0, 12.0)
    assignment_bonus = min(float(assignment_hits) * 8.0, 16.0)
    missing_penalty = min(float(missing_required) * 7.0, 21.0)
    return max(0.0, min(result.score + support_bonus + assignment_bonus - missing_penalty, 100.0))


def _aggregate_conflicts(
    functional_group_results: Sequence[FunctionalGroupScore],
    match_results: Sequence[MatchResult],
) -> tuple[ConsensusEvidence, ...]:
    conflicts: list[ConsensusEvidence] = []
    if len(functional_group_results) >= 2:
        gap = functional_group_results[0].score - functional_group_results[1].score
        if gap < 8.0:
            conflicts.append(
                ConsensusEvidence(
                    kind="conflict",
                    label="Chemistry evidence is split",
                    score=100.0 - gap * 10.0,
                    details=(
                        f"{functional_group_results[0].group_name} vs "
                        f"{functional_group_results[1].group_name}"
                    ),
                )
            )
    if len(match_results) >= 2:
        gap = (match_results[0].score - match_results[1].score) * 100.0
        if gap < 5.0:
            conflicts.append(
                ConsensusEvidence(
                    kind="conflict",
                    label="Top library matches are close",
                    score=100.0 - gap * 10.0,
                    details=f"{match_results[0].name} vs {match_results[1].name}",
                    target_id=int(match_results[0].ref_id),
                )
            )
    return tuple(conflicts)


def _overall_score(
    project: Project | None,
    *,
    functional_group_results: Sequence[FunctionalGroupScore],
    match_results: Sequence[MatchResult],
    hypotheses: Sequence[ConsensusHypothesis],
) -> float:
    fg_component = functional_group_results[0].score if functional_group_results else 0.0
    match_component = match_results[0].score * 100.0 if match_results else 0.0
    peaks = [] if project is None else list(project.peaks)
    assigned_peak_count = sum(1 for peak in peaks if getattr(peak, "vibration_labels", ()))
    assignment_component = (assigned_peak_count / len(peaks) * 100.0) if peaks else 0.0

    score = 0.45 * fg_component + 0.35 * match_component + 0.20 * assignment_component
    if hypotheses:
        score -= min(len(hypotheses[0].conflicting_evidence) * 6.0, 18.0)
    if len(functional_group_results) >= 2 and functional_group_results[0].score - functional_group_results[1].score < 8.0:
        score -= 6.0
    if len(match_results) >= 2 and (match_results[0].score - match_results[1].score) < 0.05:
        score -= 6.0
    return max(0.0, min(score, 100.0))


def _build_headline(
    hypotheses: Sequence[ConsensusHypothesis],
    top_matches: Sequence[ConsensusEvidence],
) -> str:
    if hypotheses and top_matches:
        return (
            f"Most consistent picture: {hypotheses[0].title} "
            f"(supported by library match {top_matches[0].label})"
        )
    if hypotheses:
        return f"Most consistent picture: {hypotheses[0].title}"
    if top_matches:
        return f"Best spectral match: {top_matches[0].label}"
    return "Not enough evidence for a consensus interpretation yet."


def _build_summary(
    project: Project | None,
    *,
    functional_group_results: Sequence[FunctionalGroupScore],
    match_results: Sequence[MatchResult],
    overall_score: float,
) -> str:
    peak_count = 0 if project is None else len(project.peaks)
    assigned_peak_count = 0 if project is None else sum(
        1 for peak in project.peaks if getattr(peak, "vibration_labels", ())
    )
    top_group = functional_group_results[0] if functional_group_results else None
    top_match = match_results[0] if match_results else None
    parts = [f"Interpretation confidence {overall_score:.0f}%."]
    if top_group is not None:
        parts.append(f"Top chemistry evidence: {top_group.group_name} ({top_group.score:.1f}%).")
    if top_match is not None:
        parts.append(f"Top library hit: {top_match.name} ({top_match.score * 100.0:.1f}%).")
    if peak_count:
        parts.append(f"Assigned peaks: {assigned_peak_count}/{peak_count}.")
    return " ".join(parts)


def _feature_summary(result: FunctionalGroupScore) -> str:
    matched = len(result.matched_bands)
    missing = len(result.missing_bands)
    if missing:
        return f"{matched} matched bands, {missing} missing required"
    return f"{matched} matched bands"


def _match_details(match: MatchResult) -> str:
    quality = match_quality_label(match.score)
    if match.description:
        return f"{quality} spectral match. {match.description}"
    return f"{quality} spectral match."
