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
        self._main_window: MainWindow | None = None
        self._pending_open_paths: list[str] = []

    def run(self, startup_path: str | Path | None = None) -> None:
        """Initialize all components and show the main window."""
        self._db.initialize()
        self._settings.load()
        self._init_main_window()
        if self._main_window:
            self._main_window.show()
        if startup_path is not None:
            self.open_path(startup_path)
        pending, self._pending_open_paths = self._pending_open_paths, []
        for path in pending:
            self.open_path(path)

    def open_path(self, path: str | Path) -> None:
        """Open an OS/CLI-supplied spectrum or project in the main window."""
        normalized = str(Path(path).expanduser())
        if self._main_window is None:
            self._pending_open_paths.append(normalized)
            return
        # MainWindow already owns the tested extension-aware open workflow. Keep
        # OS integration at the controller boundary without duplicating it here.
        self._main_window._open_recent_path(normalized)

    def _init_main_window(self) -> None:
        """Create and configure the main application window."""
        from ui.main_window import MainWindow  # noqa: PLC0415

        self._main_window = MainWindow(db=self._db, settings=self._settings)
