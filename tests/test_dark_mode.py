"""Dark mode: one palette switch recolours the whole interface, never the exports."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest
from PySide6.QtCore import QByteArray
from PySide6.QtGui import QColor, QImage

from core.spectrum import SpectralUnit, Spectrum
from storage.settings import Settings
from ui import icons, theme


@pytest.fixture
def dark():
    """Build widgets in the dark theme for one test and always switch back."""
    theme.set_mode(theme.DARK_MODE)
    yield
    theme.set_mode(theme.LIGHT_MODE)


def _settings(values: dict | None = None) -> MagicMock:
    stored = dict(values or {})
    settings = MagicMock()
    settings.get.side_effect = lambda key, default=None: stored.get(key, default)
    settings.set.side_effect = lambda key, value: stored.__setitem__(key, value)
    settings.stored = stored
    return settings


def _luminance(hex_color: str) -> float:
    color = QColor(hex_color)
    return 0.2126 * color.redF() + 0.7152 * color.greenF() + 0.0722 * color.blueF()


def test_both_palettes_define_the_same_colours() -> None:
    assert set(theme.LIGHT) == set(theme.DARK)
    for name in theme.LIGHT:
        assert QColor(theme.LIGHT[name]).isValid(), name
        assert QColor(theme.DARK[name]).isValid(), name


def test_set_mode_swaps_every_constant_and_the_stylesheet() -> None:
    try:
        assert theme.set_mode(theme.DARK_MODE) == theme.DARK_MODE
        assert theme.is_dark()
        for name, value in theme.DARK.items():
            assert getattr(theme, name) == value
        assert theme.DARK["WINDOW"] in theme.APP_STYLESHEET
        assert theme.LIGHT["WINDOW"] not in theme.APP_STYLESHEET
        assert theme.DARK["TEXT_MUTED"] in theme.CAPTION_STYLE
        assert _luminance(theme.WINDOW) < 0.2 < _luminance(theme.TEXT)
    finally:
        theme.set_mode(theme.LIGHT_MODE)
    assert not theme.is_dark()
    assert theme.TEXT == theme.LIGHT["TEXT"]
    assert theme.LIGHT["WINDOW"] in theme.APP_STYLESHEET


def test_light_stylesheet_has_no_stray_hex_colours() -> None:
    """Every colour in the stylesheet comes from the palette, so dark mode reaches it."""
    import re

    palette_colours = {value.upper() for value in theme.LIGHT.values()}
    used = {match.upper() for match in re.findall(r"#[0-9A-Fa-f]{6}", theme.APP_STYLESHEET)}
    assert used <= palette_colours


def test_resolve_mode_reads_setting_environment_and_system(monkeypatch) -> None:
    monkeypatch.delenv(theme.ENV_VAR, raising=False)
    assert theme.resolve_mode("dark") == theme.DARK_MODE
    assert theme.resolve_mode("light") == theme.LIGHT_MODE
    assert theme.resolve_mode("system") in (theme.LIGHT_MODE, theme.DARK_MODE)
    assert theme.resolve_mode(None) in (theme.LIGHT_MODE, theme.DARK_MODE)
    monkeypatch.setenv(theme.ENV_VAR, "light")
    assert theme.resolve_mode("dark") == theme.LIGHT_MODE


def test_dark_is_the_default_appearance(tmp_path) -> None:
    settings = Settings(tmp_path / "settings.json")
    settings.load()
    assert settings.get("appearance") == theme.DARK_MODE


def test_apply_theme_sets_a_dark_palette(qapp, dark) -> None:
    from PySide6.QtGui import QPalette

    theme.apply_theme(qapp)
    try:
        palette = qapp.palette()
        assert palette.color(QPalette.ColorRole.Window).name().upper() == theme.WINDOW
        assert palette.color(QPalette.ColorRole.Text).name().upper() == theme.TEXT
    finally:
        theme.set_mode(theme.LIGHT_MODE)
        theme.apply_theme(qapp)


def test_icons_follow_the_active_theme(qapp) -> None:
    light = icons.icon("undo").pixmap(24, 24).toImage()
    theme.set_mode(theme.DARK_MODE)
    try:
        dark_icon = icons.icon("undo").pixmap(24, 24).toImage()
    finally:
        theme.set_mode(theme.LIGHT_MODE)

    def _ink(image: QImage) -> float:
        values = []
        for x in range(image.width()):
            for y in range(image.height()):
                pixel = image.pixelColor(x, y)
                if pixel.alpha() > 200:
                    values.append(pixel.lightnessF())
        return float(np.mean(values))

    assert _ink(dark_icon) > 0.6 > _ink(light)


def test_spectrum_plot_is_dark_with_light_ink(qtbot, dark) -> None:
    from ui.spectrum_widget import SpectrumWidget

    widget = SpectrumWidget()
    qtbot.addWidget(widget)
    wn = np.linspace(400.0, 4000.0, 500)
    widget.set_spectrum(
        Spectrum(
            wavenumbers=wn,
            intensities=np.exp(-((wn - 1700.0) ** 2) / 200.0),
            y_unit=SpectralUnit.ABSORBANCE,
        )
    )
    background = widget._plot_widget.backgroundBrush().color().name().upper()
    assert background == theme.DARK["PLOT_BG"]
    curve_pen = widget._spectrum_curve.opts["pen"]
    assert curve_pen.color().name().upper() == theme.DARK["PLOT_FG"]
    assert theme.DARK["OVERLAY_BAR"] in widget._overlay_bar.styleSheet()


def test_editor_canvas_is_dark_on_screen_but_exports_stay_light(qtbot, dark) -> None:
    from ui.widgets.molecule_canvas import MoleculeCanvas

    canvas = MoleculeCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(320, 240)
    canvas.load_smiles("OCC(=O)N")
    on_screen = canvas.grab().toImage()
    corner = on_screen.pixelColor(2, 2)
    assert corner.name().upper() == theme.DARK["SURFACE"]

    exported = QImage.fromData(QByteArray(canvas.render_to_png_bytes(300, 200)))
    assert not exported.isNull()
    assert exported.pixelColor(0, 0).lightnessF() > 0.95
    darkest = min(
        exported.pixelColor(x, y).lightnessF()
        for x in range(0, exported.width(), 2)
        for y in range(0, exported.height(), 2)
    )
    assert darkest < 0.3

    # The next on-screen paint goes back to the dark ink.
    again = canvas.grab().toImage()
    assert again.pixelColor(2, 2).name().upper() == theme.DARK["SURFACE"]


def test_appearance_menu_stores_the_choice(qtbot, monkeypatch) -> None:
    from ui.main_window import MainWindow

    db = MagicMock()
    db.get_vibration_presets.return_value = []
    window = MainWindow(db=db, settings=_settings())

    def _discard_changes(closing: MainWindow) -> None:
        closing._non_undo_dirty = False
        closing._undo_stack.setClean()

    qtbot.addWidget(window, before_close_func=_discard_changes)
    shown: list[str] = []
    monkeypatch.setattr(
        "ui.main_window.QMessageBox.information", lambda *args, **kwargs: shown.append(args[2])
    )
    actions = {action.text(): action for action in window._appearance_menu.actions()}
    assert set(actions) == {"Follow system", "Light", "Dark"}
    assert actions["Dark"].isChecked()
    assert window._appearance_menu.menuAction() in window._view_menu.actions()

    actions["Light"].trigger()
    assert window._settings.stored["appearance"] == "light"
    assert shown
    assert "next time" in shown[0]
    actions["Follow system"].trigger()
    assert window._settings.stored["appearance"] == "system"
