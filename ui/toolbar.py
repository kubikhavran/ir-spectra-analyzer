"""
Toolbar — Hlavní nástrojová lišta.

Zodpovědnost:
- Rychlé akce seskupené podle toho, k čemu slouží:
  soubor · historie · nástroje · píky · úpravy · porovnání · export
- Tool mode selection (Select / Zoom / Pan / Add Peak)
- Citlivost automatické detekce píků
- Synchronizace aktivního nástroje se SpectrumWidget
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QSlider, QToolBar, QWidget

from processing.peak_detection import (
    DEFAULT_SENSITIVITY,
    SENSITIVITY_MAX,
    SENSITIVITY_MIN,
    clamp_sensitivity,
)
from ui import icons, theme
from ui.i18n import tr


class MainToolbar(QToolBar):
    """Main application toolbar with tool mode selection."""

    tool_mode_changed = Signal(str)  # emits: "select", "zoom", "pan", "add_peak"
    correct_baseline = Signal()
    match_spectrum = Signal()
    clear_peaks = Signal()
    arrange_labels = Signal()
    save_requested = Signal()
    undo_requested = Signal()
    redo_requested = Signal()
    #: Emits the new detection sensitivity (1–10) once the slider settles.
    sensitivity_changed = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__("Main Toolbar", parent)
        self.setObjectName("mainToolbar")
        self.setMovable(False)
        self.setIconSize(QSize(22, 22))
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self._open_action: QAction | None = None
        self._save_action: QAction | None = None
        self._undo_action: QAction | None = None
        self._redo_action: QAction | None = None
        self._export_action: QAction | None = None
        self._detect_action: QAction | None = None
        self._clear_peaks_action: QAction | None = None
        self._arrange_labels_action: QAction | None = None
        self._correct_baseline_action: QAction | None = None
        self._match_action: QAction | None = None
        self._setup_actions()

    def _action(
        self,
        text: str,
        icon_name: str,
        tip: str,
        *,
        checkable: bool = False,
        icon_color: str | None = None,
    ) -> QAction:
        action = QAction(icons.icon(icon_name, color=icon_color), tr(text), self)
        action.setCheckable(checkable)
        action.setToolTip(tr(tip))
        self.addAction(action)
        return action

    def _setup_actions(self) -> None:
        """Create toolbar actions, one visual group per kind of task."""
        # ── File ─────────────────────────────────────────────────────────────
        self._open_action = self._action("Open", "open", "Open a spectrum file (Ctrl+O)")
        self._save_action = self._action("Save", "save", "Save the project to its file (Ctrl+S)")
        self._save_action.triggered.connect(self.save_requested)
        self.addSeparator()

        # ── History ──────────────────────────────────────────────────────────
        self._undo_action = self._action("Undo", "undo", "Undo the last step (Ctrl+Z)")
        self._undo_action.setEnabled(False)
        self._undo_action.triggered.connect(self.undo_requested)
        self._redo_action = self._action("Redo", "redo", "Redo the step just undone (Ctrl+Y)")
        self._redo_action.setEnabled(False)
        self._redo_action.triggered.connect(self.redo_requested)
        self.addSeparator()

        # ── Tool modes — mutually exclusive via QActionGroup ─────────────────
        mode_group = QActionGroup(self)
        mode_group.setExclusive(True)

        self._select_action = self._action(
            "Select",
            "select",
            "Select — click a peak or its label to select it (S)",
            checkable=True,
        )
        self._select_action.setChecked(True)
        self._zoom_action = self._action(
            "Zoom", "zoom", "Zoom — drag a rectangle to zoom in (Z)", checkable=True
        )
        self._pan_action = self._action(
            "Pan", "pan", "Pan — drag to move the view, wheel to zoom (P)", checkable=True
        )
        self._add_peak_action = self._action(
            "Add Peak",
            "add_peak",
            "Add Peak — click any point of the spectrum to label it "
            "(hold Ctrl to snap to the apex of the band under the pointer) (A)",
            checkable=True,
        )
        # Single-key shortcuts. Text inputs take the key first, so typing an
        # "s" into a filter box still types an "s".
        for action, key in (
            (self._select_action, "S"),
            (self._zoom_action, "Z"),
            (self._pan_action, "P"),
            (self._add_peak_action, "A"),
        ):
            mode_group.addAction(action)
            action.setShortcut(key)

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

        # ── Peaks ────────────────────────────────────────────────────────────
        self._detect_action = self._action(
            "Detect Peaks",
            "detect",
            "Find peaks automatically at the sensitivity set beside this button.\n"
            "Peaks that already carry an assignment are kept.",
            icon_color=theme.ACCENT,
        )
        self._setup_sensitivity_control()
        self._arrange_labels_action = self._action(
            "Arrange Labels", "arrange", "Stagger overlapping peak labels"
        )
        self._arrange_labels_action.triggered.connect(self.arrange_labels)
        self._clear_peaks_action = self._action(
            "Clear Peaks",
            "clear",
            "Remove every peak (Ctrl+Z brings them back)",
            icon_color=theme.DANGER,
        )
        self._clear_peaks_action.triggered.connect(self.clear_peaks)
        self.addSeparator()

        # ── Processing ───────────────────────────────────────────────────────
        self._correct_baseline_action = self._action(
            "Correct Baseline", "baseline", "Remove a rubber-band baseline (Ctrl+Z to undo)"
        )
        self._correct_baseline_action.triggered.connect(self.correct_baseline)
        self.addSeparator()

        # ── Library ──────────────────────────────────────────────────────────
        self._match_action = self._action(
            "Match Spectrum",
            "match",
            "Compare the spectrum with the reference library (Ctrl+M)",
            icon_color=theme.ACCENT,
        )
        self._match_action.setShortcut("Ctrl+M")
        self._match_action.triggered.connect(self.match_spectrum)
        self.addSeparator()

        # ── Output ───────────────────────────────────────────────────────────
        self._export_action = self._action(
            "Export",
            "export",
            "Export a PDF report, CSV or Excel file (Ctrl+E)",
            icon_color=theme.ACCENT,
        )
        self._export_action.setShortcut("Ctrl+E")

    def set_history_state(
        self, *, can_undo: bool, can_redo: bool, undo_text: str = "", redo_text: str = ""
    ) -> None:
        """Mirror the undo stack: enable the buttons and name the step in the tooltip."""
        if self._undo_action is not None:
            self._undo_action.setEnabled(can_undo)
            tip = tr("Undo the last step (Ctrl+Z)")
            self._undo_action.setToolTip(
                f"{tr('Undo')}: {undo_text} (Ctrl+Z)" if undo_text else tip
            )
        if self._redo_action is not None:
            self._redo_action.setEnabled(can_redo)
            tip = tr("Redo the step just undone (Ctrl+Y)")
            self._redo_action.setToolTip(
                f"{tr('Redo')}: {redo_text} (Ctrl+Y)" if redo_text else tip
            )

    def _setup_sensitivity_control(self) -> None:
        """Slider next to Detect Peaks that sets how faint a band still counts."""
        holder = QWidget(self)
        holder.setObjectName("toolbarSensitivityCapsule")
        # Fixed width: a toolbar stretches an expanding widget, which pushed the
        # slider to the far end, away from its label and from Detect Peaks.
        holder.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        row = QHBoxLayout(holder)
        row.setContentsMargins(8, 2, 8, 2)
        row.setSpacing(6)

        tip = tr(
            "Detection sensitivity: 1 marks only the dominant bands, "
            "10 also the faintest ones.\n"
            "After Detect Peaks, moving the slider re-detects straight away."
        )
        label = QLabel(tr("Sensitivity"))
        label.setToolTip(tip)
        row.addWidget(label)

        self._sensitivity_slider = QSlider(Qt.Orientation.Horizontal, holder)
        self._sensitivity_slider.setRange(SENSITIVITY_MIN, SENSITIVITY_MAX)
        self._sensitivity_slider.setPageStep(1)
        self._sensitivity_slider.setValue(DEFAULT_SENSITIVITY)
        self._sensitivity_slider.setFixedWidth(96)
        self._sensitivity_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._sensitivity_slider.setTickInterval(1)
        self._sensitivity_slider.setToolTip(tip)
        # Report the value when the handle is released, not at every step it
        # passes on the way — each report can re-run a detection.
        self._sensitivity_slider.setTracking(False)
        row.addWidget(self._sensitivity_slider)

        self._sensitivity_value = QLabel(str(DEFAULT_SENSITIVITY))
        self._sensitivity_value.setFixedWidth(20)
        self._sensitivity_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sensitivity_value.setStyleSheet(
            f"color: {theme.ACCENT_DARK}; background: {theme.ACCENT_SOFT}; "
            "border-radius: 4px; font-weight: 600; padding: 1px 2px;"
        )
        self._sensitivity_value.setToolTip(tip)
        row.addWidget(self._sensitivity_value)

        self._sensitivity_slider.sliderMoved.connect(
            lambda value: self._sensitivity_value.setText(str(value))
        )
        self._sensitivity_slider.valueChanged.connect(self._on_sensitivity_value_changed)
        self.addWidget(holder)

    def _on_sensitivity_value_changed(self, value: int) -> None:
        self._sensitivity_value.setText(str(value))
        self.sensitivity_changed.emit(int(value))

    def sensitivity(self) -> int:
        """Current peak-detection sensitivity (1–10)."""
        return int(self._sensitivity_slider.value())

    def set_sensitivity(self, value: object) -> None:
        """Show a stored sensitivity without announcing it as a user change."""
        level = clamp_sensitivity(value)
        blocked = self._sensitivity_slider.blockSignals(True)
        try:
            self._sensitivity_slider.setValue(level)
        finally:
            self._sensitivity_slider.blockSignals(blocked)
        self._sensitivity_value.setText(str(level))
