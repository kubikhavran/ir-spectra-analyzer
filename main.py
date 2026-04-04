"""
IR Spectra Analyzer — Main Entry Point

Spustí PySide6 aplikaci pro analýzu IR spekter.
"""

import sys

from PySide6.QtWidgets import QApplication

from app.runtime_imports import install_project_imports


def main() -> None:
    """Initialize and run the IR Spectra Analyzer application."""
    install_project_imports()

    from app.application import Application  # noqa: PLC0415

    app = QApplication(sys.argv)
    app.setApplicationName("IR Spectra Analyzer")
    app.setApplicationVersion("0.4.0")
    app.setOrganizationName("IRSpectra")

    main_app = Application()
    main_app.run()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
