"""
Theme — Jednotný vzhled aplikace.

Zodpovědnost:
- Jedna paleta barev, ze které berou všechny panely (žádné roztroušené hex kódy)
- Jeden stylesheet pro celou aplikaci: odstupy, okraje, výběr, záhlaví
- Styl "Fusion", aby aplikace vypadala stejně na Windows, macOS i Linuxu

Architektonické pravidlo:
  Panel si barvu nevymýšlí — vezme ji odsud. Když se má změnit odstín modré,
  mění se na jednom místě.

Světlý a tmavý vzhled:
  Paleta má světlou (LIGHT) a tmavou (DARK) variantu. ``set_mode`` je
  přepne ještě před sestavením oken; panely čtou ``theme.X`` až při
  vytváření nebo kreslení. Exporty (PDF, XLSX, obrázky struktur) zůstávají
  vždy světlé.
"""

from __future__ import annotations

import os

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

# ── Palettes ─────────────────────────────────────────────────────────────────
# Every colour the interface uses, in a light and a dark variant. The module
# attributes below (ACCENT, TEXT, …) always hold the active palette; panels
# read them as ``theme.TEXT`` when they build or paint, never copy them early.
LIGHT: dict[str, str] = {
    "ACCENT": "#1F6FB2",  # selection, active tool, links
    "ACCENT_DARK": "#17537F",  # accent text on ACCENT_SOFT
    "ACCENT_SOFT": "#DCEAF6",  # hover / checked background
    "TEXT": "#1B2733",
    "TEXT_MUTED": "#5E6B78",
    "TEXT_FAINT": "#8A96A3",
    "BORDER": "#C9D1D9",
    "BORDER_STRONG": "#9AA7B4",
    "WINDOW": "#F3F5F7",  # window and panel background
    "SURFACE": "#FFFFFF",  # lists, tables, inputs
    "SURFACE_ALT": "#F7F9FB",  # alternating rows
    "HEADER": "#E6EBF0",  # dock titles, table headers
    "SUCCESS": "#2E7D4F",
    "WARNING": "#B26A00",
    "DANGER": "#B3261E",
    "DANGER_SOFT": "#FBE9E7",
    # Spectrum overlays — one visual language for every band marker in the plot.
    "REGION_CONFIRMED": "#1F6FB2",  # scored band that was found
    "REGION_EXPECTED": "#8A6D1B",  # expected band, weak or not found
    "REGION_MISSING": "#B3261E",  # required band that is absent
    "REGION_VIBRATION": "#0F8B8D",  # range of the vibration picked in the list
    "MATCH_HIGHLIGHT": "#CFE8D4",  # vibration that fits the active peak
    # Match-quality colours (bar in the results list).
    "QUALITY_EXCELLENT": "#2E7D4F",
    "QUALITY_STRONG": "#1F6FB2",
    "QUALITY_POSSIBLE": "#C77700",
    "QUALITY_WEAK": "#9AA7B4",
    # Relative peak-intensity pill badge colours (vs / s / m / w).
    "STRENGTH_VS_BG": "#DCEAF6",
    "STRENGTH_VS_FG": "#17537F",
    "STRENGTH_S_BG": "#DDF2EC",
    "STRENGTH_S_FG": "#166552",
    "STRENGTH_M_BG": "#FBF0D9",
    "STRENGTH_M_FG": "#8A5A00",
    "STRENGTH_W_BG": "#EEF1F5",
    "STRENGTH_W_FG": "#5E6B78",
    # Odds and ends that used to be spelled out where they were used.
    "ON_ACCENT": "#FFFFFF",  # text and marks on an ACCENT background
    "ON_ACCENT_MUTED": "#DDE8F3",  # secondary text on an ACCENT background
    "TOOLTIP_BG": "#FFFFFF",
    "PRESSED": "#C9DCEF",
    "GRIDLINE": "#E3E8ED",
    "SUCCESS_SOFT": "#DDF2EC",
    "WARNING_SOFT": "#FBF0D9",
    "ROW_POSITIVE": "#E8F6F3",  # table row of a group whose bands are present
    "TOOLBAR_BAR": "#EEF1F4",  # strip above the plot
    "OVERLAY_BAR": "#E4F0FB",  # reference-overlay strip above the plot
    "OVERLAY_BORDER": "#7F9DB9",
    # Spectrum plot.
    "PLOT_BG": "#FFFFFF",
    "PLOT_FG": "#000000",  # axes, ticks, the spectrum trace, peak labels
    "PLOT_LEADER": "#000000",  # thin line from a peak to its label
    # Chemistry drawing (molecule editor); structures in reports stay light.
    "MOLECULE_BOND": "#0F172A",
}

