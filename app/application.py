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

from app.runtime_imports import install_project_imports
from storage.database import Database
from storage.settings import Settings

install_project_imports()


class Application:
    """Main application controller managing lifecycle and component wiring."""

    def __init__(self) -> None:
        self._db = Database()
        self._settings = Settings()
        self._main_window = None

    def run(self) -> None:
        """Initialize all components and show the main window."""
        self._db.initialize()
        self._settings.load()
        self._init_main_window()
        if self._main_window:
            self._main_window.show()

    def _init_main_window(self) -> None:
        """Create and configure the main application window."""
        from ui.main_window import MainWindow  # noqa: PLC0415

        self._main_window = MainWindow(db=self._db, settings=self._settings)
