"""Tests for the interface review: layout, reading aids, lists, start page, language.

Each test covers one thing an analyst sees or does; the docstring says which.
"""

from __future__ import annotations

import string
from unittest.mock import MagicMock

import numpy as np
import pytest
from PySide6.QtCore import QMimeData, QPoint, Qt, QUrl
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QWidget

from core.peak import Peak
from core.project import Project
from core.spectrum import SpectralUnit, Spectrum
from core.vibration_presets import VibrationPreset
from ui import i18n, icons, theme
from ui.main_window import MainWindow
from ui.match_results_panel import MatchResultsPanel, quality_color
from ui.peak_table_widget import PeakTableWidget
from ui.score_row_delegate import NAME_ROLE, SCORE_ROLE, score_color
from ui.spectrum_widget import SpectrumWidget
from ui.toolbar import MainToolbar
from ui.vibration_panel import MODE_GROUPED, MODE_WAVENUMBER, VibrationPanel
from ui.welcome_overlay import WelcomeOverlay

_WN = np.linspace(400.0, 4000.0, 3601)


def _absorbance_spectrum(n_bands: int = 4) -> Spectrum:
    centres = np.linspace(700.0, 3400.0, n_bands)
    y = np.zeros_like(_WN)
    for index, centre in enumerate(centres):
        y += (0.3 + 0.7 * (index + 1) / n_bands) * np.exp(-((_WN - centre) ** 2) / (2 * 12.0**2))
    return Spectrum(wavenumbers=_WN.copy(), intensities=y, y_unit=SpectralUnit.ABSORBANCE)


def _settings(values: dict | None = None) -> MagicMock:
    stored = dict(values or {})
    settings = MagicMock()
    settings.get.side_effect = lambda key, default=None: stored.get(key, default)
    settings.set.side_effect = lambda key, value: stored.__setitem__(key, value)
    settings.stored = stored
    return settings


def _window(qtbot, values: dict | None = None) -> MainWindow:
    db = MagicMock()
    db.get_vibration_presets.return_value = []
    window = MainWindow(db=db, settings=_settings(values))

    def _discard_changes(closing: MainWindow) -> None:
        # A shown window asks about unsaved work when it closes; nobody is
        # there to answer the dialog at test teardown.
        closing._non_undo_dirty = False
        closing._undo_stack.setClean()

    qtbot.addWidget(window, before_close_func=_discard_changes)
    return window


@pytest.fixture
def czech():
    """Switch the UI to Czech for one test and always switch back."""
    i18n.set_language(i18n.CZECH)
    yield
    i18n.set_language(i18n.ENGLISH)


# ── Theme and icons ──────────────────────────────────────────────────────────


def test_every_icon_renders(qtbot) -> None:
    """A missing or broken icon would leave a blank button in the toolbar."""
    for name in icons.names():
        image = icons.pixmap(name).toImage()
        assert not image.isNull()
        painted = any(
            image.pixelColor(x, y).alpha() > 0
            for x in range(0, image.width(), 3)
            for y in range(0, image.height(), 3)
        )
        assert painted, name


def test_theme_applies_one_style_to_the_application(qtbot) -> None:
    from PySide6.QtGui import QPalette

    app = QApplication.instance()
    previous_sheet, previous_palette = app.styleSheet(), app.palette()
    try:
        theme.apply_theme(app)
        assert theme.ACCENT in app.styleSheet()
        highlight = app.palette().color(QPalette.ColorRole.Highlight).name()
        assert highlight.lower() == theme.ACCENT.lower()
    finally:
        app.setStyleSheet(previous_sheet)
        app.setPalette(previous_palette)


# ── Toolbar ──────────────────────────────────────────────────────────────────


