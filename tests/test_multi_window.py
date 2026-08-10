"""Several windows may be open at once, each owning one independent project.

The point of the feature is comparing an analysis against an already-saved one,
so the guarantee that matters is isolation: nothing a user does in one window
may change what another window holds or writes to disk.
"""

import numpy as np
import pytest

from core.peak import Peak
from core.project import Project
from core.spectrum import SpectralUnit, Spectrum
from storage.database import Database
from storage.settings import Settings
from ui.main_window import MainWindow


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "projects.db")
    database.initialize()
    yield database
    database.close()


@pytest.fixture
def settings(tmp_path):
    stored = Settings(tmp_path / "settings.json")
    stored.load()
    return stored


def _spectrum(offset: float = 0.0) -> Spectrum:
    wavenumbers = np.linspace(400.0, 4000.0, 401)
    intensities = 100.0 - 30.0 * np.exp(-(((wavenumbers - (1700.0 + offset)) / 40.0) ** 2))
    return Spectrum(
        wavenumbers=wavenumbers, intensities=intensities, y_unit=SpectralUnit.TRANSMITTANCE
    )


def _window(qtbot, db, settings, name: str, offset: float = 0.0) -> MainWindow:
    window = MainWindow(db=db, settings=settings)
    qtbot.addWidget(window)
    window._project = Project(name=name, spectrum=_spectrum(offset))
    return window


def test_two_windows_hold_separate_projects(qtbot, db, settings):
    first = _window(qtbot, db, settings, "first")
    second = _window(qtbot, db, settings, "second", offset=200.0)

    assert first._project is not second._project
    assert first._project.name == "first"
    assert second._project.name == "second"


def test_editing_one_window_leaves_the_other_untouched(qtbot, db, settings):
    first = _window(qtbot, db, settings, "first")
    second = _window(qtbot, db, settings, "second")

    first._project.peaks.append(Peak(position=1700.0, intensity=70.0))

    assert len(first._project.peaks) == 1
    assert second._project.peaks == []


def test_undo_stacks_are_independent(qtbot, db, settings):
    from core.commands import AddPeakCommand

    first = _window(qtbot, db, settings, "first")
    second = _window(qtbot, db, settings, "second")

    first._undo_stack.push(AddPeakCommand(first._project, Peak(position=1700.0, intensity=70.0)))

    assert first._undo_stack.count() == 1
    assert second._undo_stack.count() == 0
    assert second._undo_stack.isClean()


def test_unsaved_marker_belongs_to_one_window(qtbot, db, settings):
    first = _window(qtbot, db, settings, "first")
    second = _window(qtbot, db, settings, "second")

    first._mark_non_undo_dirty()

    assert first._has_unsaved_changes()
    assert not second._has_unsaved_changes()
    assert first.windowTitle().startswith("*")
    assert not second.windowTitle().startswith("*")


def test_saving_one_window_writes_only_its_own_file(qtbot, db, settings, tmp_path):
    from storage.project_serializer import ProjectSerializer

    first = _window(qtbot, db, settings, "first")
    second = _window(qtbot, db, settings, "second", offset=200.0)
    first_path = tmp_path / "first.irproj"
    second_path = tmp_path / "second.irproj"

    ProjectSerializer().save(first._project, first_path)
    ProjectSerializer().save(second._project, second_path)

    reloaded_first = ProjectSerializer().load(first_path)
    reloaded_second = ProjectSerializer().load(second_path)
    assert reloaded_first.name == "first"
    assert reloaded_second.name == "second"
    assert not np.array_equal(
        reloaded_first.spectrum.intensities, reloaded_second.spectrum.intensities
    )


def test_saving_clears_the_marker_only_in_the_saving_window(qtbot, db, settings):
    first = _window(qtbot, db, settings, "first")
    second = _window(qtbot, db, settings, "second")
    first._mark_non_undo_dirty()
    second._mark_non_undo_dirty()

    first._mark_project_saved()

    assert not first._has_unsaved_changes()
    assert second._has_unsaved_changes()


def test_recent_menu_picks_up_a_file_opened_in_another_window(qtbot, db, settings):
    first = _window(qtbot, db, settings, "first")
    second = _window(qtbot, db, settings, "second")

    first._add_to_recent("/tmp/opened-elsewhere.irproj")
    # The submenu refreshes when it is opened, not when it is built.
    second._recent_menu.aboutToShow.emit()

    assert any(
        action.text() == "/tmp/opened-elsewhere.irproj" for action in second._recent_menu.actions()
    )


def test_controller_keeps_new_windows_alive_and_forgets_closed_ones(qtbot, db, settings):
    """A window dropped from the list would be garbage collected mid-session."""
    from app.application import Application

    controller = Application()
    controller._db = db
    controller._settings = settings

    first = controller.new_window()
    qtbot.addWidget(first)
    second = controller.new_window()
    qtbot.addWidget(second)
    assert controller.windows == [first, second]

    controller._forget_window(first)

    assert controller.windows == [second]


def test_controller_opens_a_file_next_to_an_occupied_window(qtbot, db, settings, tmp_path):
    """Opening from the OS must never silently replace an analysis in progress."""
    from app.application import Application

    controller = Application()
    controller._db = db
    controller._settings = settings

    occupied = controller.new_window()
    qtbot.addWidget(occupied)
    occupied._project = Project(name="in progress", spectrum=_spectrum())
    opened: list[str] = []
    created: list[MainWindow] = []
    original_new_window = controller.new_window

    def _tracked_new_window():
        window = original_new_window()
        qtbot.addWidget(window)
        window._open_recent_path = opened.append  # type: ignore[method-assign]
        created.append(window)
        return window

    controller.new_window = _tracked_new_window  # type: ignore[method-assign]
    controller.open_path(tmp_path / "other.irproj")

    assert len(created) == 1, "the occupied window should have been left alone"
    assert opened == [str(tmp_path / "other.irproj")]
    assert occupied._project.name == "in progress"


def test_new_window_action_only_asks_the_controller(qtbot, db, settings):
    """MainWindow must not create windows itself — Application owns their lifetime."""
    window = _window(qtbot, db, settings, "first")
    requests: list[int] = []
    window.new_window_requested.connect(lambda: requests.append(1))

    action = next(a for a in window.menuBar().actions() if a.text() == "&File")
    new_window_action = next(a for a in action.menu().actions() if a.text() == "New &Window")
    new_window_action.trigger()

    assert requests == [1]
