"""
IR Spectra Analyzer — Main Entry Point

Spustí PySide6 aplikaci pro analýzu IR spekter.
"""

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.config import APP_NAME, APP_VERSION, ORG_NAME
from app.runtime_imports import install_project_imports

# Stable identity used for the Windows taskbar icon grouping (see below).
_APP_USER_MODEL_ID = "IRSpectra.IRSpectraAnalyzer"


def _resource_path(relative: str) -> Path:
    """Resolve a bundled resource whether running from source or a PyInstaller build."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / relative


def _set_windows_app_id() -> None:
    """Give Windows an explicit AppUserModelID.

    Without this a PyInstaller-frozen GUI app is grouped under the bootloader
    host process on the taskbar, which shows a blank/generic icon even when
    ``setWindowIcon`` is set. Harmless (and skipped) on non-Windows platforms.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes  # noqa: PLC0415

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(_APP_USER_MODEL_ID)
    except Exception:  # noqa: BLE001 — cosmetic only, never block startup
        pass


def _load_app_icon() -> QIcon:
    """Build the application icon from all available sources.

    Both the multi-resolution ``.ico`` (crisp small taskbar sizes) and the
    1024px ``.png`` (reliable rendering and high-DPI scaling) are added, so
    the window/taskbar/dock icon renders instead of showing a blank square.
    """
    icon = QIcon()
    for name in ("assets/icon.png", "assets/icon.ico", "assets/icon.icns"):
        path = _resource_path(name)
        if path.exists():
            icon.addFile(str(path))
    return icon


def main() -> None:
    """Initialize and run the IR Spectra Analyzer application."""
    install_project_imports()
    _set_windows_app_id()

    from app.application import Application  # noqa: PLC0415

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(ORG_NAME)

    app_icon = _load_app_icon()
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)

    main_app = Application()
    main_app.run()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
