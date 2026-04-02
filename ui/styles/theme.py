"""
Theme — Barevné schéma a fonty aplikace.

Zodpovědnost:
- Definice barev pro světlý a tmavý režim
- Fonty pro UI a vědecké popisky
- Qt stylesheet pro celou aplikaci
"""

from __future__ import annotations

# Dark theme colors (Catppuccin Mocha inspired)
BACKGROUND = "#1E1E2E"
FOREGROUND = "#CDD6F4"
ACCENT = "#89B4FA"
PEAK_COLOR = "#F38BA8"
GRID_COLOR = "#313244"
SPECTRUM_LINE = "#CDD6F4"

DARK_STYLESHEET = f"""
QMainWindow {{
    background-color: {BACKGROUND};
    color: {FOREGROUND};
}}
QWidget {{
    background-color: {BACKGROUND};
    color: {FOREGROUND};
}}
QTableWidget {{
    gridline-color: {GRID_COLOR};
}}
"""