def test_toolbar_actions_carry_icons_tooltips_and_history_buttons(qtbot) -> None:
    toolbar = MainToolbar()
    qtbot.addWidget(toolbar)
    actions = [action for action in toolbar.actions() if not action.isSeparator() and action.text()]
    assert [a.text() for a in actions[:4]] == ["Open", "Save", "Undo", "Redo"]
    assert all(not action.icon().isNull() for action in actions)
    assert all(action.toolTip() for action in actions)
    assert sum(1 for action in toolbar.actions() if action.isSeparator()) >= 5

    assert not toolbar._undo_action.isEnabled()
    toolbar.set_history_state(can_undo=True, can_redo=False, undo_text="Detect peaks")
    assert toolbar._undo_action.isEnabled()
    assert "Detect peaks" in toolbar._undo_action.toolTip()
    assert not toolbar._redo_action.isEnabled()


def test_toolbar_undo_redo_and_save_drive_the_window(qtbot, monkeypatch) -> None:
    """Undo, Redo and Save used to exist only in the menu."""
    window = _window(qtbot)
    window._apply_project_to_ui(Project(name="p", spectrum=_absorbance_spectrum()))
    window._on_peak_clicked(1500.0, 0.1, 0.2)
    assert window._toolbar._undo_action.isEnabled()

    window._toolbar._undo_action.trigger()
    assert window._project.peaks == []
    assert window._toolbar._redo_action.isEnabled()
    window._toolbar._redo_action.trigger()
    assert len(window._project.peaks) == 1

    saved: list[int] = []
    monkeypatch.setattr(window, "_on_save_project_quick", lambda: saved.append(1) or True)
    window._toolbar.save_requested.emit()
    assert saved == [1]


# ── Peak table ───────────────────────────────────────────────────────────────


def test_peak_table_shows_relative_strength_and_progress(qtbot) -> None:
    """The Label column only repeated the position; strength and progress are new."""
    table = PeakTableWidget()
    qtbot.addWidget(table)
    strong = Peak(position=1715.0, intensity=0.9, vibration_labels=["ν(C=O)"], vibration_ids=[None])
    weak = Peak(position=1200.0, intensity=0.1)
    table.set_peaks([strong, weak], is_dip_spectrum=False)

    headers = [table._table.horizontalHeaderItem(c).text() for c in range(4)]
    assert headers == ["Position (cm⁻¹)", "Intensity", "Rel.", "Vibration"]
    assert table._table.item(0, 2).text() == "vs"
    assert table._table.item(1, 2).text() == "w"
    assert table._table.item(0, 3).text() == "ν(C=O)"
    assert table._table.item(0, 0).textAlignment() & int(Qt.AlignmentFlag.AlignRight)
    assert table.summary_text() == "2 peaks · 1 assigned"
    assert table._summary_label.text() == "2 peaks · 1 assigned"

    table.set_peaks([])
    assert table.summary_text() == "No peaks"


# ── Vibration list ───────────────────────────────────────────────────────────


def _presets() -> list[VibrationPreset]:
    return [
        VibrationPreset("ν(OH)", 3200.0, 3600.0, category="stretch"),
        VibrationPreset("ν(C=O) ester", 1720.0, 1750.0, category="stretch"),
        VibrationPreset("ν(C=O) broad", 1650.0, 1800.0, category="stretch"),
        VibrationPreset("δ(CH₂)", 1440.0, 1480.0, category="bend"),
        VibrationPreset("γ(CH) Ar", 690.0, 900.0, category="oop"),
        VibrationPreset("ν(Si–O)", 1000.0, 1100.0, category="silyl"),
        VibrationPreset("my band", 1700.0, 1760.0, category="", is_builtin=False),
    ]


def _rows(panel: VibrationPanel) -> list[str]:
    return [panel._list.item(row).text() for row in range(panel._list.count())]


def test_wavenumber_mode_is_the_flat_list_it_always_was(qtbot) -> None:
    """The lab can always go back to everything in one list ordered by wavenumber."""
    panel = VibrationPanel()
    qtbot.addWidget(panel)
    panel.set_presets(_presets())
    assert panel.view_mode() == MODE_WAVENUMBER
    names = [panel._list.item(row).data(256).name for row in panel.preset_rows()]
    assert names == [
        "ν(OH)",
        "ν(C=O) ester",
        "ν(C=O) broad",
        "δ(CH₂)",
        "γ(CH) Ar",
        "my band",
        "ν(Si–O)",
    ]
    assert sum(1 for text in _rows(panel) if "Protecting groups" in text) == 1


