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

    results = [MatchResult(ref_id=1, name="Benzene", score=0.88)]
    panel.set_results(results)

    received = []
    panel.candidate_selected.connect(received.append)
    panel._list.setCurrentRow(0)
    assert len(received) == 1
    assert received[0].name == "Benzene"


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
