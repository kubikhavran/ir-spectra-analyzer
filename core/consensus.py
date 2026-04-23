"""Consensus interpretation models built from multiple analysis layers."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ConsensusEvidence:
    """One supporting, conflicting, or actionable piece of interpretation evidence."""

    kind: str
    label: str
    score: float
    details: str = ""
    target_id: str | int | None = None


@dataclass(frozen=True)
class ConsensusHypothesis:
    """One ranked chemistry hypothesis in the consensus panel."""

    hypothesis_id: str
    title: str
    score: float
    summary: str
    supporting_evidence: tuple[ConsensusEvidence, ...] = ()
    conflicting_evidence: tuple[ConsensusEvidence, ...] = ()
    recommended_checks: tuple[ConsensusEvidence, ...] = ()


@dataclass(frozen=True)
class ConsensusAnalysis:
    """Combined interpretation summary for the current project state."""

    overall_score: float
    headline: str
    summary: str
    hypotheses: tuple[ConsensusHypothesis, ...] = field(default_factory=tuple)
    confirmed_features: tuple[ConsensusEvidence, ...] = field(default_factory=tuple)
    uncertain_features: tuple[ConsensusEvidence, ...] = field(default_factory=tuple)
    conflicts: tuple[ConsensusEvidence, ...] = field(default_factory=tuple)
    top_matches: tuple[ConsensusEvidence, ...] = field(default_factory=tuple)