DARK: dict[str, str] = {
    "ACCENT": "#3A86D0",
    "ACCENT_DARK": "#9CCBF5",
    "ACCENT_SOFT": "#1F3A56",
    # Text kept bright on purpose: thin UI fonts on a dark background read
    # weaker than the contrast ratio suggests.
    "TEXT": "#F1F4F8",
    "TEXT_MUTED": "#C4CDD7",
    "TEXT_FAINT": "#919DAB",
    "BORDER": "#3A4552",
    "BORDER_STRONG": "#56626F",
    "WINDOW": "#1B2027",
    "SURFACE": "#232A33",
    "SURFACE_ALT": "#29313B",
    "HEADER": "#2C3540",
    "SUCCESS": "#5CBF85",
    "WARNING": "#E3A54A",
    "DANGER": "#F06A60",
    "DANGER_SOFT": "#40221F",
    "REGION_CONFIRMED": "#4C9EEB",
    "REGION_EXPECTED": "#D9B54E",
    "REGION_MISSING": "#F06A60",
    "REGION_VIBRATION": "#3CC6C8",
    "MATCH_HIGHLIGHT": "#24452F",
    "QUALITY_EXCELLENT": "#5CBF85",
    "QUALITY_STRONG": "#4C9EEB",
    "QUALITY_POSSIBLE": "#E3A54A",
    "QUALITY_WEAK": "#6F7B89",
    "STRENGTH_VS_BG": "#1F3A56",
    "STRENGTH_VS_FG": "#9CCBF5",
    "STRENGTH_S_BG": "#173B33",
    "STRENGTH_S_FG": "#7FD6BC",
    "STRENGTH_M_BG": "#45371A",
    "STRENGTH_M_FG": "#F0C36B",
    "STRENGTH_W_BG": "#2C3540",
    "STRENGTH_W_FG": "#C4CDD7",
    "ON_ACCENT": "#FFFFFF",
    "ON_ACCENT_MUTED": "#DCE9F6",
    "TOOLTIP_BG": "#2C3540",
    "PRESSED": "#28496B",
    "GRIDLINE": "#333D48",
    "SUCCESS_SOFT": "#173B33",
    "WARNING_SOFT": "#45371A",
    "ROW_POSITIVE": "#1D3A33",
    "TOOLBAR_BAR": "#212831",
    "OVERLAY_BAR": "#1C3046",
    "OVERLAY_BORDER": "#3E5873",
    "PLOT_BG": "#161B21",
    "PLOT_FG": "#D9E0E8",
    "PLOT_LEADER": "#8D99A6",
    "MOLECULE_BOND": "#E2E8F0",
}

LIGHT_MODE = "light"
DARK_MODE = "dark"
SYSTEM_MODE = "system"
#: (setting value, menu label) for View → Appearance.
APPEARANCES: tuple[tuple[str, str], ...] = (
    (SYSTEM_MODE, "Follow system"),
    (LIGHT_MODE, "Light"),
    (DARK_MODE, "Dark"),
)
ENV_VAR = "IR_SPECTRA_APPEARANCE"

_mode = LIGHT_MODE
_light_plot = False

