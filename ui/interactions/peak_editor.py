"""
PeakEditor — Editace peaků (přesun, resize labelu, mazání).

Zodpovědnost:
- Drag&drop přesun peaku v grafu
- Přesun labelu (label_offset_x/y)
- Mazání peaku pravým klikem / Delete klávesou
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from core.peak import Peak


class PeakEditor(QObject):
    """Handles peak editing interactions (drag, delete, label move)."""

    peak_moved = Signal(object, float)         # (Peak, new_position)
    peak_deleted = Signal(object)              # (Peak,)
    label_moved = Signal(object, float, float) # (Peak, offset_x, offset_y)
