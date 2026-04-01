"""
MainWindow — Hlavní okno aplikace.

Zodpovědnost:
- Dockable panel layout (spectrum viewer + peak table + metadata + vibration panel)
- Menu bar a toolbar akce
- Signál-slot propojení mezi komponentami
- Koordinace workflow: otevření souboru → analýza → export

Architektonické pravidlo:
  MainWindow NIKDY neprovádí výpočty ani I/O.
  Deleguje na core modely a processing funkce.
"""
from __future__ import annotations

from PySide6.QtWidgets import QMainWindow, QFileDialog, QMessageBox

from storage.database import Database
from storage.settings import Settings


class MainWindow(QMainWindow):
    """Main application window with dockable analysis panels."""

    def __init__(
        self,
        db: Database,
        settings: Settings,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._db = db
        self._settings = settings
        self._project = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Initialize UI layout, menus, and dock panels."""
        self.setWindowTitle("IR Spectra Analyzer")
        self.setMinimumSize(1200, 800)
        self._setup_menu()

    def _setup_menu(self) -> None:
        """Create the main menu bar."""
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("&File")
        open_action = file_menu.addAction("&Open SPA...")
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self._on_open_file)
        file_menu.addSeparator()
        exit_action = file_menu.addAction("E&xit")
        exit_action.triggered.connect(self.close)

        help_menu = menu_bar.addMenu("&Help")
        about_action = help_menu.addAction("&About")
        about_action.triggered.connect(self._on_about)

    def _on_open_file(self) -> None:
        """Handle File → Open SPA action."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open IR Spectrum",
            "",
            "OMNIC SPA Files (*.spa);;All Files (*)",
        )
        if path:
            self._load_spectrum(path)

    def _load_spectrum(self, path: str) -> None:
        """Load a spectrum file and update the UI."""
        from pathlib import Path  # noqa: PLC0415
        from io.format_registry import FormatRegistry  # noqa: PLC0415
        from core.project import Project  # noqa: PLC0415

        try:
            registry = FormatRegistry()
            spectrum = registry.read(Path(path))
            self._project = Project(name=Path(path).stem, spectrum=spectrum)
            self.statusBar().showMessage(
                f"Loaded: {Path(path).name} ({spectrum.n_points} points)"
            )
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Error", f"Failed to load spectrum:\n{e}")

    def _on_about(self) -> None:
        """Show About dialog."""
        from ui.dialogs.about_dialog import AboutDialog  # noqa: PLC0415
        AboutDialog(self).exec()
