"""A two-handle slider for a wavenumber window.

Drawn like the spectrum axis — high wavenumbers on the left — so a window can
be marked roughly by eye and then refined in the number boxes next to it.
Drag a handle to move one end, drag the shaded window to shift it, or click
the track to bring the nearer end there.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ui import theme
from ui.i18n import tr

_HANDLE_RADIUS = 7.0
_MARGIN = 18.0
_TRACK_Y = 12.0
_TICKS = (4000, 3500, 3000, 2500, 2000, 1500, 1000, 500)
_LABELLED = frozenset({4000, 3000, 2000, 1000})


def _round_pen(color: QColor, width: float) -> QPen:
    pen = QPen(color, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    return pen


class WavenumberRangeSlider(QWidget):
    """Select a window ``low``–``high`` cm⁻¹ between ``minimum`` and ``maximum``."""

    range_changed = Signal(float, float)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        minimum: float = 400.0,
        maximum: float = 4000.0,
        step: float = 5.0,
    ) -> None:
        super().__init__(parent)
        self._minimum = float(minimum)
        self._maximum = float(maximum)
        self._step = float(step)
        self._low = self._minimum
        self._high = self._maximum
        self._drag: str | None = None  # "low", "high" or "span"
        self._drag_origin = 0.0
        self._drag_window = (self._low, self._high)
        self.setMinimumWidth(220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        self.setToolTip(
            tr("Drag an end to move it, drag the window to shift it, or click the track")
        )

    # ------------------------------------------------------------------ values

    def values(self) -> tuple[float, float]:
        return self._low, self._high

    def set_values(self, low: float, high: float) -> None:
        """Show *low*–*high* (clamped to the slider) without emitting a signal."""
        low, high = sorted((float(low), float(high)))
        self._low = min(max(low, self._minimum), self._maximum)
        self._high = min(max(high, self._minimum), self._maximum)
        self.update()

    def _commit(self, low: float, high: float) -> None:
        low, high = sorted((low, high))
        if (low, high) == (self._low, self._high):
            return
        self._low, self._high = low, high
        self.update()
        self.range_changed.emit(low, high)

    def _snap(self, value: float) -> float:
        value = round(value / self._step) * self._step
        return min(max(value, self._minimum), self._maximum)

    # -------------------------------------------------------------- geometry

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return QSize(320, 34)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return QSize(220, 34)

    def _x_of(self, value: float) -> float:
        width = max(float(self.width()) - 2 * _MARGIN, 1.0)
        fraction = (self._maximum - value) / (self._maximum - self._minimum)
        return _MARGIN + fraction * width

    def _value_at(self, x: float) -> float:
        width = max(float(self.width()) - 2 * _MARGIN, 1.0)
        fraction = (x - _MARGIN) / width
        return self._maximum - fraction * (self._maximum - self._minimum)

    # ------------------------------------------------------------------ mouse

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        x = event.position().x()
        x_high, x_low = self._x_of(self._high), self._x_of(self._low)
        near_high = abs(x - x_high) <= _HANDLE_RADIUS + 2
        near_low = abs(x - x_low) <= _HANDLE_RADIUS + 2
        if near_high and near_low:
            # Both ends on one spot: the side of the click decides.
            self._drag = "high" if x < x_high else "low"
        elif near_high:
            self._drag = "high"
        elif near_low:
            self._drag = "low"
        elif x_high < x < x_low:
            self._drag = "span"
            self._drag_origin = self._value_at(x)
            self._drag_window = (self._low, self._high)
        else:
            value = self._snap(self._value_at(x))
            if abs(x - x_high) < abs(x - x_low):
                self._drag = "high"
                self._commit(self._low, max(value, self._low))
            else:
                self._drag = "low"
                self._commit(min(value, self._high), self._high)
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        x = event.position().x()
        if self._drag is None:
            inside = self._x_of(self._high) < x < self._x_of(self._low)
            cursor = Qt.CursorShape.SizeAllCursor if inside else Qt.CursorShape.SizeHorCursor
            self.setCursor(cursor)
            return
        value = self._snap(self._value_at(x))
        if self._drag == "high":
            self._commit(self._low, max(value, self._low))
        elif self._drag == "low":
            self._commit(min(value, self._high), self._high)
        else:
            low, high = self._drag_window
            shift = round((self._value_at(x) - self._drag_origin) / self._step) * self._step
            shift = min(max(shift, self._minimum - low), self._maximum - high)
            self._commit(low + shift, high + shift)
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        self._drag = None
        event.accept()

    # ------------------------------------------------------------------ paint

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        left, right = _MARGIN, self.width() - _MARGIN
        painter.setPen(_round_pen(QColor(theme.BORDER_STRONG), 4))
        painter.drawLine(QPointF(left, _TRACK_Y), QPointF(right, _TRACK_Y))

        x_high, x_low = self._x_of(self._high), self._x_of(self._low)
        accent = QColor(theme.ACCENT)
        painter.setPen(_round_pen(accent, 4))
        painter.drawLine(QPointF(x_high, _TRACK_Y), QPointF(x_low, _TRACK_Y))

        font = painter.font()
        font.setPointSizeF(max(font.pointSizeF() - 2.0, 6.5))
        painter.setFont(font)
        muted = QColor(theme.TEXT_MUTED)
        for tick in _TICKS:
            if not self._minimum <= tick <= self._maximum:
                continue
            x = self._x_of(tick)
            painter.setPen(QPen(muted, 1))
            painter.drawLine(QPointF(x, _TRACK_Y + 5), QPointF(x, _TRACK_Y + 8))
            if tick in _LABELLED:
                label = QRectF(x - 20, _TRACK_Y + 8, 40, 14)
                painter.drawText(label, Qt.AlignmentFlag.AlignCenter, str(tick))

        painter.setPen(QPen(QColor(theme.ACCENT_DARK), 1.5))
        painter.setBrush(QColor(theme.SURFACE))
        for x in (x_high, x_low):
            painter.drawEllipse(QPointF(x, _TRACK_Y), _HANDLE_RADIUS, _HANDLE_RADIUS)
        painter.end()
