"""
Theme — Jednotný vzhled aplikace.

Zodpovědnost:
- Jedna paleta barev, ze které berou všechny panely (žádné roztroušené hex kódy)
- Jeden stylesheet pro celou aplikaci: odstupy, okraje, výběr, záhlaví
- Styl "Fusion", aby aplikace vypadala stejně na Windows, macOS i Linuxu

Architektonické pravidlo:
  Panel si barvu nevymýšlí — vezme ji odsud. Když se má změnit odstín modré,
  mění se na jednom místě.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

# ── Palette ──────────────────────────────────────────────────────────────────
ACCENT = "#1F6FB2"  # selection, active tool, links
ACCENT_DARK = "#17537F"
ACCENT_SOFT = "#DCEAF6"  # hover / checked background
TEXT = "#1B2733"
TEXT_MUTED = "#5E6B78"
TEXT_FAINT = "#8A96A3"
BORDER = "#C9D1D9"
BORDER_STRONG = "#9AA7B4"
WINDOW = "#F3F5F7"  # window and panel background
SURFACE = "#FFFFFF"  # lists, tables, inputs, plot
SURFACE_ALT = "#F7F9FB"  # alternating rows
HEADER = "#E6EBF0"  # dock titles, table headers

SUCCESS = "#2E7D4F"
WARNING = "#B26A00"
DANGER = "#B3261E"
DANGER_SOFT = "#FBE9E7"

# Spectrum overlays — one visual language for every band marker in the plot.
REGION_CONFIRMED = "#1F6FB2"  # scored band that was found
REGION_EXPECTED = "#8A6D1B"  # expected band, weak or not found
REGION_MISSING = "#B3261E"  # required band that is absent
REGION_VIBRATION = "#0F8B8D"  # range of the vibration picked in the list
MATCH_HIGHLIGHT = "#CFE8D4"  # vibration that fits the active peak

# Match-quality colours (bar in the results list).
QUALITY_EXCELLENT = "#2E7D4F"
QUALITY_STRONG = "#1F6FB2"
QUALITY_POSSIBLE = "#C77700"
QUALITY_WEAK = "#9AA7B4"

# Relative peak-intensity pill badge colours (vs / s / m / w).
STRENGTH_VS_BG = "#DCEAF6"
STRENGTH_VS_FG = "#17537F"
STRENGTH_S_BG = "#DDF2EC"
STRENGTH_S_FG = "#166552"
STRENGTH_M_BG = "#FBF0D9"
STRENGTH_M_FG = "#8A5A00"
STRENGTH_W_BG = "#EEF1F5"
STRENGTH_W_FG = "#5E6B78"

#: Style for small secondary captions under or above a control.
CAPTION_STYLE = f"color: {TEXT_MUTED}; font-size: 9pt;"

#: Neutral card container for summary/detail blocks in side panels.
INFO_CARD_STYLE = (
    f"background: {SURFACE_ALT}; color: {TEXT}; "
    f"border: 1px solid {BORDER}; border-radius: 6px; padding: 6px 8px;"
)

#: Accent-tinted callout card for active selection / assignment previews.
ACCENT_CARD_STYLE = (
    f"background: {ACCENT_SOFT}; color: {TEXT}; "
    f"border: 1px solid {ACCENT}; border-radius: 6px; padding: 6px 8px;"
)

#: Prominent headline card for primary verdicts (e.g., Consensus top candidate).
HEADLINE_CARD_STYLE = (
    f"background: {SURFACE}; color: {TEXT}; "
    f"border: 1px solid {BORDER_STRONG}; border-left: 3px solid {ACCENT}; "
    "border-radius: 6px; padding: 8px 10px; font-weight: 600;"
)

#: Uppercase/bold section header inside panels and forms.
SECTION_TITLE_STYLE = (
    f"color: {TEXT_MUTED}; font-size: 8.5pt; font-weight: 600; "
    "padding-top: 4px; padding-bottom: 2px;"
)

#: Read-only metadata value badge.
READONLY_VALUE_STYLE = (
    f"color: {TEXT}; background: {SURFACE_ALT}; "
    f"border: 1px solid {BORDER}; border-radius: 4px; padding: 2px 6px;"
)

APP_STYLESHEET = f"""
QMainWindow, QDialog {{ background: {WINDOW}; }}