def test_grouped_mode_has_sections_and_puts_fitting_vibrations_on_top(qtbot) -> None:
    panel = VibrationPanel()
    qtbot.addWidget(panel)
    panel.set_presets(_presets())
    panel.set_view_mode(MODE_GROUPED)

    headers = [text for text in _rows(panel) if text.startswith("▾")]
    assert [h.split("  (")[0] for h in headers] == [
        "▾ Custom vibrations",
        "▾ Stretching ν",
        "▾ Bending δ",
        "▾ Out-of-plane γ",
        "▾ Protecting groups",
    ]
    assert "(3)" in headers[1]

    panel.highlight_for_peak(1735.0)
    rows = _rows(panel)
    assert rows[0].startswith("▾ Fits peak 1735 cm⁻¹  (3)")
    # Narrowest range first: the most specific candidate leads.
    fitting = [panel._list.item(row).data(256).name for row in (1, 2, 3)]
    assert fitting == ["ν(C=O) ester", "my band", "ν(C=O) broad"]
    # A vibration is listed once — not again in its own section.
    all_names = [panel._list.item(row).data(256).name for row in panel.preset_rows()]
    assert len(all_names) == len(set(all_names)) == len(_presets())


def test_sections_fold_and_the_header_is_never_the_highlighted_vibration(qtbot) -> None:
    panel = VibrationPanel()
    qtbot.addWidget(panel)
    panel.set_presets(_presets())
    panel.set_view_mode(MODE_GROUPED)
    before = panel._list.count()
    header = next(
        panel._list.item(row)
        for row in range(panel._list.count())
        if panel._list.item(row).text().startswith("▾ Stretching")
    )
    assert not (header.flags() & Qt.ItemFlag.ItemIsSelectable)

    received: list = []
    panel.preset_range_requested.connect(received.append)
    panel._list.itemClicked.emit(header)
    assert received == []  # folding is not "show this vibration's range"
    assert panel._list.count() == before - 3
    assert any(text.startswith("▸ Stretching") for text in _rows(panel))

    folded = next(
        panel._list.item(row)
        for row in range(panel._list.count())
        if panel._list.item(row).text().startswith("▸ Stretching")
    )
    panel._list.itemClicked.emit(folded)
    assert panel._list.count() == before


def test_the_arrangement_is_remembered(qtbot) -> None:
    window = _window(qtbot)
    assert window._vibration_panel.view_mode() == MODE_GROUPED  # the new default

    combo = window._vibration_panel._mode_combo
    combo.setCurrentIndex(combo.findData(MODE_WAVENUMBER))
    assert window._settings.stored["vibration_list_mode"] == MODE_WAVENUMBER

    again = _window(qtbot, {"vibration_list_mode": MODE_WAVENUMBER})
    assert again._vibration_panel.view_mode() == MODE_WAVENUMBER


# ── Scored lists ─────────────────────────────────────────────────────────────


def test_match_rows_keep_their_text_and_colour_only_the_bar(qtbot) -> None:
    """Orange and light-blue row text was hard to read; quality now sits in the bar."""
    from matching.search_engine import MatchResult

    panel = MatchResultsPanel()
    qtbot.addWidget(panel)
    panel.set_results(
        [
            MatchResult(ref_id=1, name="Ethanol", score=0.95, fingerprint_score=0.9),
            MatchResult(ref_id=2, name="Acetone", score=0.55, fingerprint_score=0.7),
        ]
    )
    first = panel._list.item(0)
    assert "Ethanol" in first.text()
    assert "95.0%" in first.text()
    assert first.foreground().style() == Qt.BrushStyle.NoBrush  # no per-row text colour
    assert quality_color(0.95) == theme.QUALITY_EXCELLENT
    assert quality_color(0.10) == theme.QUALITY_WEAK
    index = panel._list.model().index(0, 0)
    assert panel._list.sizeHintForIndex(index).height() >= 26


