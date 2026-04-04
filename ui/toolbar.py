"""
Toolbar — Hlavní nástrojová lišta.

Zodpovědnost:
- Tool mode selection (Select / Zoom / Pan / Add Peak / Assign)
- Quick actions (Open, Save, Export PDF, Detect Peaks)
- Synchronizace aktivního nástroje se SpectrumWidget
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QToolBar


class MainToolbar(QToolBar):
    """Main application toolbar with tool mode selection."""

    tool_mode_changed = Signal(str)  # emits: "select", "zoom", "pan", "add_peak"
    correct_baseline = Signal()
    match_spectrum = Signal()
    clear_peaks = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__("Main Toolbar", parent)
        self._open_action: QAction | None = None
        self._export_action: QAction | None = None
        self._detect_action: QAction | None = None
        self._clear_peaks_action: QAction | None = None
        self._correct_baseline_action: QAction | None = None
        self._match_action: QAction | None = None
        self._setup_actions()

    def _setup_actions(self) -> None:
        """Create toolbar actions."""
        # File actions
        self._open_action = QAction("Open", self)
        self.addAction(self._open_action)
        self.addSeparator()

        # Tool mode actions — mutually exclusive via QActionGroup
        mode_group = QActionGroup(self)
        mode_group.setExclusive(True)

        self._select_action = QAction("Select", self)
        self._select_action.setCheckable(True)
        self._select_action.setChecked(True)
        mode_group.addAction(self._select_action)
        self.addAction(self._select_action)

        self._zoom_action = QAction("Zoom", self)
        self._zoom_action.setCheckable(True)
        mode_group.addAction(self._zoom_action)
        self.addAction(self._zoom_action)

        self._pan_action = QAction("Pan", self)
        self._pan_action.setCheckable(True)
        mode_group.addAction(self._pan_action)
        self.addAction(self._pan_action)

        self._add_peak_action = QAction("Add Peak", self)
        self._add_peak_action.setCheckable(True)
        mode_group.addAction(self._add_peak_action)
        self.addAction(self._add_peak_action)

        # Connect mode actions
        self._select_action.toggled.connect(
            lambda checked: self.tool_mode_changed.emit("select") if checked else None
        )
        self._zoom_action.toggled.connect(
            lambda checked: self.tool_mode_changed.emit("zoom") if checked else None
        )
        self._pan_action.toggled.connect(
            lambda checked: self.tool_mode_changed.emit("pan") if checked else None
        )
        self._add_peak_action.toggled.connect(
            lambda checked: self.tool_mode_changed.emit("add_peak") if checked else None
        )

        self.addSeparator()

        # Peak detection
        self._detect_action = QAction("Detect Peaks", self)
        self.addAction(self._detect_action)

        self._clear_peaks_action = QAction("Clear Peaks", self)
        self.addAction(self._clear_peaks_action)
        self._clear_peaks_action.triggered.connect(self.clear_peaks)

        self.addSeparator()

        # Baseline correction action
        self._correct_baseline_action = QAction("Correct Baseline", self)
        self.addAction(self._correct_baseline_action)

        self.addSeparator()

        self._match_action = QAction("Match Spectrum", self)
        self.addAction(self._match_action)

        self.addSeparator()

        # Export action
        self._export_action = QAction("Export", self)
        self.addAction(self._export_action)

        if self._correct_baseline_action is not None:
            self._correct_baseline_action.triggered.connect(self.correct_baseline)

        if self._match_action is not None:
            self._match_action.triggered.connect(self.match_spectrum)