QToolTip {{
    background: #FFFFFF; color: {TEXT};
    border: 1px solid {BORDER_STRONG}; border-radius: 4px; padding: 4px 7px;
}}

/* ── Menus ──────────────────────────────────────────────────── */
QMenuBar {{
    background: {SURFACE}; color: {TEXT};
    border-bottom: 1px solid {BORDER}; padding: 1px 4px;
}}
QMenuBar::item {{
    background: transparent; padding: 4px 8px; border-radius: 4px;
}}
QMenuBar::item:selected {{ background: {ACCENT_SOFT}; color: {ACCENT_DARK}; }}
QMenu {{
    background: {SURFACE}; color: {TEXT};
    border: 1px solid {BORDER_STRONG}; border-radius: 6px; padding: 4px;
}}
QMenu::item {{
    padding: 5px 24px 5px 12px; border-radius: 4px;
}}
QMenu::item:selected {{ background: {ACCENT_SOFT}; color: {ACCENT_DARK}; }}
QMenu::item:disabled {{ color: {TEXT_FAINT}; }}
QMenu::separator {{
    height: 1px; background: {BORDER}; margin: 4px 6px;
}}

/* ── Main toolbar ───────────────────────────────────────────── */
QToolBar#mainToolbar {{
    background: {SURFACE}; border: none;
    border-bottom: 1px solid {BORDER}; padding: 4px 8px; spacing: 3px;
}}
QToolBar#mainToolbar QToolButton {{
    color: {TEXT}; background: transparent;
    border: 1px solid transparent; border-radius: 5px;
    padding: 4px 8px; min-width: 44px;
}}
QToolBar#mainToolbar QToolButton:hover {{
    background: {ACCENT_SOFT}; border-color: {BORDER};
}}
QToolBar#mainToolbar QToolButton:pressed {{ background: #C9DCEF; }}
QToolBar#mainToolbar QToolButton:checked {{
    background: {ACCENT_SOFT}; border-color: {ACCENT}; color: {ACCENT_DARK};
}}
QToolBar#mainToolbar QToolButton:disabled {{ color: {TEXT_FAINT}; }}
QToolBar#mainToolbar::separator {{
    background: {BORDER}; width: 1px; margin: 5px 6px;
}}
QToolBar#mainToolbar QLabel {{ color: {TEXT_MUTED}; }}
QWidget#toolbarSensitivityCapsule {{
    background: {SURFACE_ALT}; border: 1px solid {BORDER};
    border-radius: 6px;
}}

/* ── Docks and tabs ─────────────────────────────────────────── */
QDockWidget {{ color: {TEXT}; font-weight: 600; }}
QDockWidget::title {{
    background: {HEADER}; padding: 6px 10px;
    border-bottom: 1px solid {BORDER};
}}
QMainWindow::separator {{ background: {BORDER}; width: 1px; height: 1px; }}
QMainWindow::separator:hover {{ background: {ACCENT}; }}
QTabBar::tab {{
    background: {HEADER}; color: {TEXT_MUTED};
    border: 1px solid {BORDER}; border-top-left-radius: 4px; border-top-right-radius: 4px;
    padding: 5px 10px; margin-right: 1px;
}}
QTabBar::tab:selected {{
    background: {SURFACE}; color: {TEXT}; font-weight: 600;
    border-bottom: 2px solid {ACCENT};
}}
QTabBar::tab:hover:!selected {{ background: {ACCENT_SOFT}; color: {TEXT}; }}

