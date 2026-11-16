"""
WelcomeOverlay — Úvodní plocha prázdného okna.

Zodpovědnost:
- Místo prázdného grafu říct, co se dá udělat: přetáhnout soubor, otevřít
  spektrum nebo projekt, vrátit se k naposledy otevřenému souboru
- Nic neotevírá sama — jen oznamuje, co si uživatel vybral

Leží přes plochu grafu a zmizí, jakmile je načtené spektrum.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui import icons, theme
from ui.i18n import tr

_MAX_RECENT = 5


class WelcomeOverlay(QFrame):
    """Start page shown over the plot while no spectrum is loaded."""

    open_spectrum_requested = Signal()
    open_project_requested = Signal()
    recent_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("welcomeOverlay")
        self.setStyleSheet(
            f"""
            QFrame#welcomeOverlay {{ background: {theme.SURFACE}; }}
            QFrame#dropCard {{
                background: {theme.SURFACE_ALT};
                border: 2px dashed {theme.BORDER_STRONG}; border-radius: 12px;
            }}
            QFrame#dropCard[dragActive="true"] {{
                background: {theme.ACCENT_SOFT}; border-color: {theme.ACCENT};
            }}
            QLabel#welcomeTitle {{ color: {theme.TEXT}; font-size: 15pt; font-weight: 600; }}
            QLabel#welcomeHint {{ color: {theme.TEXT_MUTED}; font-size: 10pt; }}
            QLabel#recentCaption {{ color: {theme.TEXT_MUTED}; font-size: 9pt; font-weight: 600; }}
            QListWidget#recentList {{ border: none; background: transparent; }}
            QListWidget#recentList::item {{ padding: 4px 6px; border-radius: 4px; }}
            QListWidget#recentList::item:hover {{ background: {theme.ACCENT_SOFT}; }}
            """
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.addStretch(2)

        self._card = QFrame()
        self._card.setObjectName("dropCard")
        self._card.setMaximumWidth(560)
        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(32, 28, 32, 28)
        card_layout.setSpacing(10)

        icon_label = QLabel()
        icon_label.setPixmap(icons.pixmap("drop", size=44, color=theme.ACCENT))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(icon_label)

        title = QLabel(tr("Drop a spectrum here"))
        title.setObjectName("welcomeTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(title)

        hint = QLabel(tr("OMNIC .spa, JCAMP-DX .jdx / .dx, or a saved .irproj project"))
        hint.setObjectName("welcomeHint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setWordWrap(True)
        card_layout.addWidget(hint)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addStretch()
        self._open_spectrum_btn = QPushButton(tr("Open Spectrum…"))
        self._open_spectrum_btn.setProperty("role", "primary")
        self._open_spectrum_btn.setToolTip("Ctrl+O")
        self._open_spectrum_btn.clicked.connect(self.open_spectrum_requested)
        buttons.addWidget(self._open_spectrum_btn)
        self._open_project_btn = QPushButton(tr("Open Project…"))
        self._open_project_btn.clicked.connect(self.open_project_requested)
        buttons.addWidget(self._open_project_btn)
        buttons.addStretch()
        card_layout.addSpacing(6)
        card_layout.addLayout(buttons)

        self._recent_caption = QLabel(tr("Recent files"))
        self._recent_caption.setObjectName("recentCaption")
        card_layout.addSpacing(10)
        card_layout.addWidget(self._recent_caption)

        self._recent_list = QListWidget()
        self._recent_list.setObjectName("recentList")
        self._recent_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._recent_list.setCursor(Qt.CursorShape.PointingHandCursor)
        self._recent_list.itemClicked.connect(self._on_recent_clicked)
        card_layout.addWidget(self._recent_list)

        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(self._card, 1)
        row.addStretch()
        outer.addLayout(row)
        outer.addStretch(3)
        self.set_recent_files([])

    def set_recent_files(self, paths: list[str]) -> None:
        """List the most recently opened files; the section hides when there are none."""
        self._recent_list.clear()
        shown = [str(path) for path in paths if str(path).strip()][:_MAX_RECENT]
        for path in shown:
            item = QListWidgetItem(Path(path).name)
            item.setToolTip(path)
            item.setData(Qt.ItemDataRole.UserRole, path)
            self._recent_list.addItem(item)
        has_recent = bool(shown)
        self._recent_caption.setVisible(has_recent)
        self._recent_list.setVisible(has_recent)
        self._recent_list.setFixedHeight(28 * len(shown) + 4 if has_recent else 0)

    def recent_files(self) -> list[str]:
        """Paths currently offered, in the order shown."""
        return [
            str(self._recent_list.item(row).data(Qt.ItemDataRole.UserRole))
            for row in range(self._recent_list.count())
        ]

    def set_drag_active(self, active: bool) -> None:
        """Highlight the card while a file is being dragged over the window."""
        self._card.setProperty("dragActive", "true" if active else "false")
        self._card.style().unpolish(self._card)
        self._card.style().polish(self._card)

    def _on_recent_clicked(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self.recent_requested.emit(str(path))
