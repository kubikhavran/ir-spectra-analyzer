"""Tests for ConsensusPanel widget."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _make_analysis():
    from core.consensus import ConsensusAnalysis, ConsensusEvidence, ConsensusHypothesis

    return ConsensusAnalysis(
        overall_score=76.0,
        headline="Most consistent picture: Phenol",
        summary="Interpretation confidence 76%.",
        hypotheses=(
            ConsensusHypothesis(
                hypothesis_id="phenol",
                title="Phenol",
                score=68.0,
                summary="3 matched bands",
                supporting_evidence=(
                    ConsensusEvidence(
                        kind="matched_band",
                        label="Phenolic O-H stretch",
                        score=82.0,
                        details="3200–3600 cm-1",
                        target_id="phenol",
                    ),
                ),
                recommended_checks=(
                    ConsensusEvidence(
                        kind="recommended_check",
                        label="Inspect 1200–1260 cm-1",
                        score=44.0,
                        details="Ar-OH bend / C-O support",
                        target_id="phenol",
                    ),
                ),
            ),
            ConsensusHypothesis(
                hypothesis_id="aryl_ether",
                title="Aryl Ether",
                score=41.0,
                summary="2 matched bands",
            ),
        ),
        top_matches=(
            ConsensusEvidence(
                kind="library_match",
                label="Reference A",
                score=72.0,
                details="Strong spectral match.",
                target_id=10,
            ),
        ),
        confirmed_features=(
            ConsensusEvidence(
                kind="functional_group",
                label="Phenol",
                score=68.0,
                details="3 matched bands",
                target_id="phenol",
            ),
        ),
        uncertain_features=(
            ConsensusEvidence(
                kind="functional_group",
                label="Aryl Ether",
                score=41.0,
                details="2 matched bands",
                target_id="aryl_ether",
            ),
        ),
        conflicts=(
            ConsensusEvidence(
                kind="conflict",
                label="Top library matches are close",
                score=70.0,
                details="Reference A vs Reference B",
            ),
        ),
    )


def test_consensus_panel_creates(qtbot):
    from ui.consensus_panel import ConsensusPanel

    panel = ConsensusPanel()
    qtbot.addWidget(panel)

    assert panel._hypothesis_list.count() == 0
    assert panel._match_list.count() == 0


def test_consensus_panel_set_analysis_and_emit_navigation_signals(qtbot):
    from ui.consensus_panel import ConsensusPanel

    panel = ConsensusPanel()
    qtbot.addWidget(panel)

    hypothesis_ids: list[str] = []
    match_ids: list[int] = []
    panel.hypothesis_selected.connect(hypothesis_ids.append)
    panel.match_requested.connect(match_ids.append)

    panel.set_analysis(_make_analysis())
    panel._hypothesis_list.setCurrentRow(1)
    panel._match_list.setCurrentRow(0)

    assert "Phenol" in panel._headline_label.text()
    assert panel._hypothesis_list.count() == 2
    assert panel._match_list.count() == 1
    assert hypothesis_ids[-1] == "aryl_ether"
    assert match_ids[-1] == 10