def test_score_colours_step_with_the_score() -> None:
    assert score_color(90.0) == theme.QUALITY_EXCELLENT
    assert score_color(75.0) == theme.QUALITY_STRONG
    assert score_color(55.0) == theme.QUALITY_POSSIBLE
    assert score_color(20.0) == theme.QUALITY_WEAK


def test_functional_group_rows_carry_name_and_score_for_the_bar(qtbot) -> None:
    window = _window(qtbot)
    window._apply_project_to_ui(Project(name="p", spectrum=_absorbance_spectrum()))
    item = window._functional_group_panel._group_list.item(0)
    assert item is not None
    assert isinstance(item.data(NAME_ROLE), str)
    assert item.data(NAME_ROLE)
    assert 0.0 <= float(item.data(SCORE_ROLE)) <= 100.0


# ── Start page and drag & drop ───────────────────────────────────────────────


def test_start_page_shows_until_a_spectrum_is_loaded(qtbot) -> None:
    """An empty window used to be an empty plot with no hint what to do."""
    window = _window(qtbot, {"recent_files": ["/data/a.spa", "/data/b.irproj"]})
    window.show()
    qtbot.waitExposed(window)
    assert window._welcome.isVisible()
    assert window._welcome.recent_files() == ["/data/a.spa", "/data/b.irproj"]
    assert window._welcome.geometry() == window._spectrum_widget.rect()

    window._apply_project_to_ui(Project(name="p", spectrum=_absorbance_spectrum()))
    assert not window._welcome.isVisible()


def test_start_page_buttons_and_recent_files_report_the_choice(qtbot) -> None:
    overlay = WelcomeOverlay()
    qtbot.addWidget(overlay)
    overlay.set_recent_files(["/data/sample.spa"])
    chosen: list[str] = []
    overlay.recent_requested.connect(chosen.append)
    overlay._recent_list.itemClicked.emit(overlay._recent_list.item(0))
    assert chosen == ["/data/sample.spa"]

    with qtbot.waitSignal(overlay.open_spectrum_requested, timeout=1000):
        overlay._open_spectrum_btn.click()
    with qtbot.waitSignal(overlay.open_project_requested, timeout=1000):
        overlay._open_project_btn.click()

    overlay.set_recent_files([])
    assert overlay._recent_list.isHidden()


