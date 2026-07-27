"""Tests for MatchResultsPanel widget."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from matching.search_engine import MatchResult


def test_match_results_panel_creates(qtbot):
    from ui.match_results_panel import MatchResultsPanel

    panel = MatchResultsPanel()
    qtbot.addWidget(panel)
    assert panel._list.count() == 0


def test_match_results_panel_set_results(qtbot):
    from ui.match_results_panel import MatchResultsPanel

    panel = MatchResultsPanel()
    qtbot.addWidget(panel)

    results = [
        MatchResult(ref_id=1, name="Ethanol", score=0.95),
        MatchResult(ref_id=2, name="Acetone", score=0.72),
    ]
    panel.set_results(results)
    assert panel._list.count() == 2
    assert "Ethanol" in panel._list.item(0).text()
    assert "95.0%" in panel._list.item(0).text()
    assert "Excellent" in panel._list.item(0).text()
    assert "Strong" in panel._list.item(1).text()
    assert panel._list.currentRow() == 0
    assert (
        panel._status_label.toolTip() == "Similarity score is an internal spectral metric "
        "(coarse cosine search + fine rerank). Not equivalent to OMNIC HQI."
    )


def test_match_results_panel_empty_results(qtbot):
    from ui.match_results_panel import MatchResultsPanel

    panel = MatchResultsPanel()
    qtbot.addWidget(panel)
    panel.set_results([])
    assert panel._list.count() == 0
    assert "No results" in panel._status_label.text()


def test_match_results_panel_candidate_selected_signal(qtbot):
    from ui.match_results_panel import MatchResultsPanel

    panel = MatchResultsPanel()
    qtbot.addWidget(panel)

    received = []
    panel.candidate_selected.connect(received.append)
    results = [MatchResult(ref_id=1, name="Benzene", score=0.88)]
    panel.set_results(results)

    assert len(received) == 1
    assert received[0].name == "Benzene"


def test_match_results_panel_saved_only_filter(qtbot):
    from ui.match_results_panel import MatchResultsPanel

    panel = MatchResultsPanel()
    qtbot.addWidget(panel)

    results = [
        MatchResult(ref_id=1, name="Ethanol", score=0.95),
        MatchResult(ref_id=2, name="Acetone", score=0.72),
        MatchResult(ref_id=3, name="Benzene", score=0.61),
    ]
    panel.set_saved_project_names(["ethanol", "benzene"])
    panel.set_results(results)

    # unfiltered: everything is listed, saved ones carry a marker
    assert panel._list.count() == 3
    assert panel._list.item(0).text().startswith("\U0001f4be Ethanol")
    assert panel._list.item(1).text().startswith("Acetone")
    assert "3 candidates (2 saved)" in panel._status_label.text()

    panel._saved_only_check.setChecked(True)
    assert panel._list.count() == 2
    assert [r.name for r in panel._visible_results] == ["Ethanol", "Benzene"]
    assert panel.selected_result().name == "Ethanol"
    assert "2 of 3 candidates saved" in panel._status_label.text()

    panel._list.setCurrentRow(1)
    assert panel.selected_result().name == "Benzene"

    panel._saved_only_check.setChecked(False)
    assert panel._list.count() == 3
    # selection survives the filter toggle
    assert panel.selected_result().name == "Benzene"


def test_match_results_panel_apply_button_requires_saved_project(qtbot):
    from ui.match_results_panel import MatchResultsPanel

    panel = MatchResultsPanel()
    qtbot.addWidget(panel)
    results = [
        MatchResult(ref_id=1, name="Ethanol", score=0.95),
        MatchResult(ref_id=2, name="Acetone", score=0.72),
    ]

    # no folder configured yet — button stays live so the hint can be shown
    panel.set_results(results)
    assert panel._apply_btn.isEnabled()

    panel.set_saved_project_names(["acetone"])
    assert not panel._apply_btn.isEnabled()
    panel._list.setCurrentRow(1)
    assert panel._apply_btn.isEnabled()


def test_match_results_panel_select_by_ref_id_drops_saved_filter(qtbot):
    from ui.match_results_panel import MatchResultsPanel

    panel = MatchResultsPanel()
    qtbot.addWidget(panel)
    panel.set_saved_project_names(["ethanol"])
    panel.set_results(
        [
            MatchResult(ref_id=1, name="Ethanol", score=0.95),
            MatchResult(ref_id=2, name="Acetone", score=0.72),
        ]
    )
    panel._saved_only_check.setChecked(True)
    assert panel._list.count() == 1

    assert panel.select_result_by_ref_id(2)
    assert not panel._saved_only_check.isChecked()
    assert panel.selected_result().name == "Acetone"
    assert not panel.select_result_by_ref_id(99)


def test_match_quality_label_thresholds():
    from matching.quality import match_quality_label

    assert match_quality_label(0.95) == "Excellent"
    assert match_quality_label(0.80) == "Strong"
    assert match_quality_label(0.55) == "Possible"
    assert match_quality_label(0.30) == "Weak"


def test_spectrum_widget_overlay(qtbot):
    import numpy as np

    from core.spectrum import Spectrum
    from ui.spectrum_widget import SpectrumWidget

    widget = SpectrumWidget()
    qtbot.addWidget(widget)

    wn = np.linspace(400.0, 4000.0, 100)
    sp1 = Spectrum(wavenumbers=wn, intensities=np.ones(100), title="A")
    sp2 = Spectrum(wavenumbers=wn, intensities=np.ones(100) * 0.5, title="B")

    widget.set_spectrum(sp1)
    widget.set_overlay_spectra([sp2])
    assert len(widget._overlay_curves) == 1

    widget.set_overlay_spectra([])
    assert len(widget._overlay_curves) == 0
