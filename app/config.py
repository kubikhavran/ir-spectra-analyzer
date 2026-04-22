"""
Config — Globální konfigurace a cesty.

Zodpovědnost:
- Definice cest k datovým souborům (DB, settings, logs)
- Aplikační konstanty
- Verze a metadata
"""

from __future__ import annotations

from pathlib import Path

APP_NAME = "IR Spectra Analyzer"
APP_VERSION = "0.6.1"
ORG_NAME = "IRSpectra"

# Data directories
DATA_DIR = Path.home() / ".ir-spectra-analyzer"
DB_PATH = DATA_DIR / "projects.db"
SETTINGS_PATH = DATA_DIR / "settings.json"
LOG_DIR = DATA_DIR / "logs"

# Spectral constants
WAVENUMBER_MIN = 400.0  # cm⁻¹
WAVENUMBER_MAX = 4000.0  # cm⁻¹