def test_dropping_a_file_on_the_window_opens_it(qtbot, tmp_path, monkeypatch) -> None:
    window = _window(qtbot)
    opened: list[str] = []
    extra: list[str] = []
    monkeypatch.setattr(window, "_open_recent_path", opened.append)
    window.open_path_requested.connect(extra.append)

    first, second, ignored = tmp_path / "a.SPA", tmp_path / "b.irproj", tmp_path / "notes.txt"
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in (ignored, first, second)])
    assert window._droppable_paths(mime) == [str(first), str(second)]

    event = QDropEvent(
        QPoint(10, 10).toPointF(),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.dropEvent(event)
    assert opened == [str(first)]
    assert extra == [str(second)]  # further files go to the controller

    text_only = QMimeData()
    text_only.setText("not a file")
    assert window._droppable_paths(text_only) == []


# ── Status bar ───────────────────────────────────────────────────────────────


def test_status_bar_shows_the_standing_facts(qtbot) -> None:
    """Unit, baseline state and peak progress used to be nowhere on screen."""
    window = _window(qtbot)
    window.show()
    qtbot.waitExposed(window)
    assert not window._status_unit.isVisible()

    spectrum = Spectrum(
        wavenumbers=_WN.copy(),
        intensities=90.0 - 30.0 * _absorbance_spectrum().intensities,
        y_unit=SpectralUnit.TRANSMITTANCE,
    )
    window._apply_project_to_ui(Project(name="p", spectrum=spectrum))
    assert window._status_unit.text() == "Transmittance"
    assert not window._status_baseline.isVisible()
    window._on_detect_peaks()
    assert window._status_peaks.text() == "4 peaks · 0 assigned"

    window._on_correct_baseline()
    assert window._status_baseline.isVisible()
    window._undo_stack.undo()
    assert not window._status_baseline.isVisible()
    # The message about the undone step does not linger.
    assert window.statusBar().currentMessage() == ""


def test_cursor_readout_gives_wavenumber_and_intensity(qtbot) -> None:
    window = _window(qtbot)
    window._apply_project_to_ui(Project(name="p", spectrum=_absorbance_spectrum()))
    window._spectrum_widget.cursor_moved.emit(1715.25, 0.4321)
    assert window._status_cursor.text() == "1715.2 cm⁻¹   0.4321 A"


# ── Plot reading aids ────────────────────────────────────────────────────────


def test_range_presets_show_one_window_with_fitted_intensity(qtbot) -> None:
    widget = SpectrumWidget()
    qtbot.addWidget(widget)
    widget.set_spectrum(_absorbance_spectrum())

    widget.show_range(None, 2000.0)
    assert widget.get_x_view_range() == pytest.approx((400.0, 2000.0))
    widget.show_range(2000.0, None)
    assert widget.get_x_view_range() == pytest.approx((2000.0, 4000.0))
    widget.show_range(None, None)
    assert widget.get_x_view_range() == pytest.approx((400.0, 4000.0))

    widget._split_btn.setChecked(True)
    widget._range_buttons[2].click()  # a preset leaves split view
    assert not widget._split_btn.isChecked()
    assert widget.get_x_view_range() == pytest.approx((400.0, 2000.0))


def test_crosshair_follows_the_curve_and_can_be_switched_off(qtbot) -> None:
    widget = SpectrumWidget()
    qtbot.addWidget(widget)
    widget.resize(900, 500)
    widget.show()
    qtbot.waitExposed(widget)
    spectrum = _absorbance_spectrum()
    widget.set_spectrum(spectrum)
    view_box = widget._plot_widget.getPlotItem().vb
    crosshair = widget._crosshairs[widget._plot_widget]

    widget._handle_mouse_moved(
        view_box.mapViewToScene(QPoint(1600, 0).toPointF()), widget._plot_widget
    )
    assert crosshair._line.isVisible()
    assert crosshair._line.value() == pytest.approx(1600.0, abs=0.5)
    expected = float(np.interp(1600.0, _WN, spectrum.intensities))
    assert crosshair._dot.getData()[1][0] == pytest.approx(expected, abs=1e-6)
    assert "cm⁻¹" in crosshair._text.toPlainText()

    widget._crosshair_action.setChecked(False)
    assert not crosshair._line.isVisible()
    widget._handle_mouse_moved(
        view_box.mapViewToScene(QPoint(1600, 0).toPointF()), widget._plot_widget
    )
    assert not crosshair._line.isVisible()


def test_overlapping_labels_of_weaker_peaks_step_aside(qtbot) -> None:
    """A crowded region was an unreadable pile of labels."""
    widget = SpectrumWidget()
    qtbot.addWidget(widget)
    widget.resize(900, 500)
    widget.show()
    qtbot.waitExposed(widget)
    spectrum = _absorbance_spectrum()
    widget.set_spectrum(spectrum)
    # Eleven peaks 2 cm⁻¹ apart: at full view their labels cannot all fit.
    crowd = [Peak(position=1500.0 + 2.0 * i, intensity=0.2 + 0.05 * i) for i in range(11)]
    assigned = crowd[0]
    assigned.vibration_labels = ["ν(C=C)"]
    assigned.vibration_ids = [None]
    counts: list[int] = []
    widget.hidden_labels_changed.connect(counts.append)
    widget.set_peaks(crowd)

    hidden = widget.hidden_label_count()
    assert 0 < hidden < len(crowd)
    assert counts
    assert counts[-1] == hidden
    labels = {label._peak.position: label for label in widget._peak_label_items()}
    assert labels[assigned.position].isVisible()  # an assigned peak is never hidden
    assert labels[crowd[-1].position].isVisible()  # nor the strongest one
    # Every label is still there for the report, hidden or not.
    assert len(widget.get_peak_label_placements()) == len(crowd)

    widget._declutter_action.setChecked(False)
    assert widget.hidden_label_count() == 0
    assert all(label.isVisible() for label in widget._peak_label_items())

    widget._declutter_action.setChecked(True)
    widget._plot_widget.setXRange(1495.0, 1525.0, padding=0.0)  # zoom in: room for all
    # The plot re-lays its labels out on the next event-loop turn, then the
    # widget's own (debounced) tidy-up runs — exactly as when a user zooms.
    qtbot.waitUntil(lambda: widget.hidden_label_count() == 0, timeout=2000)


def test_detect_peaks_arranges_labels_in_the_same_undo_step(qtbot) -> None:
    window = _window(qtbot)
    window.resize(1300, 850)
    window.show()
    qtbot.waitExposed(window)
    window._apply_project_to_ui(Project(name="p", spectrum=_absorbance_spectrum(8)))
    window._on_detect_peaks()
    assert len(window._project.peaks) == 8
    assert all(peak.manual_placement for peak in window._project.peaks)

    window._undo_stack.undo()
    assert window._project.peaks == []
    assert not window._undo_stack.canUndo()


def test_band_markers_follow_the_functional_groups_tab_and_have_a_legend(qtbot) -> None:
    """Coloured bands used to appear on load with nothing saying what they meant."""
    window = _window(qtbot)
    window._apply_project_to_ui(Project(name="p", spectrum=_absorbance_spectrum()))
    widget = window._spectrum_widget
    assert widget.diagnostic_regions()  # a group is selected, its bands are known

    assert widget.diagnostic_regions_visible()
    assert "band" in widget._legend_label.text()
    assert not widget._legend_label.isHidden()

    window._functional_group_panel.diagnostic_visibility_changed.emit(False)
    assert not widget.diagnostic_regions_visible()
    assert widget._legend_label.isHidden()

    window._on_preset_range_requested(VibrationPreset("ν(C=O)", 1700.0, 1750.0))
    assert "range of the selected vibration" in widget._legend_label.text()
    assert not widget._legend_label.isHidden()


def test_found_expected_and_missing_bands_use_one_visual_language(qtbot) -> None:
    widget = SpectrumWidget()
    qtbot.addWidget(widget)

    def _style(**flags):
        region = type("Region", (), {"color": "#00FF00", **flags})()
        brush, pen = widget._diagnostic_region_style(region)
        return brush, pen

    found_brush, found_pen = _style(is_confirmed=True)
    expected_brush, expected_pen = _style()
    missing_brush, missing_pen = _style(is_missing_required=True)
    # Meaning sits in fill and line style, not in a per-band colour.
    assert found_pen.color().name().lower() == theme.REGION_CONFIRMED.lower()
    assert found_pen.style() == Qt.PenStyle.SolidLine
    assert found_brush.alpha() > expected_brush.alpha()
    assert expected_pen.style() == Qt.PenStyle.DashLine
    assert missing_pen.color().name().lower() == theme.REGION_MISSING.lower()


# ── Window layout ────────────────────────────────────────────────────────────


def test_first_tab_is_metadata_and_layout_is_remembered(qtbot) -> None:
    """The window used to open on the still-empty Structure tab."""
    window = _window(qtbot)
    window.show()
    qtbot.waitExposed(window)
    qtbot.wait(50)
    assert not window._dock_metadata.visibleRegion().isEmpty()
    assert window._dock_structure.visibleRegion().isEmpty()

    window._dock_structure.raise_()
    window._save_window_layout()
    stored = window._settings.stored
    assert isinstance(stored["window_state"], str)
    assert stored["window_state"]
    assert isinstance(stored["window_geometry"], str)
    assert stored["window_geometry"]

    again = _window(qtbot, dict(stored))
    assert again._layout_restored

    window._on_reset_layout()
    qtbot.wait(20)
    assert not window._dock_metadata.visibleRegion().isEmpty()


def test_a_broken_stored_layout_does_not_stop_the_window(qtbot) -> None:
    window = _window(qtbot, {"window_state": "%%% not base64 %%%", "window_geometry": 12345})
    assert not window._layout_restored


def test_reference_library_buttons_are_grouped_and_clear_is_set_apart(qtbot, tmp_path) -> None:
    from PySide6.QtWidgets import QGroupBox

    from storage.database import Database
    from ui.dialogs.reference_library_dialog import ReferenceLibraryDialog

    db = Database(tmp_path / "library.db")
    db.initialize()
    dialog = ReferenceLibraryDialog(db)
    qtbot.addWidget(dialog)

    groups = {box.title(): box for box in dialog.findChildren(QGroupBox)}
    assert {"Library", "Selected reference", "Similarity search"} <= set(groups)
    assert dialog._delete_btn.parent() is groups["Selected reference"]
    assert dialog._find_similar_btn.parent() is groups["Similarity search"]
    assert dialog._clear_library_btn.property("role") == "danger"
    assert not isinstance(dialog._clear_library_btn.parent(), QGroupBox)


# ── Language ─────────────────────────────────────────────────────────────────


def test_english_is_untouched_and_czech_translates(czech) -> None:
    assert i18n.tr("Detect Peaks") == "Najít píky"
    assert i18n.tr("a text nobody translated") == "a text nobody translated"
    i18n.set_language(i18n.ENGLISH)
    assert i18n.tr("Detect Peaks") == "Detect Peaks"


def test_translations_keep_every_placeholder() -> None:
    """A dropped or renamed {placeholder} would raise at the moment the text is shown."""
    from ui.i18n_cs import CZECH_TEXTS

    def _fields(text: str) -> set[str]:
        return {name for _, name, _, _ in string.Formatter().parse(text) if name}

    for english, czech_text in CZECH_TEXTS.items():
        assert _fields(english) == _fields(czech_text), english
        assert czech_text.strip(), english
        assert english.count("\n") == czech_text.count("\n"), english


def test_language_preference_resolution(monkeypatch) -> None:
    monkeypatch.delenv(i18n.ENV_VAR, raising=False)
    assert i18n.resolve_language("cs") == i18n.CZECH
    assert i18n.resolve_language("en") == i18n.ENGLISH
    monkeypatch.setenv(i18n.ENV_VAR, "cs")
    assert i18n.resolve_language("en") == i18n.CZECH  # the override wins
    monkeypatch.setenv(i18n.ENV_VAR, "en")
    assert i18n.resolve_language(None) == i18n.ENGLISH


def test_a_whole_window_can_be_translated_without_touching_its_code(qtbot, czech) -> None:
    host = QWidget()
    qtbot.addWidget(host)
    label = QLabel("Sample:", host)
    untranslated = QLabel("ref01.SPA", host)
    combo = QComboBox(host)
    combo.addItems(["All time", "Last 7 days"])
    combo.setCurrentIndex(1)

    i18n.translate_tree(host)
    assert label.text() == "Vzorek:"
    assert untranslated.text() == "ref01.SPA"  # data is left alone
    assert combo.currentText() == "Posledních 7 dní"
    # Code that branches on the entry still gets the English source text.
    assert i18n.current_source_text(combo) == "Last 7 days"


def test_main_window_builds_in_czech(qtbot, czech) -> None:
    window = _window(qtbot)
    assert window._dock_peaks.windowTitle() == "Píky"
    assert window._toolbar._detect_action.text() == "Najít píky"
    assert window._vibration_panel._assign_btn.text() == "Přiřadit vybranému píku"
    window._apply_project_to_ui(Project(name="p", spectrum=_absorbance_spectrum()))
    window._on_detect_peaks()
    assert "Nalezeno 4 píků" in window.statusBar().currentMessage()
    assert window._peak_table.summary_text() == "4 píků · 0 přiřazeno"


def test_language_menu_stores_the_choice(qtbot, monkeypatch) -> None:
    window = _window(qtbot)
    shown: list[str] = []
    monkeypatch.setattr(
        "ui.main_window.QMessageBox.information", lambda *args, **kwargs: shown.append(args[2])
    )
    actions = {action.text(): action for action in window._language_menu.actions()}
    assert {"System", "English", "Čeština"} == set(actions)
    assert actions["System"].isChecked()

    actions["Čeština"].trigger()
    assert window._settings.stored["language"] == "cs"
    assert shown
    assert "příštím spuštění" in shown[0]
    actions["System"].trigger()
    assert window._settings.stored["language"] is None