#: Colours of the spectrum plot. With ``light_plot`` the dark appearance keeps
#: these from the light palette: a white plot in an otherwise dark window.
PLOT_KEYS: tuple[str, ...] = (
    "PLOT_BG",
    "PLOT_FG",
    "PLOT_LEADER",
    "REGION_CONFIRMED",
    "REGION_EXPECTED",
    "REGION_MISSING",
    "REGION_VIBRATION",
)
#: Setting that keeps the spectrum plot light in the dark appearance.
LIGHT_PLOT_SETTING = "light_plot_in_dark"

# The active palette, as module constants (``set_mode`` swaps them).
ACCENT = LIGHT["ACCENT"]
ACCENT_DARK = LIGHT["ACCENT_DARK"]
ACCENT_SOFT = LIGHT["ACCENT_SOFT"]
TEXT = LIGHT["TEXT"]
TEXT_MUTED = LIGHT["TEXT_MUTED"]
TEXT_FAINT = LIGHT["TEXT_FAINT"]
BORDER = LIGHT["BORDER"]
BORDER_STRONG = LIGHT["BORDER_STRONG"]
WINDOW = LIGHT["WINDOW"]
SURFACE = LIGHT["SURFACE"]
SURFACE_ALT = LIGHT["SURFACE_ALT"]
HEADER = LIGHT["HEADER"]
SUCCESS = LIGHT["SUCCESS"]
WARNING = LIGHT["WARNING"]
DANGER = LIGHT["DANGER"]
DANGER_SOFT = LIGHT["DANGER_SOFT"]
REGION_CONFIRMED = LIGHT["REGION_CONFIRMED"]
REGION_EXPECTED = LIGHT["REGION_EXPECTED"]
REGION_MISSING = LIGHT["REGION_MISSING"]
REGION_VIBRATION = LIGHT["REGION_VIBRATION"]
MATCH_HIGHLIGHT = LIGHT["MATCH_HIGHLIGHT"]
QUALITY_EXCELLENT = LIGHT["QUALITY_EXCELLENT"]
QUALITY_STRONG = LIGHT["QUALITY_STRONG"]
QUALITY_POSSIBLE = LIGHT["QUALITY_POSSIBLE"]
QUALITY_WEAK = LIGHT["QUALITY_WEAK"]
STRENGTH_VS_BG = LIGHT["STRENGTH_VS_BG"]
STRENGTH_VS_FG = LIGHT["STRENGTH_VS_FG"]
STRENGTH_S_BG = LIGHT["STRENGTH_S_BG"]
STRENGTH_S_FG = LIGHT["STRENGTH_S_FG"]
STRENGTH_M_BG = LIGHT["STRENGTH_M_BG"]
STRENGTH_M_FG = LIGHT["STRENGTH_M_FG"]
STRENGTH_W_BG = LIGHT["STRENGTH_W_BG"]
STRENGTH_W_FG = LIGHT["STRENGTH_W_FG"]
ON_ACCENT = LIGHT["ON_ACCENT"]
ON_ACCENT_MUTED = LIGHT["ON_ACCENT_MUTED"]
TOOLTIP_BG = LIGHT["TOOLTIP_BG"]
PRESSED = LIGHT["PRESSED"]
GRIDLINE = LIGHT["GRIDLINE"]
SUCCESS_SOFT = LIGHT["SUCCESS_SOFT"]
WARNING_SOFT = LIGHT["WARNING_SOFT"]
ROW_POSITIVE = LIGHT["ROW_POSITIVE"]
TOOLBAR_BAR = LIGHT["TOOLBAR_BAR"]
OVERLAY_BAR = LIGHT["OVERLAY_BAR"]
OVERLAY_BORDER = LIGHT["OVERLAY_BORDER"]
PLOT_BG = LIGHT["PLOT_BG"]
PLOT_FG = LIGHT["PLOT_FG"]
PLOT_LEADER = LIGHT["PLOT_LEADER"]
MOLECULE_BOND = LIGHT["MOLECULE_BOND"]
CAPTION_STYLE = ""
INFO_CARD_STYLE = ""
ACCENT_CARD_STYLE = ""
HEADLINE_CARD_STYLE = ""
SECTION_TITLE_STYLE = ""
READONLY_VALUE_STYLE = ""
APP_STYLESHEET = ""


