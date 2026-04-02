"""
PanHandler — Pan (posun pohledu) v spektrálním vieweru.

Zodpovědnost:
- Middle mouse button pan
- Space+drag pan
- Koordinace s nativním PyQtGraph pan

Poznámka: PyQtGraph zpracovává nativní pan.
Tato třída přidává custom pan módy.
"""

from __future__ import annotations

from PySide6.QtCore import QObject


class PanHandler(QObject):
    """Manages pan interactions in the spectrum viewer."""
