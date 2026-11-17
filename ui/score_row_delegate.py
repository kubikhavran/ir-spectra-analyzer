"""
ScoreRowDelegate — Řádek "název + skóre s pruhem" pro seznamy výsledků.

Zodpovědnost:
- Jednotné vykreslení hodnocených položek (funkční skupiny, hypotézy, shody):
  název vlevo, procenta zarovnaná do sloupce a pruh, jehož délka je skóre
- Kvalitu nese barva pruhu, text zůstává tmavý a čitelný

Seznamy dřív barvily celý řádek podle kvality — oranžový a světle modrý text
na bílé se špatně četl a čísla nebyla pod sebou.
"""

from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from ui import theme

#: Item data role holding the row's display name (str).
NAME_ROLE = 300
#: Item data role holding the score as a percentage 0–100 (float).
SCORE_ROLE = 301

_BAR_WIDTH = 54
_NUMBER_WIDTH = 50
_PADDING = 6


def score_color(percent: float) -> str:
    """Bar colour for a 0–100 score."""
    if percent >= 85.0:
        return theme.QUALITY_EXCELLENT
    if percent >= 70.0:
        return theme.QUALITY_STRONG
    if percent >= 50.0:
        return theme.QUALITY_POSSIBLE
    return theme.QUALITY_WEAK


class ScoreRowDelegate(QStyledItemDelegate):
    """Paints rows that carry NAME_ROLE and SCORE_ROLE as name · percent · bar."""

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        hint = super().sizeHint(option, index)
        return QSize(0, max(hint.height(), 24))

    def paint(self, painter, option, index) -> None:
        score = index.data(SCORE_ROLE)
        if score is None:
            super().paint(painter, option, index)
            return
        percent = max(0.0, min(float(score), 100.0))
        view_option = QStyleOptionViewItem(option)
        self.initStyleOption(view_option, index)
        name = str(index.data(NAME_ROLE) or view_option.text)
        view_option.text = ""
        if view_option.widget is not None:
            view_option.widget.style().drawControl(
                QStyle.ControlElement.CE_ItemViewItem, view_option, painter, view_option.widget
            )
        selected = bool(view_option.state & QStyle.StateFlag.State_Selected)
        rect: QRect = view_option.rect
        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)

        track = QRect(rect.right() - _BAR_WIDTH - _PADDING, rect.center().y() - 3, _BAR_WIDTH, 7)
        number_rect = QRect(
            track.left() - _NUMBER_WIDTH - 8, rect.top(), _NUMBER_WIDTH, rect.height()
        )
        name_rect = QRect(
            rect.left() + _PADDING,
            rect.top(),
            max(number_rect.left() - rect.left() - 2 * _PADDING, 10),
            rect.height(),
        )
        painter.setPen(QColor(theme.ON_ACCENT) if selected else QColor(theme.TEXT))
        painter.drawText(
            name_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            painter.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, name_rect.width()),
        )
        painter.drawText(
            number_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
            f"{percent:.1f}%",
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 70) if selected else QColor(theme.HEADER))
        painter.drawRoundedRect(track, 3, 3)
        fill = QRect(track)
        fill.setWidth(max(int(round(track.width() * percent / 100.0)), 2))
        painter.setBrush(QColor(theme.ON_ACCENT) if selected else QColor(score_color(percent)))
        painter.drawRoundedRect(fill, 3, 3)
        painter.restore()
