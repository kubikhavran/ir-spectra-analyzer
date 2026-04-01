"""
Toolbar — Hlavní nástrojová lišta.

Zodpovědnost:
- Tool mode selection (Select / Zoom / Pan / Add Peak / Assign)
- Quick actions (Open, Save, Export PDF)
- Synchronizace aktivního nástroje se SpectrumWidget
"""
from __future__ import annotations

from PySide6.QtWidgets import QToolBar
from PySide6.QtCore import Signal


class MainToolbar(QToolBar):
    """Main application toolbar with tool mode selection."""

    tool_mode_changed = Signal(str)  # emits: "select", "zoom", "pan", "add_peak"

    def __init__(self, parent=None) -> None:
        super().__init__("Main Toolbar", parent)
        self._setup_actions()

    def _setup_actions(self) -> None:
        """Create toolbar actions."""
        self.addAction("Open")
        self.addSeparator()
        self.addAction("Select")
        self.addAction("Zoom")
        self.addAction("Pan")
        self.addAction("Add Peak")
        self.addSeparator()
        self.addAction("Export PDF")
