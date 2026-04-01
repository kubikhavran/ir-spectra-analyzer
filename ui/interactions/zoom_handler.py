"""
ZoomHandler — Zoom v spektrálním vieweru.

Zodpovědnost:
- Scroll wheel zoom (center on cursor)
- Rectangle zoom selection
- Zoom reset (double-click nebo tlačítko)

Poznámka: PyQtGraph zpracovává základní zoom nativně.
Tato třída přidává rectangle zoom a programmatický reset.
"""
from __future__ import annotations

from PySide6.QtCore import QObject


class ZoomHandler(QObject):
    """Manages zoom interactions in the spectrum viewer."""
