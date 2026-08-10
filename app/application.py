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
        self.new_window()
        if startup_path is not None:
            self.open_path(startup_path)
        pending, self._pending_open_paths = self._pending_open_paths, []
        for path in pending:
            self.open_path(path)

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

    def new_window(self) -> MainWindow:
        """Create, show and track another independent window."""
        from PySide6.QtCore import Qt  # noqa: PLC0415

        from ui.main_window import MainWindow  # noqa: PLC0415

        window = MainWindow(db=self._db, settings=self._settings)
        # Set here rather than in MainWindow so tests that build a window
        # directly keep their current lifetime.
        window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        window.new_window_requested.connect(self.new_window)
        window.destroyed.connect(lambda _=None, w=window: self._forget_window(w))
        self._windows.append(window)
        window.show()
        return window

    def _forget_window(self, window: MainWindow) -> None:
        """Drop a closed window so Qt can reclaim it.

        Compared by identity on purpose: ``destroyed`` fires after the C++ object
        is gone, and ``==`` on the stale wrapper would raise.
        """
        self._windows = [existing for existing in self._windows if existing is not window]
