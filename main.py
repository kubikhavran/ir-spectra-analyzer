"""
IR Spectra Analyzer — Main Entry Point

Spustí PySide6 aplikaci pro analýzu IR spekter.
"""
import sys

from PySide6.QtWidgets import QApplication

from app.application import Application


def main() -> None:
    """Initialize and run the IR Spectra Analyzer application."""
    app = QApplication(sys.argv)
    app.setApplicationName("IR Spectra Analyzer")
    app.setApplicationVersion("0.1.0")
    app.setOrganizationName("IRSpectra")

    main_app = Application()
    main_app.run()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
