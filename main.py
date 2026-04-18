"""
IR Spectra Analyzer — Main Entry Point

Spustí PySide6 aplikaci pro analýzu IR spekter.
"""

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.runtime_imports import install_project_imports


def _resource_path(relative: str) -> Path:
    """Resolve a bundled resource whether running from source or a PyInstaller build."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / relative


def main() -> None:
    """Initialize and run the IR Spectra Analyzer application."""
    install_project_imports()

    from app.application import Application  # noqa: PLC0415

    app = QApplication(sys.argv)
    app.setApplicationName("IR Spectra Analyzer")
    app.setApplicationVersion("0.4.0")
    app.setOrganizationName("IRSpectra")

    icon_path = _resource_path("assets/icon.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    main_app = Application()
    main_app.run()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
