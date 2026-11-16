"""
Toolbar — Hlavní nástrojová lišta.

Zodpovědnost:
- Tool mode selection (Select / Zoom / Pan / Add Peak / Assign)
- Quick actions (Open, Save, Export PDF, Detect Peaks)
- Synchronizace aktivního nástroje se SpectrumWidget
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QSlider, QToolBar, QWidget

from processing.peak_detection import (
    DEFAULT_SENSITIVITY,
    SENSITIVITY_MAX,
    SENSITIVITY_MIN,
    clamp_sensitivity,
)


class MainToolbar(QToolBar):
    """Main application toolbar with tool mode selection."""

    tool_mode_changed = Signal(str)  # emits: "select", "zoom", "pan", "add_peak"
    correct_baseline = Signal()
    match_spectrum = Signal()
    clear_peaks = Signal()
    arrange_labels = Signal()
    #: Emits the new detection sensitivity (1–10) once the slider settles.
    sensitivity_changed = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__("Main Toolbar", parent)
        self._open_action: QAction | None = None
        self._export_action: QAction | None = None
        self._detect_action: QAction | None = None
        self._clear_peaks_action: QAction | None = None
        self._arrange_labels_action: QAction | None = None
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

        # Single-key shortcuts and tooltips. Text inputs take the key first, so
        # typing an "s" into a filter box still types an "s".
        for action, key, tip in (
            (self._select_action, "S", "Select — click a peak or its label to select it"),
            (self._zoom_action, "Z", "Zoom — drag a rectangle to zoom in"),
            (self._pan_action, "P", "Pan — drag to move the view, wheel to zoom"),
            (
                self._add_peak_action,
                "A",
                "Add Peak — click any point of the spectrum to label it "
                "(hold Ctrl to snap to the apex of the band under the pointer)",
            ),
        ):
            action.setShortcut(key)
            action.setToolTip(f"{tip} ({key})")

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

        self._setup_sensitivity_control()

        self._clear_peaks_action = QAction("Clear Peaks", self)
        self.addAction(self._clear_peaks_action)
        self._clear_peaks_action.triggered.connect(self.clear_peaks)

        self._arrange_labels_action = QAction("Arrange Labels", self)
        self.addAction(self._arrange_labels_action)
        self._arrange_labels_action.triggered.connect(self.arrange_labels)

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

        self._open_action.setToolTip("Open a spectrum file (Ctrl+O)")
        self._detect_action.setToolTip(
            "Find peaks automatically at the sensitivity set beside this button.\n"
            "Peaks that already carry an assignment are kept."
        )
        self._clear_peaks_action.setToolTip("Remove every peak (Ctrl+Z brings them back)")
        self._arrange_labels_action.setToolTip("Stagger overlapping peak labels")
        self._correct_baseline_action.setToolTip("Subtract a rubber-band baseline (Ctrl+Z to undo)")
        self._match_action.setToolTip("Compare the spectrum with the reference library (Ctrl+M)")
        self._match_action.setShortcut("Ctrl+M")
        self._export_action.setToolTip("Export a PDF report, CSV or Excel file (Ctrl+E)")
        self._export_action.setShortcut("Ctrl+E")

        if self._correct_baseline_action is not None:
            self._correct_baseline_action.triggered.connect(self.correct_baseline)

        if self._match_action is not None:
            self._match_action.triggered.connect(self.match_spectrum)

    def _setup_sensitivity_control(self) -> None:
        """Slider next to Detect Peaks that sets how faint a band still counts."""
        holder = QWidget(self)
        # Fixed width: a toolbar stretches an expanding widget, which pushed the
        # slider to the far end, away from its label and from Detect Peaks.
        holder.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        row = QHBoxLayout(holder)
        row.setContentsMargins(4, 0, 8, 0)
        row.setSpacing(4)

        tip = (
            "Detection sensitivity: 1 marks only the dominant bands, "
            f"{SENSITIVITY_MAX} also the faintest ones.\n"
            "After Detect Peaks, moving the slider re-detects straight away."
        )
        label = QLabel("Sensitivity")
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
        self._sensitivity_value.setFixedWidth(16)
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
