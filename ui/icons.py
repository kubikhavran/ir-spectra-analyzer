"""
Icons — Sada ikon aplikace.

Zodpovědnost:
- Jednotné čárové ikony (24 px mřížka, jedna tloušťka čáry) pro lištu a tlačítka
- Vykreslení ze SVG za běhu: ostré na HiDPI, bez souborů, které by se musely
  přibalovat do instalátoru

Ikony jsou uložené jako SVG cesty přímo tady. Aplikace žádné obrázky ikon
nenačítá z disku, takže v zabaleném buildu nemůže žádná chybět.
"""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from ui import theme

# Each entry is the inner markup of a 24×24 SVG drawn with a 1.8 px stroke.
_PATHS: dict[str, str] = {
    "open": '<path d="M3 7.5a2 2 0 0 1 2-2h4.2l2 2.2H19a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "save": (
        '<path d="M5 3.5h11l3.5 3.5v11.5a2 2 0 0 1-2 2h-12a2 2 0 0 1-2-2v-13a2 2 0 0 1 2-2z"/>'
        '<path d="M8 3.5v5h7v-5"/><path d="M7.5 20.5v-7h9v7"/>'
    ),
    "undo": '<path d="M8.5 13.5 4 9l4.5-4.5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
    "redo": '<path d="m15.5 13.5 4.5-4.5-4.5-4.5"/><path d="M20 9H9.5a5.5 5.5 0 0 0 0 11H13"/>',
    "select": '<path d="m4.5 3.5 6.6 16 2.4-7 7-2.4z"/>',
    "zoom": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m20.5 20.5-5.2-5.2"/><path d="M10.5 7.8v5.4M7.8 10.5h5.4"/>',
    "pan": (
        '<path d="M12 3v18M3 12h18"/>'
        '<path d="m9.2 5.8 2.8-2.8 2.8 2.8M9.2 18.2l2.8 2.8 2.8-2.8"/>'
        '<path d="m5.8 9.2-2.8 2.8 2.8 2.8M18.2 9.2l2.8 2.8-2.8 2.8"/>'
    ),
    "add_peak": '<path d="M2.5 19.5c4 0 4.6-11 7.5-11s3.5 11 7.5 11"/><path d="M18 3.5v6M15 6.5h6"/>',
    "detect": '<path d="M2.5 19.5 6 11l2.8 5.5L12 5l3 9.5 2.2-4 4.3 9"/>',
    "arrange": (
        '<path d="M6 20.5v-8M12 20.5V9M18 20.5v-6"/><path d="M3.8 9.5h4.4M9.8 6h4.4M15.8 11.5h4.4"/>'
    ),
    "clear": (
        '<path d="M4 7h16"/><path d="M9.5 7V4.2h5V7"/>'
        '<path d="m6.2 7 .9 12a2 2 0 0 0 2 1.8h5.8a2 2 0 0 0 2-1.8l.9-12"/>'
        '<path d="M10 11v6M14 11v6"/>'
    ),
    "baseline": (
        '<path d="M3 15.5c2.6 0 3.4-9 5.6-9s2.8 8 5 8 2-4.5 3.9-4.5 2 3 3.500 3"/>'
        '<path d="M3 20h18" stroke-dasharray="2.5 2.5"/>'
    ),
    "match": (
        '<path d="M3 17.500c3 0 3.800-10 6.500-10s3.500 10 6.500 10"/>'
        '<path d="M8 17.500c3 0 3.800-7 6.500-7s3.500 7 6.500 7" stroke-dasharray="2.5 2.2"/>'
    ),
    "export": (
        '<path d="M12 3.5v11.500"/><path d="m7.800 11 4.200 4.200 4.200-4.200"/>'
        '<path d="M4 16.500v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/>'
    ),
    "drop": (
        '<path d="M12 4v10.500"/><path d="m7.500 10.200 4.500 4.500 4.500-4.500"/>'
        '<path d="M4.500 15v3.500a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V15"/>'
    ),
}


def _svg(name: str, color: str) -> bytes:
    body = _PATHS[name]
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="1.8" stroke-linecap="round" '
        f'stroke-linejoin="round">{body}</svg>'
    ).encode()


def pixmap(name: str, size: int = 24, color: str = theme.TEXT, scale: float = 2.0) -> QPixmap:
    """Render one icon to a pixmap; ``scale`` is the device pixel ratio drawn for."""
    renderer = QSvgRenderer(QByteArray(_svg(name, color)))
    pixels = int(round(size * scale))
    image = QPixmap(QSize(pixels, pixels))
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter, QRectF(0, 0, pixels, pixels))
    painter.end()
    image.setDevicePixelRatio(scale)
    return image


@lru_cache(maxsize=64)
def icon(name: str) -> QIcon:
    """Icon with normal, active (accent) and disabled (faint) states."""
    result = QIcon()
    result.addPixmap(pixmap(name, color=theme.TEXT), QIcon.Mode.Normal, QIcon.State.Off)
    result.addPixmap(pixmap(name, color=theme.ACCENT_DARK), QIcon.Mode.Normal, QIcon.State.On)
    result.addPixmap(pixmap(name, color=theme.ACCENT_DARK), QIcon.Mode.Active, QIcon.State.Off)
    result.addPixmap(pixmap(name, color=theme.TEXT_FAINT), QIcon.Mode.Disabled, QIcon.State.Off)
    return result


def names() -> tuple[str, ...]:
    """Every icon this module can draw."""
    return tuple(_PATHS)
