"""Tests for the interface review features (i18n, icons, welcome overlay, grouped vibrations, range presets, crosshair, decluttering, and layout reset)."""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QModelIndex
from PySide6.QtWidgets import (
    QComboBox,
    QLabel,
    QPushButton,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from core.peak import Peak
from core.spectrum import SpectralUnit, Spectrum
from core.vibration_presets import VibrationPreset
from ui import icons
from ui.consensus_panel import ConsensusPanel
from ui.functional_group_panel import FunctionalGroupPanel
from ui.i18n import (
    ENV_VAR,
    SOURCE_TEXT_ROLE,
    current_source_text,
    language,
    resolve_language,
    set_language,
    tr,
    translate_tree,
)
from ui.i18n_cs import CZECH_TEXTS
from ui.score_row_delegate import ScoreRowDelegate, score_color
from ui.spectrum_widget import SpectrumWidget
from ui.theme import apply_theme
from ui.vibration_panel import MODE_GROUPED, MODE_WAVENUMBER, VibrationPanel
from ui.welcome_overlay import WelcomeOverlay

_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z0-9_]+)\}")


def test_czech_dictionary_placeholders_match_english_keys() -> None:
    """Every format placeholder in an English key must appear in its Czech translation."""
    assert len(CZECH_TEXTS) > 200
    for source, target in CZECH_TEXTS.items():
        assert isinstance(source, str)
        assert bool(source)
        assert isinstance(target, str)
        assert bool(target)
        src_placeholders = set(_PLACEHOLDER_RE.findall(source))
        dst_placeholders = set(_PLACEHOLDER_RE.findall(target))
        assert src_placeholders == dst_placeholders, (
            f"Placeholder mismatch for {source!r}: {src_placeholders} != {dst_placeholders}"
        )


def test_i18n_translation_and_combo_source_role(qapp, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_VAR, raising=False)
    assert resolve_language("cs") == "cs"
    assert resolve_language("en") == "en"
    assert resolve_language("auto") in {"cs", "en"}

    container = QWidget()
    layout = QVBoxLayout(container)
    button = QPushButton("&Open Spectrum...")
    combo = QComboBox()
    combo.addItems(["All time", "Custom range…"])
    label = QLabel("No functional-group analysis")
    layout.addWidget(button)
    layout.addWidget(combo)
    layout.addWidget(label)

    try:
        set_language("cs")
        assert language() == "cs"
        assert tr("&Open Spectrum...") == "&Otevřít spektrum..."
        translate_tree(container)
        assert button.text() == "&Otevřít spektrum..."
        assert label.text() == "Analýza funkčních skupin není k dispozici"
        assert combo.itemText(1) == "Vlastní období…"
        assert combo.itemData(1, SOURCE_TEXT_ROLE) == "Custom range…"
        combo.setCurrentIndex(1)
        assert current_source_text(combo) == "Custom range…"
    finally:
        set_language("en")


def test_czech_dynamic_panel_updates_remain_translated(qapp) -> None:
    fg_panel = FunctionalGroupPanel()
    consensus_panel = ConsensusPanel()
    try:
        set_language("cs")
        fg_panel.clear()
        assert fg_panel._status_label.text() == "Analýza funkčních skupin není k dispozici"
        assert (
            fg_panel._group_info_label.text()
            == "Vyberte funkční skupinu a zobrazí se, o co se opírá."
        )
        assert (
            fg_panel._peak_info_label.text() == "Vyberte pík a zobrazí se pro něj návrhy přiřazení."
        )
        assert fg_panel._detail_label.text() == "Diagnostické vibrace"

        consensus_panel.clear()
        assert consensus_panel._status_label.text() == "Souhrn není k dispozici"
        assert (
            consensus_panel._headline_label.text()
            == "Spusťte porovnání nebo si projděte funkční skupiny, souhrn se pak sestaví."
        )
        assert (
            consensus_panel._detail_label.text() == "Vyberte hypotézu a zobrazí se, o co se opírá."
        )
    finally:
        set_language("en")


def test_all_registered_icons_render_non_null_pixmaps(qapp) -> None:
    icon_names = icons.names()
    assert len(icon_names) >= 15
    for name in icon_names:
        ic = icons.icon(name)
        assert not ic.isNull(), f"Icon {name!r} returned null QIcon"
        pm = icons.pixmap(name, size=18)
        assert not pm.isNull(), f"Icon {name!r} returned null QPixmap"
        assert pm.width() > 0
        assert pm.height() > 0