def _build_styles() -> None:
    """(Re)build the stylesheet strings from the active palette."""
    global CAPTION_STYLE, INFO_CARD_STYLE, ACCENT_CARD_STYLE, HEADLINE_CARD_STYLE
    global SECTION_TITLE_STYLE, READONLY_VALUE_STYLE, APP_STYLESHEET

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
    background: {TOOLTIP_BG}; color: {TEXT};
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
QToolBar#mainToolbar QToolButton:pressed {{ background: {PRESSED}; }}
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
    selection-background-color: {ACCENT}; selection-color: {ON_ACCENT};
}}
QTableWidget, QTableView {{ gridline-color: {GRIDLINE}; }}
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
QComboBox {{ min-height: 20px; }}
QPushButton {{
    background: {SURFACE}; color: {TEXT};
    border: 1px solid {BORDER_STRONG}; border-radius: 5px;
    padding: 4px 12px; min-height: 18px;
}}
QPushButton:hover {{ background: {ACCENT_SOFT}; border-color: {ACCENT}; }}
QPushButton:pressed {{ background: {PRESSED}; }}
QPushButton:checked {{
    background: {ACCENT}; color: {ON_ACCENT}; border-color: {ACCENT_DARK};
}}
QPushButton:disabled {{
    background: {WINDOW}; color: {TEXT_FAINT}; border-color: {BORDER};
}}
QPushButton[role="primary"] {{
    background: {ACCENT}; color: {ON_ACCENT}; border-color: {ACCENT_DARK}; font-weight: 600;
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


def mode() -> str:
    """The active appearance: ``"light"`` or ``"dark"``."""
    return _mode


def is_dark() -> bool:
    return _mode == DARK_MODE


def light_plot() -> bool:
    """Whether the spectrum plot stays light in the dark appearance."""
    return _light_plot


def set_mode(appearance: str, *, light_plot: bool | None = None) -> str:
    """Switch every colour constant to the light or dark palette.

    *light_plot* keeps the spectrum plot light in the dark appearance
    (``None`` leaves the current choice). Call it before any window is built
    (the main window, panels and dialogs read the constants when they are
    created). Returns the mode actually used.
    """
    global _mode, _light_plot
    if light_plot is not None:
        _light_plot = bool(light_plot)
    chosen = DARK_MODE if appearance == DARK_MODE else LIGHT_MODE
    globals().update(DARK if chosen == DARK_MODE else LIGHT)
    if chosen == DARK_MODE and _light_plot:
        globals().update({key: LIGHT[key] for key in PLOT_KEYS})
    _mode = chosen
    _build_styles()
    return chosen


def resolve_mode(setting: object) -> str:
    """Turn the stored preference (``light``/``dark``/``system``) into a mode.

    The ``IR_SPECTRA_APPEARANCE`` environment variable wins over the setting;
    ``system`` follows the operating system's dark-mode switch.
    """
    override = os.environ.get(ENV_VAR, "").strip().lower()
    if override in (LIGHT_MODE, DARK_MODE):
        return override
    if setting in (LIGHT_MODE, DARK_MODE):
        return str(setting)
    try:
        from PySide6.QtCore import Qt  # noqa: PLC0415
        from PySide6.QtGui import QGuiApplication  # noqa: PLC0415

        app = QGuiApplication.instance()
        if app is not None:
            hints = QGuiApplication.styleHints()
            if hints.colorScheme() == Qt.ColorScheme.Dark:
                return DARK_MODE
    except Exception:  # noqa: BLE001 - older Qt without colour scheme support
        pass
    return LIGHT_MODE


set_mode(LIGHT_MODE)


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
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(TOOLTIP_BG))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(ON_ACCENT))
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
