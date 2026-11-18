"""Language (CZ/EN) and appearance switch at once, without restarting the app."""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from core.peak import Peak
from core.project import Project
from core.spectrum import SpectralUnit, Spectrum
from storage.database import Database
from storage.settings import Settings
from ui import i18n, theme


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "projects.db")
    database.initialize()
    yield database
    database.close()


@pytest.fixture
def controller(tmp_path, db, monkeypatch):
    from app.application import Application

    monkeypatch.delenv(i18n.ENV_VAR, raising=False)
    monkeypatch.delenv(theme.ENV_VAR, raising=False)
    settings = Settings(tmp_path / "settings.json")
    settings.load()
    app = Application()
    app._db = db
    app._settings = settings
    yield app
    for window in app.windows:
        window.close_for_rebuild()
    i18n.set_language(i18n.ENGLISH)
    theme.set_mode(theme.LIGHT_MODE, light_plot=False)
    instance = QApplication.instance()
    if isinstance(instance, QApplication):
        theme.apply_theme(instance)


def _project() -> Project:
    wavenumbers = np.linspace(400.0, 4000.0, 401)
    intensities = np.exp(-(((wavenumbers - 1700.0) / 30.0) ** 2))
    spectrum = Spectrum(
        wavenumbers=wavenumbers, intensities=intensities, y_unit=SpectralUnit.ABSORBANCE
    )
    return Project(
        name="live", spectrum=spectrum, peaks=[Peak(position=1700.0, intensity=1.0)], smiles="CCO"
    )


def _visible(controller):
    return [window for window in controller.windows if window.isVisible()]


def test_language_buttons_switch_every_window_at_once(qtbot, controller) -> None:
    window = controller.new_window()
    project = _project()
    window._apply_project_to_ui(project)
    window._mark_non_undo_dirty()
    assert window._view_menu.title() == "&View"
    assert window._language_buttons[i18n.ENGLISH].isChecked()

    window._language_buttons[i18n.CZECH].click()
    qtbot.waitUntil(lambda: len(controller.windows) == 1)

    (rebuilt,) = controller.windows
    assert rebuilt is not window
    assert i18n.language() == i18n.CZECH
    assert controller._settings.get("language") == i18n.CZECH
    assert rebuilt._view_menu.title() == "&Zobrazení"
    assert rebuilt._language_buttons[i18n.CZECH].isChecked()
    # The analysis moves over untouched, unsaved edits included.
    assert rebuilt._project is project
    assert rebuilt._has_unsaved_changes()
    assert rebuilt.windowTitle().startswith("*")

    rebuilt._language_buttons[i18n.ENGLISH].click()
    qtbot.waitUntil(lambda: controller.windows and controller.windows[0] is not rebuilt)
    assert i18n.language() == i18n.ENGLISH
    assert controller.windows[0]._view_menu.title() == "&View"
    assert controller.windows[0]._project is project


def test_language_menu_switches_at_once_too(qtbot, controller) -> None:
    window = controller.new_window()
    actions = {action.text(): action for action in window._language_menu.actions()}
    actions["Čeština"].trigger()
    qtbot.waitUntil(lambda: len(controller.windows) == 1 and controller.windows[0] is not window)
    assert i18n.language() == i18n.CZECH


def test_choosing_the_active_language_does_not_rebuild(qtbot, controller) -> None:
    controller._settings.set("language", i18n.ENGLISH)
    window = controller.new_window()
    window._language_buttons[i18n.ENGLISH].click()
    QApplication.processEvents()
    assert controller.windows == [window]


def test_appearance_switches_at_once(qtbot, controller) -> None:
    theme.set_mode(theme.DARK_MODE)
    window = controller.new_window()
    window._apply_project_to_ui(_project())
    actions = {action.text(): action for action in window._appearance_menu.actions()}

    actions["Light"].trigger()
    qtbot.waitUntil(lambda: len(controller.windows) == 1 and controller.windows[0] is not window)

    assert theme.mode() == theme.LIGHT_MODE
    rebuilt = controller.windows[0]
    background = rebuilt._spectrum_widget._plot_widget.backgroundBrush().color().name().upper()
    assert background == theme.LIGHT["PLOT_BG"]
    assert rebuilt._project is window._project


def test_light_plot_in_dark_mode_switches_at_once(qtbot, controller) -> None:
    theme.set_mode(theme.DARK_MODE)
    window = controller.new_window()
    window._apply_project_to_ui(_project())

    window._light_plot_action.trigger()
    qtbot.waitUntil(lambda: len(controller.windows) == 1 and controller.windows[0] is not window)

    assert theme.mode() == theme.DARK_MODE
    rebuilt = controller.windows[0]
    background = rebuilt._spectrum_widget._plot_widget.backgroundBrush().color().name().upper()
    assert background == theme.LIGHT["PLOT_BG"]
    assert rebuilt._light_plot_action.isChecked()


def test_switch_waits_while_a_reference_search_runs(qtbot, controller, monkeypatch) -> None:
    window = controller.new_window()
    shown: list[str] = []
    monkeypatch.setattr(
        "PySide6.QtWidgets.QMessageBox.information",
        lambda *args, **kwargs: shown.append(args[2]),
    )
    window._reference_search_thread = object()  # type: ignore[assignment]
    try:
        window._language_buttons[i18n.CZECH].click()
    finally:
        window._reference_search_thread = None
    assert controller.windows == [window]
    assert i18n.language() == i18n.ENGLISH
    assert controller._settings.get("language") == i18n.CZECH
    assert shown
    assert "next time" in shown[0]


def test_standalone_window_keeps_the_restart_notice(qtbot, monkeypatch) -> None:
    """A window built without the controller cannot rebuild itself."""
    from unittest.mock import MagicMock

    from ui.main_window import MainWindow

    stored: dict = {}
    settings = MagicMock()
    settings.get.side_effect = lambda key, default=None: stored.get(key, default)
    settings.set.side_effect = lambda key, value: stored.__setitem__(key, value)
    db = MagicMock()
    db.get_vibration_presets.return_value = []
    window = MainWindow(db=db, settings=settings)
    qtbot.addWidget(window)
    shown: list[str] = []
    monkeypatch.setattr(
        "ui.main_window.QMessageBox.information", lambda *args, **kwargs: shown.append(args[2])
    )
    window._language_buttons[i18n.CZECH].click()
    assert stored["language"] == i18n.CZECH
    assert shown
    assert i18n.language() == i18n.ENGLISH
