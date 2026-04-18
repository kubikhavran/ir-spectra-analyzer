# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec for IR Spectra Analyzer — macOS .app bundle.

Usage (from the project root, on macOS):

    pyinstaller packaging/ir-spectra-analyzer-mac.spec --clean --noconfirm

Produces:
    dist/IR Spectra Analyzer.app/

That .app is then wrapped in a DMG by the CI:

    dmgbuild -s packaging/dmg_settings.py "IR Spectra Analyzer" \\
        "dist/IR-Spectra-Analyzer-<version>-<arch>.dmg"

Notes
-----
* target_arch is intentionally left as None so PyInstaller builds for the
  host architecture (arm64 on macos-14, x86_64 on macos-13).
* The app is NOT signed/notarized. First-launch Gatekeeper prompt:
  right-click → Open, or the user runs:
      xattr -rd com.apple.quarantine "/Applications/IR Spectra Analyzer.app"
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

PROJECT_ROOT = Path(SPECPATH).resolve().parent
ASSETS = PROJECT_ROOT / "assets"
ICON_ICNS = ASSETS / "icon.icns"

datas = [
    (str(ASSETS / "icon.icns"), "assets"),
    (str(ASSETS / "icon.png"), "assets"),
]
datas += collect_data_files("rdkit")
datas += collect_data_files("spectrochempy")
datas += collect_data_files("matplotlib")

hiddenimports: list[str] = []
hiddenimports += collect_submodules("rdkit")
hiddenimports += collect_submodules("pyqtgraph")
hiddenimports += [
    "PySide6.QtSvg",
    "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtPrintSupport",
]

block_cipher = None

a = Analysis(
    [str(PROJECT_ROOT / "main.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "pytest_qt", "mypy", "ruff"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="IR Spectra Analyzer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON_ICNS) if ICON_ICNS.exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="IR Spectra Analyzer",
)

app = BUNDLE(
    coll,
    name="IR Spectra Analyzer.app",
    icon=str(ICON_ICNS) if ICON_ICNS.exists() else None,
    bundle_identifier="com.irspectra.analyzer",
    version="0.4.0",
    info_plist={
        "NSPrincipalClass": "NSApplication",
        "NSHighResolutionCapable": True,
        "CFBundleDisplayName": "IR Spectra Analyzer",
        "CFBundleShortVersionString": "0.4.0",
        "LSMinimumSystemVersion": "12.0",
        "NSRequiresAquaSystemAppearance": False,
        "CFBundleDocumentTypes": [
            {
                "CFBundleTypeName": "IR Spectrum",
                "CFBundleTypeExtensions": ["spa"],
                "CFBundleTypeRole": "Viewer",
            },
            {
                "CFBundleTypeName": "IR Spectra Analyzer Project",
                "CFBundleTypeExtensions": ["irproj"],
                "CFBundleTypeRole": "Editor",
            },
        ],
    },
)