def test_theme_and_score_row_delegate(qapp) -> None:
    from ui import theme

    apply_theme(qapp)
    assert score_color(90.0).lower() == theme.QUALITY_EXCELLENT.lower()
    assert score_color(60.0).lower() == theme.QUALITY_POSSIBLE.lower()
    assert score_color(20.0).lower() == theme.QUALITY_WEAK.lower()

    delegate = ScoreRowDelegate()
    size = delegate.sizeHint(QStyleOptionViewItem(), QModelIndex())
    assert size.height() >= 24


def test_welcome_overlay_recent_files_and_signals(qapp, tmp_path: Path) -> None:
    existing_a = tmp_path / "sample_a.spa"
    existing_b = tmp_path / "sample_b.irproj"
    existing_a.write_text("a", encoding="utf-8")
    existing_b.write_text("b", encoding="utf-8")

    overlay = WelcomeOverlay()
    overlay.set_recent_files([str(existing_a), str(existing_b)])

    assert overlay.recent_files() == [str(existing_a), str(existing_b)]
    assert not overlay._recent_list.isHidden()

    triggered: list[str] = []
    overlay.recent_requested.connect(triggered.append)
    overlay._on_recent_clicked(overlay._recent_list.item(0))
    assert triggered == [str(existing_a)]

    actions: list[str] = []
    overlay.open_spectrum_requested.connect(lambda: actions.append("spectrum"))
    overlay.open_project_requested.connect(lambda: actions.append("project"))
    overlay._open_spectrum_btn.click()
    overlay._open_project_btn.click()
    assert actions == ["spectrum", "project"]


def test_vibration_panel_grouped_folding_and_active_peak_pinning(qapp) -> None:
    panel = VibrationPanel()
    panel.set_presets(
        [
            VibrationPreset(
                name="ν(C=O)",
                typical_range_min=1680.0,
                typical_range_max=1750.0,
                category="stretch",
                db_id=1,
            ),
            VibrationPreset(
                name="δ(C-H)",
                typical_range_min=1350.0,
                typical_range_max=1470.0,
                category="bend",
                db_id=2,
            ),
        ]
    )
    panel.set_view_mode(MODE_GROUPED)

    assert panel.view_mode() == MODE_GROUPED
    initial_count = panel._list.count()
    assert initial_count == 4

    # Clicking a section header folds its children
    first_header = panel._list.item(0)
    panel._on_item_clicked(first_header)
    assert panel._list.count() == 3

    # Highlighting for a peak in range of the first preset pins "Fits peak ..." at the top
    panel.highlight_for_peak(1715.0)
    top_header_text = panel._list.item(0).text()
    assert "1715" in top_header_text

    # Switching to flat wavenumber mode shows flat preset rows
    panel.set_view_mode(MODE_WAVENUMBER)
    assert panel.view_mode() == MODE_WAVENUMBER
    assert panel._list.count() == 2


def test_spectrum_widget_range_presets_crosshair_and_declutter(qapp) -> None:
    widget = SpectrumWidget()
    wn = np.linspace(400.0, 4000.0, 1801)
    y = np.ones_like(wn) * 95.0
    spectrum = Spectrum(
        wavenumbers=wn,
        intensities=y,
        y_unit=SpectralUnit.TRANSMITTANCE,
        source_path="test.spa",
    )
    widget.set_spectrum(spectrum)

    # Range preset zoom
    widget.show_range(1550.0, 1850.0)
    x_range, _ = widget._plot_widget.viewRange()
    assert min(x_range) == pytest.approx(1550.0, abs=5.0)
    assert max(x_range) == pytest.approx(1850.0, abs=5.0)

    # Crosshair toggle and readout formatting
    widget.set_crosshair_enabled(False)
    assert not widget._crosshair_enabled
    widget.set_crosshair_enabled(True)
    assert widget._crosshair_enabled
    assert "1715.0" in widget._readout_text(1715.0, 88.5)
    assert "%T" in widget._readout_text(1715.0, 88.5)

    # Decluttering hides crowded labels while keeping the selected peak label visible
    widget.resize(800, 400)
    crowded_peaks = [Peak(position=1700.0, intensity=50.0) for _ in range(4)]
    widget.show_range(None, None)
    widget._selected_peak = crowded_peaks[0]
    widget.set_peaks(crowded_peaks)

    widget.set_declutter_enabled(True)
    assert widget.hidden_label_count() == 3

    widget.set_declutter_enabled(False)
    assert widget.hidden_label_count() == 0
