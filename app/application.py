"""
Application — Hlavní aplikační třída.

Zodpovědnost:
- Inicializace a lifecycle management aplikace
- Vytvoření hlavního okna
- Inicializace databáze a nastavení
- Propojení core modelů s UI vrstvou

Architektura:
    Application
    ├── creates MainWindow (ui/main_window.py)
    ├── initializes Database (storage/database.py)
    ├── loads Settings (storage/settings.py)
    └── manages Project lifecycle (core/project.py)
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from app.runtime_imports import install_project_imports
from storage.database import Database
from storage.settings import Settings

install_project_imports()

if TYPE_CHECKING:
    from ui.main_window import MainWindow


class Application:
    """Main application controller managing lifecycle and component wiring."""

    def __init__(self) -> None:
        self._db = Database()
        self._settings = Settings()
        self._windows: list[MainWindow] = []
        self._pending_open_paths: list[str] = []

    @property
    def windows(self) -> list[MainWindow]:
        """Currently open windows, oldest first."""
        return list(self._windows)

    @property
    def _main_window(self) -> MainWindow | None:
        """The window an action without an explicit target should apply to.

        Prefers the one the user is actually looking at; falls back to the most
        recently opened so an OS file-open still lands somewhere sensible.
        """
        from PySide6.QtWidgets import QApplication  # noqa: PLC0415

        if QApplication.instance() is not None:
            active = QApplication.activeWindow()
            for window in self._windows:
                if window is active:
                    return window
        return self._windows[-1] if self._windows else None

    def run(self, startup_path: str | Path | None = None) -> None:
        """Initialize all components and show the first window."""
        self._db.initialize()
        self._settings.load()
        self._apply_language()
        self.new_window()
        if startup_path is not None:
            self.open_path(startup_path)
        pending, self._pending_open_paths = self._pending_open_paths, []
        for path in pending:
            self.open_path(path)

    def _apply_language(self) -> None:
        """Pick the UI language before the first window builds its texts.

        Dialogs are translated as they appear, by one application-wide filter,
        so each dialog does not need to know about languages itself.
        """
        from PySide6.QtCore import QEvent, QObject  # noqa: PLC0415
        from PySide6.QtWidgets import QApplication, QDialog  # noqa: PLC0415

        from ui import i18n  # noqa: PLC0415

        i18n.set_language(i18n.resolve_language(self._settings.get("language")))
        app = QApplication.instance()
        if app is None or getattr(self, "_dialog_translator", None) is not None:
            return

        class _DialogTranslator(QObject):
            def eventFilter(self, watched, event) -> bool:  # noqa: N802
                if event.type() == QEvent.Type.Show and isinstance(watched, QDialog):
                    i18n.translate_tree(watched)
                return False

        self._dialog_translator = _DialogTranslator(app)
        app.installEventFilter(self._dialog_translator)

    def open_path(self, path: str | Path) -> None:
        """Open an OS/CLI-supplied spectrum or project.

        An empty window is reused; otherwise the file gets its own window so the
        analysis already on screen is never replaced without asking.
        """
        normalized = str(Path(path).expanduser())
        target = self._main_window
        if target is None:
            self._pending_open_paths.append(normalized)
            return
        if target._project is not None:
            target = self.new_window()
        # MainWindow already owns the tested extension-aware open workflow. Keep
        # OS integration at the controller boundary without duplicating it here.
        target._open_recent_path(normalized)

    def new_window(self, *, show: bool = True) -> MainWindow:
        """Create, show and track another independent window."""
        from PySide6.QtCore import Qt  # noqa: PLC0415

        from ui.main_window import MainWindow  # noqa: PLC0415

        window = MainWindow(db=self._db, settings=self._settings)
        # Set here rather than in MainWindow so tests that build a window
        # directly keep their current lifetime.
        window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        window.new_window_requested.connect(lambda: self.new_window())
        window.open_path_requested.connect(self.open_path)
        window.language_change_requested.connect(self.apply_language_change)
        window.appearance_change_requested.connect(self.apply_appearance_change)
        window.enable_live_switching()
        window.destroyed.connect(lambda _=None, w=window: self._forget_window(w))
        self._windows.append(window)
        if show:
            window.show()
        return window

    def apply_language_change(self) -> None:
        """Switch to the stored language now: every window is rebuilt in it."""
        if not self._can_rebuild_windows():
            return
        self._apply_language()
        self._rebuild_windows()

    def apply_appearance_change(self) -> None:
        """Switch to the stored light/dark appearance now."""
        from PySide6.QtWidgets import QApplication  # noqa: PLC0415

        from ui import theme  # noqa: PLC0415

        if not self._can_rebuild_windows():
            return
        theme.set_mode(theme.resolve_mode(self._settings.get("appearance")))
        app = QApplication.instance()
        if isinstance(app, QApplication):
            theme.apply_theme(app)
        self._rebuild_windows()

    def _can_rebuild_windows(self) -> bool:
        """A running reference search would be cut off; then wait for the next start."""
        busy = next((window for window in self._windows if window.is_busy()), None)
        if busy is None:
            return True
        from PySide6.QtWidgets import QMessageBox  # noqa: PLC0415

        from ui.i18n import tr  # noqa: PLC0415

        QMessageBox.information(
            busy,
            tr("Operation in Progress"),
            tr(
                "Reference matching is still running. The change is saved and is "
                "used the next time the application starts."
            ),
        )
        return False

    def _rebuild_windows(self) -> None:
        """Replace every window with a fresh one that carries over its analysis.

        Texts and colours are set when widgets are built, so a new language or
        palette reaches every panel, dialog and plot by building them again.
        """
        for old in list(self._windows):
            window = self.new_window(show=False)
            window.adopt_from(old)
            if old.isMaximized():
                window.showMaximized()
            else:
                window.show()
            old.close_for_rebuild()

    def _forget_window(self, window: MainWindow) -> None:
        """Drop a closed window so Qt can reclaim it.

        Compared by identity on purpose: ``destroyed`` fires after the C++ object
        is gone, and ``==`` on the stale wrapper would raise.
        """
        self._windows = [existing for existing in self._windows if existing is not window]
