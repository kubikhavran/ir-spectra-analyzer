# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec for IR Spectra Analyzer.

Usage (from the project root):

    pyinstaller packaging/ir-spectra-analyzer.spec --clean --noconfirm

Produces:
    dist/IR Spectra Analyzer/IR Spectra Analyzer.exe   (+ supporting DLLs)

Notes
-----
* We ship as a one-folder (not one-file) bundle so startup is fast and Qt
  plugins load correctly. Inno Setup packages the folder into an installer.
* RDKit and SpectroChemPy both register data files that PyInstaller does not
  discover automatically — we collect their whole package trees below.
* `console=False` suppresses the black CMD window; the app is GUI-only.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

PROJECT_ROOT = Path(SPECPATH).resolve().parent
ASSETS = PROJECT_ROOT / "assets"
ICON = ASSETS / "icon.ico"

datas = [
    (str(ASSETS / "icon.ico"), "assets"),
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
    excludes=[
        "tkinter",
        "pytest",
        "pytest_qt",
        "mypy",
        "ruff",
    ],
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
    icon=str(ICON),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="IR Spectra Analyzer",
)
