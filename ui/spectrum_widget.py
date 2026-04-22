"""
SpectrumWidget — Interaktivní spektrální viewer.

Zodpovědnost:
- Vykreslování IR spektra pomocí PyQtGraph (>1000 FPS)
- Interaktivní zoom (scroll wheel, rectangle zoom)
- Pan (drag)
- Zobrazení peakových anotací (šipky + labely)
- Callback pro peak picking (klik = přidání peaku)

Architektonické pravidlo:
  Widget zobrazuje data — nevlastní je. Přijímá Spectrum a List[Peak]
  a renderuje. Uživatelské akce (click) emituje jako Qt signály nahoru.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from core.peak import Peak
from core.spectrum import Spectrum

# Default visible X range (standard IR region)
_X_DEFAULT_MIN = 400.0
_X_DEFAULT_MAX = 3800.0

# Distinct colors for reference spectrum overlays
_OVERLAY_COLORS = [
    "#2980B9",  # blue
    "#E67E22",  # orange
    "#27AE60",  # green
    "#8E44AD",  # purple
    "#C0392B",  # red
]

_PEAK_LABEL_FONT_SIZE_PT = 8.0


class _DraggableLabel(pg.TextItem):
    """TextItem with a live OMNIC-style leader line.

    The leader goes vertically from the peak apex almost to the label,
    then a short diagonal segment connects to the label position.
    The elbow is always `label_offset` away from the label toward the peak,
    so the line extends naturally when the label is dragged up or down.
    At the default position the diagonal segment is zero (only a vertical tick).

    Label position is tracked explicitly in data coordinates (_data_x, _data_y)
    because pg.TextItem.pos() does not reliably return data coordinates when the
    item is inside a ViewBox — it may return scene/pixel values depending on the
    PyQtGraph version and parent chain.
    """

    _SIDE_LABEL_DIAGONAL_FACTOR = 0.05

    def __init__(
        self,
        peak: Peak,
        peak_x: float,
        peak_y: float,
        label_offset: float,
        label_x: float,
        label_y: float,
        click_callback=None,
        shift_click_callback=None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._peak = peak
        self._peak_x = peak_x
        self._peak_y = peak_y
        self._label_offset = label_offset  # signed: + above apex, - below apex
        self._data_x = label_x  # current label x in data coordinates
        self._data_y = label_y  # current label y in data coordinates
        self._click_callback = click_callback
        self._shift_click_callback = shift_click_callback
        self._leader: pg.PlotCurveItem | None = None

    def set_leader(self, leader: pg.PlotCurveItem) -> None:
        """Attach the leader line item and draw initial position."""
        self._leader = leader
        self._update_leader()

    @classmethod
    def leader_points_for_position(
        cls,
        *,
        peak_x: float,
        peak_y: float,
        label_x: float,
        label_y: float,
    ) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]]:
        """Return the three OMNIC-style leader points for a proposed label position."""
        label_offset = label_y - peak_y

        diagonal_factor = 1.0
        if abs(label_x - peak_x) > 1e-6:
            diagonal_factor = cls._SIDE_LABEL_DIAGONAL_FACTOR

        elbow_y = label_y - (label_offset * diagonal_factor)
        if label_offset > 0:
            elbow_y = max(peak_y, elbow_y)
        else:
            elbow_y = min(peak_y, elbow_y)

        return (
            (float(peak_x), float(peak_y)),
            (float(peak_x), float(elbow_y)),
            (float(label_x), float(label_y)),
        )

    def _update_leader(self) -> None:
        """Recompute leader using explicitly stored data coordinates."""
        if self._leader is None:
            return
        points = self.leader_points_for_position(
            peak_x=self._peak_x,
            peak_y=self._peak_y,
            label_x=self._data_x,
            label_y=self._data_y,
        )
        self._leader.setData(
            x=np.array([point[0] for point in points], dtype=float),
            y=np.array([point[1] for point in points], dtype=float),
        )

    def mouseClickEvent(self, ev) -> None:  # noqa: N802
        """Handle single click: notify parent so peak can be selected/assigned."""
        if ev.button() != Qt.MouseButton.LeftButton:
            ev.ignore()
            return
        ev.accept()
        if ev.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            if self._shift_click_callback is not None:
                self._shift_click_callback(self._peak_x)
            return
        if self._click_callback is not None:
            self._click_callback(self._peak_x)

    def mouseDragEvent(self, ev) -> None:  # noqa: N802
        """Handle PyQtGraph drag events: move label and update leader."""
        if ev.button() != Qt.MouseButton.LeftButton:
            ev.ignore()
            return
        ev.accept()
        # mapToParent() is reliable once the item has a ViewBox parent (set via addItem).
        # The delta in parent (ViewBox data) coordinates gives the correct movement.
        delta = self.mapToParent(ev.pos()) - self.mapToParent(ev.lastPos())
        self._data_x += delta.x()
        self._data_y += delta.y()
        self.setPos(self._data_x, self._data_y)
        self._peak.label_offset_x = self._data_x - self._peak_x
        self._peak.label_offset_y = self._data_y - self._peak_y
        self._peak.manual_placement = True
        self._update_leader()


class SpectrumWidget(QWidget):
    """PyQtGraph-based interactive IR spectrum viewer."""

    peak_clicked = Signal(float, float, float)  # (wavenumber, intensity, click_y)
    cursor_moved = Signal(float, float)  # (wavenumber, intensity_at_cursor)
    peak_selected_in_viewer = Signal(object)  # emits Peak instance
    peak_delete_requested = Signal(object)  # emits Peak instance on Shift+click

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._spectrum: Spectrum | None = None
        self._peaks: list[Peak] = []
        self._peak_items: list = []
        self._add_peak_mode: bool = False
        self._overlay_alpha: int = 60  # 0–100 percent opacity for reference curves
        self._overlay_spectra_cache: list = []  # keep for redraw on slider change
        self._diagnostic_regions_cache: list = []
        self._diagnostic_regions_visible: bool = True
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Initialize PyQtGraph plot widget with OMNIC-like white style."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Overlay controls bar (hidden until an overlay is active) ────────
        self._overlay_bar = QWidget()
        self._overlay_bar.setStyleSheet(
            "QWidget { background: #F0F4F8; border-bottom: 1px solid #CCC; }"
        )
        overlay_row = QHBoxLayout(self._overlay_bar)
        overlay_row.setContentsMargins(8, 4, 8, 4)
        overlay_row.setSpacing(8)

        overlay_row.addWidget(QLabel("Reference overlay:"))

        self._overlay_name_label = QLabel("")
        self._overlay_name_label.setStyleSheet("color: #2980B9; font-weight: bold;")
        overlay_row.addWidget(self._overlay_name_label)

        overlay_row.addWidget(QLabel("Opacity:"))

        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setRange(5, 100)
        self._opacity_slider.setValue(self._overlay_alpha)
        self._opacity_slider.setFixedWidth(120)
        self._opacity_slider.setToolTip("Reference spectrum opacity")
        self._opacity_slider.valueChanged.connect(self._on_opacity_changed)
        overlay_row.addWidget(self._opacity_slider)

        self._opacity_label = QLabel(f"{self._overlay_alpha}%")
        self._opacity_label.setFixedWidth(36)
        overlay_row.addWidget(self._opacity_label)

        clear_overlay_btn = QPushButton("Clear")
        clear_overlay_btn.setFixedWidth(52)
        clear_overlay_btn.clicked.connect(lambda: self.set_overlay_spectra([]))
        overlay_row.addWidget(clear_overlay_btn)

        overlay_row.addStretch()
        self._overlay_bar.setVisible(False)
        layout.addWidget(self._overlay_bar)

        # ── Plot widget ──────────────────────────────────────────────────────
        self._plot_widget = pg.PlotWidget()

        # OMNIC-like style: white background, black axes, no grid
        self._plot_widget.setBackground("w")
        self._plot_widget.showGrid(x=False, y=False)

        # Axis labels with black color
        label_style = {"color": "#000000", "font-size": "10pt"}
        self._plot_widget.setLabel("bottom", "Wavenumber (cm⁻¹)", **label_style)
        self._plot_widget.setLabel("left", "Absorbance", **label_style)

        # IR convention: high to low wavenumber; lock X to standard IR range
        self._plot_widget.invertX(True)
        self._plot_widget.setXRange(_X_DEFAULT_MIN, _X_DEFAULT_MAX, padding=0.0)

        # Style axis ticks/labels black
        for axis in ("bottom", "left"):
            ax = self._plot_widget.getAxis(axis)
            ax.setPen(pg.mkPen(color="k", width=1))
            ax.setTextPen(pg.mkPen(color="k"))

        layout.addWidget(self._plot_widget)

        # Override PyQtGraph "A" button: disconnect default autoBtnClicked, wire to our reset
        _pi = self._plot_widget.getPlotItem()
        _pi.autoBtn.clicked.disconnect()
        _pi.autoBtn.clicked.connect(self.reset_view)

        # Spectrum curve: black, width 1
        self._spectrum_curve = self._plot_widget.plot(pen=pg.mkPen("k", width=1))

        self._overlay_curves: list = []
        self._diagnostic_region_items: list = []

        # Mouse click for peak picking
        self._plot_widget.scene().sigMouseClicked.connect(self._on_mouse_clicked)

        # Mouse move for cursor position tracking
        self._plot_widget.scene().sigMouseMoved.connect(self._on_mouse_moved)

    def set_add_peak_mode(self, enabled: bool) -> None:
        """Enable or disable peak-adding mode.

        Args:
            enabled: True to enter peak-add mode (clicks emit peak_clicked).
        """
        self._add_peak_mode = enabled

    def set_tool_mode(self, mode: str) -> None:
        """Switch interaction mode of the spectrum viewer.

        Args:
            mode: One of "select", "zoom", "pan", "add_peak".
        """
        vb = self._plot_widget.getPlotItem().vb
        if mode == "zoom":
            vb.setMouseMode(pg.ViewBox.RectMode)
            self._add_peak_mode = False
        elif mode == "add_peak":
            vb.setMouseMode(pg.ViewBox.PanMode)
            self._add_peak_mode = True
        else:  # "select" or "pan" — both use PanMode
            vb.setMouseMode(pg.ViewBox.PanMode)
            self._add_peak_mode = False

    def set_spectrum(self, spectrum: Spectrum) -> None:
        """Display a spectrum in the viewer.

        Args:
            spectrum: Spectrum to display.
        """
        self._spectrum = spectrum
        self._spectrum_curve.setData(x=spectrum.wavenumbers, y=spectrum.intensities)

        # Update Y-axis label from spectrum unit
        label_style = {"color": "#000000", "font-size": "10pt"}
        self._plot_widget.setLabel("left", spectrum.display_y_unit.value, **label_style)

        self.reset_view()

    def reset_view(self) -> None:
        """Reset to standard IR view: X=3800–400 cm⁻¹, Y auto-fitted to visible data + labels."""
        self._plot_widget.setXRange(_X_DEFAULT_MIN, _X_DEFAULT_MAX, padding=0.0)

        if self._spectrum is None:
            return

        wn = self._spectrum.wavenumbers
        iy = self._spectrum.intensities

        # Fit Y only to data within the visible x window
        mask = (wn >= _X_DEFAULT_MIN) & (wn <= _X_DEFAULT_MAX)
        visible_y = iy[mask] if mask.any() else iy
        if len(visible_y) == 0:
            return

        y_min = float(np.min(visible_y))
        y_max = float(np.max(visible_y))
        y_span = max(y_max - y_min, 1e-9)

        peaks_are_dips = self._spectrum.is_dip_spectrum
        if self._peaks:
            label_offset = y_span * 0.065
            label_margin = y_span * 0.08
            label_y_values = []
            for peak in self._peaks:
                if peak.manual_placement:
                    label_y_values.append(peak.intensity + peak.label_offset_y)
                else:
                    label_y_values.append(
                        peak.intensity + (-label_offset if peaks_are_dips else label_offset)
                    )
            if label_y_values:
                if peaks_are_dips:
                    y_min = min(y_min, min(label_y_values) - label_margin)
                else:
                    y_max = max(y_max, max(label_y_values) + label_margin)

        if peaks_are_dips:
            # Labels extend below troughs (%T)
            self._plot_widget.setYRange(y_min - y_span * 0.20, y_max + y_span * 0.05, padding=0.0)
        else:
            # Labels extend above peaks (Absorbance)
            self._plot_widget.setYRange(y_min - y_span * 0.05, y_max + y_span * 0.20, padding=0.0)

    def get_x_view_range(self) -> tuple[float, float]:
        """Return the current visible wavenumber range as (x_min, x_max).

        Returns the actual data coordinates of the left and right ViewBox edges,
        regardless of the invert_x setting.  The returned tuple is always ordered
        (lower_value, higher_value) so callers do not need to know the axis direction.
        """
        vb = self._plot_widget.getPlotItem().vb
        x_range = vb.viewRange()[0]  # [[xmin, xmax], [ymin, ymax]]
        return (float(min(x_range)), float(max(x_range)))

    def get_y_view_range(self) -> tuple[float, float]:
        """Return the current visible y-axis range as (y_min, y_max)."""
        vb = self._plot_widget.getPlotItem().vb
        y_range = vb.viewRange()[1]
        return (float(min(y_range)), float(max(y_range)))

    def diagnostic_regions(self) -> tuple[object, ...]:
        """Return the currently cached diagnostic regions."""
        return tuple(self._diagnostic_regions_cache)

    def diagnostic_regions_visible(self) -> bool:
        """Return whether diagnostic-region overlays are currently shown."""
        return self._diagnostic_regions_visible

    def set_peaks(self, peaks: list[Peak]) -> None:
        """Update peak annotations in the viewer.

        Args:
            peaks: List of peaks to annotate.
        """
        self._peaks = peaks

        # Clear previous peak annotations
        for item in self._peak_items:
            self._plot_widget.removeItem(item)
        self._peak_items.clear()

        if not peaks:
            return

        # Determine peak direction: dip-like spectra (%T, reflectance, mislabeled
        # percent-style OMNIC curves) place labels below the curve.
        peaks_are_dips = self._spectrum is not None and self._spectrum.is_dip_spectrum

        # Initial label offset: 6 % of y-range, direction depends on peak orientation
        if self._spectrum is not None:
            y_span = float(np.ptp(self._spectrum.intensities))
        else:
            y_span = 1.0
        if y_span == 0:
            y_span = 1.0

        if peaks_are_dips:
            label_offset = -y_span * 0.065  # labels below dips
            anchor = (1, 0.5)  # text extends downward from anchor
        else:
            label_offset = y_span * 0.065  # labels above maxima
            anchor = (0, 0.5)  # text extends upward from anchor

        leader_pen = pg.mkPen((0, 0, 0), width=0.8)

        for peak in peaks:
            # Diagonal leader line: from peak apex to label, managed by the label
            leader = pg.PlotCurveItem(pen=leader_pen)
            self._plot_widget.addItem(leader)
            self._peak_items.append(leader)

            # Draggable rotated label — owns the leader and updates it on drag
            if peak.manual_placement:
                lx = peak.position + peak.label_offset_x
                ly = peak.intensity + peak.label_offset_y
            else:
                lx = peak.position
                ly = peak.intensity + label_offset

            label = _DraggableLabel(
                peak=peak,
                peak_x=peak.position,
                peak_y=peak.intensity,
                label_offset=ly - peak.intensity,
                label_x=lx,
                label_y=ly,
                click_callback=self._on_label_clicked,
                shift_click_callback=self._on_label_shift_clicked,
                text=str(int(round(peak.position))),
                color=(0, 0, 0),
                angle=90,
                anchor=anchor,
            )
            font = QFont(label.textItem.font())
            font.setPointSizeF(_PEAK_LABEL_FONT_SIZE_PT)
            label.setFont(font)
            # IMPORTANT: addItem BEFORE setPos so ViewBox is the parent when the
            # position is stored.  Without a ViewBox parent, PyQtGraph interprets
            # the coordinates as scene-pixel values; after addItem it re-interprets
            # the stored value as data coordinates — giving the wrong visual position.
            self._plot_widget.addItem(label)
            label.setPos(lx, ly)
            self._peak_items.append(label)
            label.set_leader(leader)

    def compute_auto_label_placements(self) -> list[tuple[Peak, float, float]]:
        """Compute vertical-only label offsets for the current peak set.

        The goal is deliberately conservative: keep the clean default
        `Detect Peaks` look and only stagger labels vertically when a local
        overlap would otherwise happen. Horizontal label movement is
        intentionally forbidden here so leader lines remain mostly vertical
        and do not start criss-crossing the plot.
        """
        if self._spectrum is None or not self._peaks:
            return []

        labels = self._peak_label_items()
        if not labels:
            return []

        vb = self._plot_widget.getPlotItem().vb
        x_range, y_range = vb.viewRange()
        x_min, x_max = float(min(x_range)), float(max(x_range))
        y_min, y_max = float(min(y_range)), float(max(y_range))
        spectrum_y_span = float(np.ptp(self._spectrum.intensities)) or 1.0
        peaks_are_dips = self._spectrum.is_dip_spectrum
        direction = -1.0 if peaks_are_dips else 1.0
        view_y_span = max(y_max - y_min, 1e-6)
        base_gap = spectrum_y_span * 0.065
        x_clearance = max(abs(x_max - x_min) * 0.0015, 4.0)
        y_clearance = max(view_y_span * 0.008, spectrum_y_span * 0.01)
        original_positions = [(label, label._data_x, label._data_y) for label in labels]
        placed_rects: list[tuple[float, float, float, float]] = []
        placements: list[tuple[Peak, float, float]] = []

        sorted_labels = sorted(
            labels,
            key=lambda label: (
                -label._peak_x,
                label._peak_y if peaks_are_dips else -label._peak_y,
            ),
        )

        try:
            for label in sorted_labels:
                candidate_x = label._peak_x
                natural_y = label._peak_y + (direction * base_gap)
                natural_rect = self._data_rect_for_label_position(label, candidate_x, natural_y)
                rect_height = max(natural_rect[3] - natural_rect[2], view_y_span * 0.04)
                vertical_step = rect_height + y_clearance

                best_candidate: tuple[
                    float,
                    float,
                    tuple[float, float, float, float],
                    tuple[tuple[float, float], tuple[float, float], tuple[float, float]],
                    float,
                ] | None = None

                for level in range(18):
                    candidate_y = label._peak_y + (
                        direction * (base_gap + (level * vertical_step))
                    )
                    rect = self._data_rect_for_label_position(label, candidate_x, candidate_y)
                    leader = self._leader_polyline_for_label_position(
                        label,
                        candidate_x,
                        candidate_y,
                    )

                    rect_overlap = self._label_rect_overlaps_any(
                        rect,
                        placed_rects,
                        x_padding=x_clearance,
                        y_padding=y_clearance * 0.3,
                    )
                    curve_overlap = self._label_rect_hits_curve(
                        rect,
                        peaks_are_dips=peaks_are_dips,
                        clearance=y_clearance,
                    )
                    conflict_count = sum(
                        (
                            rect_overlap,
                            curve_overlap,
                        )
                    )
                    penalty = float((curve_overlap * 4000) + (rect_overlap * 350) + (level * 45))
                    candidate = (candidate_y, candidate_x, rect, leader, penalty)

                    if best_candidate is None or penalty < best_candidate[4]:
                        best_candidate = candidate

                    if conflict_count == 0 and level == 0:
                        best_candidate = candidate
                        break

                if best_candidate is None:
                    continue

                best_y, best_x, best_rect, best_leader, _ = best_candidate
                fine_step = max(y_clearance * 0.75, view_y_span * 0.0035)
                for _ in range(24):
                    if not self._label_rect_overlaps_any(
                        best_rect,
                        placed_rects,
                        x_padding=0.0,
                        y_padding=0.0,
                    ):
                        break
                    best_y += direction * fine_step
                    best_rect = self._data_rect_for_label_position(label, best_x, best_y)

                placed_rects.append(best_rect)
                placements.append((label._peak, best_x - label._peak_x, best_y - label._peak_y))
        finally:
            for label, original_x, original_y in original_positions:
                label._data_x = original_x
                label._data_y = original_y
                label.setPos(original_x, original_y)
                label._update_leader()

        return placements

    def _cluster_labels_for_auto_layout(
        self,
        labels: list[_DraggableLabel],
        *,
        gap_threshold: float,
        max_cluster_size: int,
    ) -> list[list[_DraggableLabel]]:
        """Split labels into local x-clusters so distant regions arrange independently."""
        if not labels:
            return []

        clusters: list[list[_DraggableLabel]] = [[labels[0]]]
        for label in labels[1:]:
            current_cluster = clusters[-1]
            previous = current_cluster[-1]
            gap = abs(previous._peak_x - label._peak_x)
            if gap > gap_threshold or len(current_cluster) >= max_cluster_size:
                clusters.append([label])
                continue
            current_cluster.append(label)

        return clusters

    def set_overlay_spectra(self, spectra: list) -> None:
        """Overlay additional spectra (e.g. reference candidates) with colored lines.

        Args:
            spectra: List of Spectrum objects to overlay. Pass empty list to clear.
        """
        self._overlay_spectra_cache = list(spectra)
        self._redraw_overlays()

        # Show/hide overlay bar and update name label
        has_overlays = bool(spectra)
        self._overlay_bar.setVisible(has_overlays)
        if has_overlays:
            names = [getattr(s, "title", "") or "" for s in spectra]
            self._overlay_name_label.setText(", ".join(n for n in names if n) or "—")

    def set_diagnostic_regions(self, regions: list) -> None:
        """Highlight diagnostic wavenumber ranges for a selected functional group."""
        self._diagnostic_regions_cache = list(regions)
        self._redraw_diagnostic_regions()

    def set_diagnostic_regions_visible(self, visible: bool) -> None:
        """Show or hide the currently selected functional-group region overlays."""
        self._diagnostic_regions_visible = bool(visible)
        self._redraw_diagnostic_regions()

    def _redraw_overlays(self) -> None:
        """Remove and redraw all overlay curves using current alpha and color settings."""
        for curve in self._overlay_curves:
            self._plot_widget.removeItem(curve)
        self._overlay_curves.clear()

        alpha = int(self._overlay_alpha / 100 * 255)
        for i, spectrum in enumerate(self._overlay_spectra_cache):
            hex_color = _OVERLAY_COLORS[i % len(_OVERLAY_COLORS)]
            r = int(hex_color[1:3], 16)
            g = int(hex_color[3:5], 16)
            b = int(hex_color[5:7], 16)
            curve = self._plot_widget.plot(
                x=spectrum.wavenumbers,
                y=spectrum.intensities,
                pen=pg.mkPen((r, g, b, alpha), width=1.5),
            )
            self._overlay_curves.append(curve)

    def _redraw_diagnostic_regions(self) -> None:
        for item in self._diagnostic_region_items:
            self._plot_widget.removeItem(item)
        self._diagnostic_region_items.clear()

        if not self._diagnostic_regions_visible:
            return

        for region in self._diagnostic_regions_cache:
            brush, pen = self._diagnostic_region_style(region)

            item = pg.LinearRegionItem(
                values=(float(region.range_min), float(region.range_max)),
                brush=brush,
                pen=pen,
                movable=False,
                swapMode="sort",
            )
            item.setZValue(-50)
            self._plot_widget.addItem(item)
            self._diagnostic_region_items.append(item)

    def _diagnostic_region_style(self, region) -> tuple[QColor, object]:
        if getattr(region, "is_missing_required", False):
            brush = QColor("#FDEDEC")
            brush.setAlpha(28)
            pen = pg.mkPen(color=QColor("#C0392B"), width=1.4, style=Qt.PenStyle.DashLine)
            return brush, pen

        if getattr(region, "is_confirmed", False):
            color = QColor(region.color)
            brush = QColor(color)
            brush.setAlpha(56)
            pen = pg.mkPen(color=color, width=1.2)
            return brush, pen

        brush = QColor("#FCF3CF")
        brush.setAlpha(36)
        pen = pg.mkPen(color=QColor("#AF6E00"), width=1.0, style=Qt.PenStyle.DashLine)
        return brush, pen

    def _on_opacity_changed(self, value: int) -> None:
        """Update overlay opacity when slider changes."""
        self._overlay_alpha = value
        self._opacity_label.setText(f"{value}%")
        self._redraw_overlays()

    def _on_label_clicked(self, peak_x: float) -> None:
        """Called when a peak label is directly clicked; find and select the peak."""
        if not self._peaks:
            return
        closest = min(self._peaks, key=lambda p: abs(p.position - peak_x))
        if abs(closest.position - peak_x) <= 1.0:  # exact match (label stores peak_x)
            self.peak_selected_in_viewer.emit(closest)

    def _peak_label_items(self) -> list[_DraggableLabel]:
        return [item for item in self._peak_items if isinstance(item, _DraggableLabel)]

    @staticmethod
    def _leader_polyline_for_label_position(
        label: _DraggableLabel,
        x_pos: float,
        y_pos: float,
    ) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]]:
        return _DraggableLabel.leader_points_for_position(
            peak_x=label._peak_x,
            peak_y=label._peak_y,
            label_x=x_pos,
            label_y=y_pos,
        )

    def _data_rect_for_label_position(
        self,
        label: _DraggableLabel,
        x_pos: float,
        y_pos: float,
    ) -> tuple[float, float, float, float]:
        old_x, old_y = label._data_x, label._data_y
        label._data_x = x_pos
        label._data_y = y_pos
        label.setPos(x_pos, y_pos)
        rect = label.mapRectToParent(label.boundingRect())
        x0, x1 = sorted((float(rect.left()), float(rect.right())))
        y0, y1 = sorted((float(rect.top()), float(rect.bottom())))
        label._data_x = old_x
        label._data_y = old_y
        label.setPos(old_x, old_y)
        return x0, x1, y0, y1

    def _clamp_label_position_to_view(
        self,
        label: _DraggableLabel,
        x_pos: float,
        y_pos: float,
        *,
        x_min: float,
        x_max: float,
        y_min: float,
        y_max: float,
    ) -> tuple[float, float]:
        rect = self._data_rect_for_label_position(label, x_pos, y_pos)
        if rect[0] < x_min:
            x_pos += x_min - rect[0]
        elif rect[1] > x_max:
            x_pos -= rect[1] - x_max

        rect = self._data_rect_for_label_position(label, x_pos, y_pos)
        if rect[2] < y_min:
            y_pos += y_min - rect[2]
        elif rect[3] > y_max:
            y_pos -= rect[3] - y_max
        return x_pos, y_pos

    @staticmethod
    def _label_rect_overlaps_any(
        rect: tuple[float, float, float, float],
        placed_rects: list[tuple[float, float, float, float]],
        *,
        x_padding: float,
        y_padding: float,
    ) -> bool:
        x0, x1, y0, y1 = rect
        for other_x0, other_x1, other_y0, other_y1 in placed_rects:
            if x1 + x_padding <= other_x0 or other_x1 + x_padding <= x0:
                continue
            if y1 + y_padding <= other_y0 or other_y1 + y_padding <= y0:
                continue
            return True
        return False

    def _label_rect_hits_curve(
        self,
        rect: tuple[float, float, float, float],
        *,
        peaks_are_dips: bool,
        clearance: float,
    ) -> bool:
        if self._spectrum is None:
            return False

        x0, x1, y0, y1 = rect
        sample_x = np.linspace(x0, x1, 12)
        curve_y = np.array([self._intensity_at(x) for x in sample_x], dtype=float)
        if peaks_are_dips:
            return y1 >= float(np.min(curve_y)) - clearance
        return y0 <= float(np.max(curve_y)) + clearance

    def _find_best_label_candidate(
        self,
        *,
        label: _DraggableLabel,
        lane_origin_y: float,
        direction: float,
        x_min: float,
        x_max: float,
        y_min: float,
        y_max: float,
        x_span: float,
        view_y_span: float,
        peaks_are_dips: bool,
        x_clearance: float,
        y_clearance: float,
        view_padding_x: float,
        view_padding_y: float,
        placed_rects: list[tuple[float, float, float, float]],
        placed_leaders: list[tuple[tuple[float, float], tuple[float, float], tuple[float, float]]],
        row_last_rects: dict[int, tuple[float, float, float, float]],
        last_anchor_x: float | None,
        allow_left_shifts: bool,
        min_candidate_x: float | None = None,
    ) -> tuple[
        float,
        float,
        float,
        float,
        float,
        float,
        float,
        int,
        tuple[tuple[float, float], tuple[float, float], tuple[float, float]],
    ] | None:
        natural_rect = self._data_rect_for_label_position(
            label,
            label._peak_x,
            label._peak_y + (direction * (float(np.ptp(self._spectrum.intensities)) or 1.0) * 0.065),
        )
        rect_width = max(natural_rect[1] - natural_rect[0], x_span * 0.01)
        rect_height = max(natural_rect[3] - natural_rect[2], view_y_span * 0.04)
        horizontal_step = rect_width + x_clearance
        vertical_step = rect_height + y_clearance
        best_candidate: tuple[
            float,
            float,
            float,
            float,
            float,
            float,
            float,
            int,
            tuple[tuple[float, float], tuple[float, float], tuple[float, float]],
        ] | None = None

        if allow_left_shifts:
            shift_multipliers = (
                [-1, 0, 1, -2, 2, -3, 3, -4, 4]
                if last_anchor_x is None
                else [0, -1, 1, -2, 2, -3, 3, -4, 4]
            )
        else:
            shift_multipliers = [0, 1, 2, 3, 4, 5]

        for level in range(12):
            candidate_y = lane_origin_y + (direction * (level * vertical_step))
            for shift_multiplier in shift_multipliers:
                candidate_x = label._peak_x - (shift_multiplier * horizontal_step)
                candidate_x, candidate_y = self._clamp_label_position_to_view(
                    label,
                    candidate_x,
                    candidate_y,
                    x_min=x_min + view_padding_x,
                    x_max=x_max - view_padding_x,
                    y_min=y_min + view_padding_y,
                    y_max=y_max - view_padding_y,
                )
                rect = self._data_rect_for_label_position(label, candidate_x, candidate_y)

                last_rect_in_row = row_last_rects.get(level)
                if last_rect_in_row is not None:
                    max_right_edge = last_rect_in_row[0] - x_clearance
                    if rect[1] > max_right_edge:
                        candidate_x += max_right_edge - rect[1]
                        rect = self._data_rect_for_label_position(label, candidate_x, candidate_y)

                if last_anchor_x is not None:
                    max_anchor_x = last_anchor_x - max(x_clearance, rect_width * 0.15)
                    if candidate_x > max_anchor_x:
                        candidate_x = max_anchor_x
                        rect = self._data_rect_for_label_position(label, candidate_x, candidate_y)

                if min_candidate_x is not None and candidate_x < min_candidate_x:
                    candidate_x = min_candidate_x
                    rect = self._data_rect_for_label_position(label, candidate_x, candidate_y)

                actual_shift_steps = int(
                    np.ceil(
                        max(0.0, label._peak_x - candidate_x) / max(horizontal_step, 1e-6) - 1e-9
                    )
                )
                if level < actual_shift_steps:
                    continue

                if rect[0] < x_min + view_padding_x or rect[1] > x_max - view_padding_x:
                    continue

                leader = self._leader_polyline_for_label_position(label, candidate_x, candidate_y)
                has_conflict = self._label_candidate_has_conflict(
                    label,
                    candidate_x,
                    candidate_y,
                    peaks_are_dips=peaks_are_dips,
                    x_clearance=x_clearance,
                    y_clearance=y_clearance,
                    placed_rects=placed_rects,
                    placed_leaders=placed_leaders,
                    rect=rect,
                    leader=leader,
                )
                cost = (
                    (1000.0 if has_conflict else 0.0)
                    + (abs(shift_multiplier) * 2.5)
                    + (level * 0.4)
                    + (abs(candidate_x - label._peak_x) / max(rect_width, 1e-6))
                    + (abs(candidate_y - label._peak_y) / max(rect_height, 1e-6))
                )
                if best_candidate is None or cost < best_candidate[0]:
                    best_candidate = (
                        cost,
                        candidate_x,
                        candidate_y,
                        rect[0],
                        rect[1],
                        rect[2],
                        rect[3],
                        level,
                        leader,
                    )
                if not has_conflict:
                    return best_candidate

        return best_candidate

    def _label_candidate_has_conflict(
        self,
        label: _DraggableLabel,
        candidate_x: float,
        candidate_y: float,
        *,
        peaks_are_dips: bool,
        x_clearance: float,
        y_clearance: float,
        placed_rects: list[tuple[float, float, float, float]],
        placed_leaders: list[tuple[tuple[float, float], tuple[float, float], tuple[float, float]]],
        rect: tuple[float, float, float, float] | None = None,
        leader: tuple[tuple[float, float], tuple[float, float], tuple[float, float]] | None = None,
    ) -> bool:
        rect = rect or self._data_rect_for_label_position(label, candidate_x, candidate_y)
        leader = leader or self._leader_polyline_for_label_position(label, candidate_x, candidate_y)
        rect_overlap = self._label_rect_overlaps_any(
            rect,
            placed_rects,
            x_padding=x_clearance * 0.5,
            y_padding=y_clearance * 0.4,
        )
        curve_overlap = self._label_rect_hits_curve(
            rect,
            peaks_are_dips=peaks_are_dips,
            clearance=y_clearance,
        )
        wrong_side = (
            candidate_y <= label._peak_y + (y_clearance * 0.25)
            if not peaks_are_dips
            else candidate_y >= label._peak_y - (y_clearance * 0.25)
        )
        leader_overlap = self._leader_polyline_overlaps_any(
            leader,
            placed_leaders,
        )
        leader_hits_rect = self._leader_polyline_hits_rects(
            leader,
            placed_rects,
            x_padding=x_clearance * 0.2,
            y_padding=y_clearance * 0.15,
        )
        incoming_leader_hits = any(
            self._leader_polyline_hits_rects(
                other_leader,
                [rect],
                x_padding=x_clearance * 0.2,
                y_padding=y_clearance * 0.15,
            )
            for other_leader in placed_leaders
        )
        return (
            rect_overlap
            or curve_overlap
            or wrong_side
            or leader_overlap
            or leader_hits_rect
            or incoming_leader_hits
        )

    @classmethod
    def _leader_polyline_overlaps_any(
        cls,
        leader: tuple[tuple[float, float], tuple[float, float], tuple[float, float]],
        placed_leaders: list[
            tuple[tuple[float, float], tuple[float, float], tuple[float, float]]
        ],
    ) -> bool:
        leader_segments = cls._polyline_segments(leader)
        for other in placed_leaders:
            other_segments = cls._polyline_segments(other)
            for segment in leader_segments:
                for other_segment in other_segments:
                    if cls._segments_intersect(segment, other_segment):
                        return True
        return False

    @classmethod
    def _leader_polyline_hits_rects(
        cls,
        leader: tuple[tuple[float, float], tuple[float, float], tuple[float, float]],
        rects: list[tuple[float, float, float, float]],
        *,
        x_padding: float,
        y_padding: float,
    ) -> bool:
        for segment in cls._polyline_segments(leader):
            for rect in rects:
                if cls._segment_hits_rect(
                    segment,
                    rect,
                    x_padding=x_padding,
                    y_padding=y_padding,
                ):
                    return True
        return False

    @staticmethod
    def _polyline_segments(
        polyline: tuple[tuple[float, float], tuple[float, float], tuple[float, float]],
    ) -> tuple[tuple[tuple[float, float], tuple[float, float]], ...]:
        return ((polyline[0], polyline[1]), (polyline[1], polyline[2]))

    @classmethod
    def _segment_hits_rect(
        cls,
        segment: tuple[tuple[float, float], tuple[float, float]],
        rect: tuple[float, float, float, float],
        *,
        x_padding: float,
        y_padding: float,
    ) -> bool:
        x0, x1, y0, y1 = rect
        expanded_rect = (x0 - x_padding, x1 + x_padding, y0 - y_padding, y1 + y_padding)
        p0, p1 = segment
        if cls._point_in_rect(p0, expanded_rect) or cls._point_in_rect(p1, expanded_rect):
            return True

        rx0, rx1, ry0, ry1 = expanded_rect
        rect_edges = (
            ((rx0, ry0), (rx1, ry0)),
            ((rx1, ry0), (rx1, ry1)),
            ((rx1, ry1), (rx0, ry1)),
            ((rx0, ry1), (rx0, ry0)),
        )
        return any(cls._segments_intersect(segment, edge) for edge in rect_edges)

    @staticmethod
    def _point_in_rect(
        point: tuple[float, float],
        rect: tuple[float, float, float, float],
    ) -> bool:
        x, y = point
        x0, x1, y0, y1 = rect
        return x0 <= x <= x1 and y0 <= y <= y1

    @classmethod
    def _segments_intersect(
        cls,
        first: tuple[tuple[float, float], tuple[float, float]],
        second: tuple[tuple[float, float], tuple[float, float]],
    ) -> bool:
        p1, q1 = first
        p2, q2 = second
        o1 = cls._orientation(p1, q1, p2)
        o2 = cls._orientation(p1, q1, q2)
        o3 = cls._orientation(p2, q2, p1)
        o4 = cls._orientation(p2, q2, q1)

        if o1 != o2 and o3 != o4:
            return True

        return (
            (o1 == 0 and cls._point_on_segment(p2, p1, q1))
            or (o2 == 0 and cls._point_on_segment(q2, p1, q1))
            or (o3 == 0 and cls._point_on_segment(p1, p2, q2))
            or (o4 == 0 and cls._point_on_segment(q1, p2, q2))
        )

    @staticmethod
    def _orientation(
        first: tuple[float, float],
        second: tuple[float, float],
        third: tuple[float, float],
    ) -> int:
        determinant = (
            (second[1] - first[1]) * (third[0] - second[0])
            - (second[0] - first[0]) * (third[1] - second[1])
        )
        if abs(determinant) <= 1e-9:
            return 0
        return 1 if determinant > 0 else 2

    @staticmethod
    def _point_on_segment(
        point: tuple[float, float],
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> bool:
        return (
            min(start[0], end[0]) - 1e-9 <= point[0] <= max(start[0], end[0]) + 1e-9
            and min(start[1], end[1]) - 1e-9 <= point[1] <= max(start[1], end[1]) + 1e-9
        )

    def _on_label_shift_clicked(self, peak_x: float) -> None:
        """Called on Shift+click of a label; delete peak in any tool mode."""
        if not self._peaks:
            return
        closest = min(self._peaks, key=lambda p: abs(p.position - peak_x))
        if abs(closest.position - peak_x) <= 1.0:
            self.peak_delete_requested.emit(closest)

    def _on_mouse_clicked(self, event) -> None:
        """Handle mouse click on the plot scene for peak picking or selection."""
        pos = event.scenePos()
        plot_item = self._plot_widget.getPlotItem()
        vb = plot_item.vb

        if not vb.sceneBoundingRect().contains(pos):
            return

        mouse_point = vb.mapSceneToView(pos)
        wavenumber = mouse_point.x()
        click_y = mouse_point.y()

        if self._add_peak_mode:
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                return  # let label's shift_click_callback handle deletion
            # Don't add a new peak if the click landed on an existing label
            if self._peaks:
                closest = min(self._peaks, key=lambda p: abs(p.position - wavenumber))
                if abs(closest.position - wavenumber) <= 5.0:
                    return  # user clicked on/near an existing label — label handles it
            intensity = self._intensity_at(wavenumber)
            self.peak_clicked.emit(wavenumber, intensity, click_y)
        elif self._peaks:
            # Select nearest peak within 30 cm⁻¹
            closest = min(self._peaks, key=lambda p: abs(p.position - wavenumber))
            if abs(closest.position - wavenumber) <= 30.0:
                self.peak_selected_in_viewer.emit(closest)

    def _on_mouse_moved(self, pos) -> None:
        """Handle mouse move on the plot scene for cursor position."""
        plot_item = self._plot_widget.getPlotItem()
        vb = plot_item.vb

        if not vb.sceneBoundingRect().contains(pos):
            return

        mouse_point = vb.mapSceneToView(pos)
        wavenumber = mouse_point.x()
        intensity = self._intensity_at(wavenumber)
        self.cursor_moved.emit(wavenumber, intensity)

    def _intensity_at(self, wavenumber: float) -> float:
        """Return interpolated intensity at the given wavenumber."""
        if self._spectrum is None:
            return 0.0
        x = self._spectrum.wavenumbers
        y = self._spectrum.intensities
        if x.size >= 2 and x[0] > x[-1]:
            x = x[::-1]
            y = y[::-1]
        return float(np.interp(wavenumber, x, y))