/* ── Lists and tables ───────────────────────────────────────── */
QListWidget, QTableWidget, QTableView, QTreeWidget, QPlainTextEdit, QTextEdit {{
    background: {SURFACE}; color: {TEXT};
    border: 1px solid {BORDER}; border-radius: 5px;
    alternate-background-color: {SURFACE_ALT};
    selection-background-color: {ACCENT}; selection-color: #FFFFFF;
}}
QTableWidget, QTableView {{ gridline-color: #E3E8ED; }}
QHeaderView::section {{
    background: {HEADER}; color: {TEXT}; font-weight: 600;
    border: none; border-right: 1px solid {BORDER};
    border-bottom: 1px solid {BORDER}; padding: 5px 8px;
}}
QTableCornerButton::section {{ background: {HEADER}; border: none; }}

/* ── Scrollbars ─────────────────────────────────────────────── */
QScrollBar:vertical {{
    background: transparent; width: 8px; margin: 2px 1px 2px 1px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER_STRONG}; min-height: 24px; border-radius: 3px;
}}
QScrollBar::handle:vertical:hover {{ background: {ACCENT}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

QScrollBar:horizontal {{
    background: transparent; height: 8px; margin: 1px 2px 1px 2px;
}}
QScrollBar::handle:horizontal {{
    background: {BORDER_STRONG}; min-width: 24px; border-radius: 3px;
}}
QScrollBar::handle:horizontal:hover {{ background: {ACCENT}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0px; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}

/* ── Inputs and buttons ─────────────────────────────────────── */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {SURFACE}; color: {TEXT};
    border: 1px solid {BORDER}; border-radius: 4px;
    padding: 3px 7px; min-height: 18px;
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border-color: {ACCENT};
}}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{
    background: {WINDOW}; color: {TEXT_FAINT};
}}
QComboBox {{ min-height: 20px; padding-right: 18px; }}
QComboBox::drop-down {{
    subcontrol-origin: padding; subcontrol-position: top right;
    width: 18px; border-left: 1px solid {BORDER};
}}
QPushButton {{
    background: {SURFACE}; color: {TEXT};
    border: 1px solid {BORDER_STRONG}; border-radius: 5px;
    padding: 4px 12px; min-height: 18px;
}}
QPushButton:hover {{ background: {ACCENT_SOFT}; border-color: {ACCENT}; }}
QPushButton:pressed {{ background: #C9DCEF; }}
QPushButton:checked {{
    background: {ACCENT}; color: #FFFFFF; border-color: {ACCENT_DARK};
}}
QPushButton:disabled {{
    background: {WINDOW}; color: {TEXT_FAINT}; border-color: {BORDER};
}}
QPushButton[role="primary"] {{
    background: {ACCENT}; color: #FFFFFF; border-color: {ACCENT_DARK}; font-weight: 600;
}}
QPushButton[role="primary"]:hover {{ background: {ACCENT_DARK}; }}
QPushButton[role="primary"]:disabled {{
    background: {WINDOW}; color: {TEXT_FAINT}; border-color: {BORDER}; font-weight: normal;
}}
QPushButton[role="danger"] {{ color: {DANGER}; border-color: {DANGER}; }}
QPushButton[role="danger"]:hover {{ background: {DANGER_SOFT}; }}
QGroupBox {{
    border: 1px solid {BORDER}; border-radius: 6px;
    margin-top: 9px; padding: 8px 6px 6px 6px; color: {TEXT_MUTED}; font-weight: 600;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; }}

/* ── Status bar ─────────────────────────────────────────────── */
QStatusBar {{
    background: {SURFACE}; color: {TEXT}; border-top: 1px solid {BORDER};
}}
QStatusBar::item {{ border: none; }}
QStatusBar QLabel {{ color: {TEXT_MUTED}; padding: 0 8px; }}
QStatusBar QLabel[chip="true"] {{
    color: {ACCENT_DARK}; background: {ACCENT_SOFT};
    border-radius: 8px; padding: 1px 9px; margin: 2px 3px; font-weight: 600;
}}
"""


def apply_theme(app: QApplication) -> None:
    """Give the whole application the shared look.

    Fusion is used as the base style so the stylesheet lands on the same
    widget geometry on every platform; the native Windows style ignores parts
    of a stylesheet and mixes two looks in one window.
    """
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(WINDOW))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor(SURFACE))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(SURFACE_ALT))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor(SURFACE))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(SURFACE))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(TEXT_FAINT))
    palette.setColor(QPalette.ColorRole.Link, QColor(ACCENT))
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(TEXT_FAINT))
    app.setPalette(palette)
    app.setStyleSheet(APP_STYLESHEET)
