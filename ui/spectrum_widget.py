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

# Control bars above the plot. Every rule is scoped to the bar's object name or
# to a concrete control class, so the bar background never bleeds into the
# buttons and slider sitting on it (which is what made them unreadable).
_OVERLAY_BAR_STYLE = """
QWidget#overlayBar {
    background: #D6E4F0;
    border-bottom: 1px solid #7F9DB9;
}
QWidget#overlayBar QLabel {
    color: #1B2B38;
    background: transparent;
}
QWidget#overlayBar QLabel#overlayName {
    color: #14507A;
    font-weight: bold;
}
QWidget#overlayBar QPushButton {
    background: #FFFFFF;
    color: #1B2B38;
    border: 1px solid #7F9DB9;
    border-radius: 3px;
    padding: 2px 8px;
}
QWidget#overlayBar QPushButton:hover {
    background: #F0F7FF;
    border-color: #14507A;
}
QWidget#overlayBar QPushButton:pressed {
    background: #C9DCEF;
}
QWidget#overlayBar QSlider::groove:horizontal {
    height: 4px;
    background: #FFFFFF;
    border: 1px solid #7F9DB9;
    border-radius: 2px;
}
QWidget#overlayBar QSlider::sub-page:horizontal {
    background: #2980B9;
    border: 1px solid #14507A;
    border-radius: 2px;
}
QWidget#overlayBar QSlider::handle:horizontal {
    width: 10px;
    margin: -5px 0;
    background: #14507A;
    border: 1px solid #0D3A57;
    border-radius: 5px;
}
"""

_PLOT_TOOLBAR_STYLE = """
QWidget#plotToolbarBar {
    background: #ECECEC;
    border-bottom: 1px solid #B8B8B8;
}
QWidget#plotToolbarBar QPushButton {
    background: #FFFFFF;
    color: #1B1B1B;
    border: 1px solid #A0A0A0;
    border-radius: 3px;
    padding: 1px 10px;
}
QWidget#plotToolbarBar QPushButton:hover {
    background: #F4F8FC;
    border-color: #14507A;
}
QWidget#plotToolbarBar QPushButton:checked {
    background: #2980B9;
    color: #FFFFFF;
    border-color: #14507A;
}
"""

# Split-view constants
_SPLIT_WN = 2000.0  # cm⁻¹ split boundary
_SPLIT_HI_FRAC = 35  # width fraction for hi-wavenumber panel (2000–3800)
_SPLIT_LO_FRAC = 65  # width fraction for fingerprint panel (400–2000)


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
        drag_finished_callback=None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._peak = peak
        self._peak_x = peak_x
        self._peak_y = peak_y
        self._data_x = label_x  # current label x in data coordinates
        self._data_y = label_y  # current label y in data coordinates
        self._click_callback = click_callback
        self._shift_click_callback = shift_click_callback
        self._drag_finished_callback = drag_finished_callback
        self._drag_changed = False
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
        if delta.x() != 0.0 or delta.y() != 0.0:
            self._drag_changed = True
        self._data_x += delta.x()
        self._data_y += delta.y()
        self.setPos(self._data_x, self._data_y)
        self._peak.label_offset_x = self._data_x - self._peak_x
        self._peak.label_offset_y = self._data_y - self._peak_y
        self._peak.manual_placement = True
        self._update_leader()
        if ev.isFinish() and self._drag_changed:
            self._drag_changed = False
            if self._drag_finished_callback is not None:
                self._drag_finished_callback(self._peak)


class SpectrumWidget(QWidget):
    """PyQtGraph-based interactive IR spectrum viewer."""

    peak_clicked = Signal(float, float, float)  # (wavenumber, intensity, click_y)
    cursor_moved = Signal(float, float)  # (wavenumber, intensity_at_cursor)
    peak_selected_in_viewer = Signal(object)  # emits Peak instance
    peak_delete_requested = Signal(object)  # emits Peak instance on Shift+click
    peak_label_moved = Signal(object)  # emits Peak after a completed label drag

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._spectrum: Spectrum | None = None
        self._peaks: list[Peak] = []
        self._peak_items: list = []
        self._selected_peak: Peak | None = None  # viewer-only: marks the active peak
        self._add_peak_mode: bool = False
        self._tool_mode: str = "select"
        self._overlay_alpha: int = 60  # 0–100 percent opacity for reference curves
        self._overlay_spectra_cache: list = []  # keep for redraw on slider change
        self._diagnostic_regions_cache: list = []
        self._diagnostic_regions_visible: bool = True
        # Split-view state
        self._split_mode: bool = False
        self._fp_plot_widget: pg.PlotWidget | None = None
        self._spectrum_curve_fp: pg.PlotDataItem | None = None
        self._peak_items_fp: list = []
        self._overlay_curves_fp: list = []
        self._diagnostic_region_items_fp: list = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Initialize PyQtGraph plot widget with OMNIC-like white style."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Overlay controls bar (hidden until an overlay is active) ────────
        # The stylesheet is scoped by object name: an unscoped `QWidget` rule
        # also repaints every child, which flattens the button and slider into
        # the bar background and makes them nearly invisible.
        self._overlay_bar = QWidget()
        self._overlay_bar.setObjectName("overlayBar")
        self._overlay_bar.setStyleSheet(_OVERLAY_BAR_STYLE)
        overlay_row = QHBoxLayout(self._overlay_bar)
        overlay_row.setContentsMargins(8, 4, 8, 4)
        overlay_row.setSpacing(8)

        overlay_row.addWidget(QLabel("Reference overlay:"))

        self._overlay_name_label = QLabel("")
        self._overlay_name_label.setObjectName("overlayName")
        self._overlay_name_label.setTextFormat(Qt.TextFormat.PlainText)
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
        clear_overlay_btn.setFixedWidth(56)
        clear_overlay_btn.setToolTip("Remove the reference overlay from the plot")
        clear_overlay_btn.clicked.connect(lambda: self.set_overlay_spectra([]))
        overlay_row.addWidget(clear_overlay_btn)

        overlay_row.addStretch()
        self._overlay_bar.setVisible(False)
        layout.addWidget(self._overlay_bar)

        # ── Toolbar bar (always visible) — split-view toggle ─────────────────
        self._toolbar_bar = QWidget()
        self._toolbar_bar.setObjectName("plotToolbarBar")
        self._toolbar_bar.setStyleSheet(_PLOT_TOOLBAR_STYLE)
        toolbar_row = QHBoxLayout(self._toolbar_bar)
        toolbar_row.setContentsMargins(8, 2, 8, 2)
        toolbar_row.setSpacing(8)
        self._split_btn = QPushButton("Split view")
        self._split_btn.setCheckable(True)
        self._split_btn.setFixedHeight(22)
        self._split_btn.setToolTip("Show fingerprint region (400–2000 cm⁻¹) expanded")
        self._split_btn.toggled.connect(self._on_split_toggled)
        toolbar_row.addWidget(self._split_btn)
        toolbar_row.addStretch()
        layout.addWidget(self._toolbar_bar)

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

        # ── Plots container (holds main + optional fingerprint panel) ─────────
        self._plots_container = QWidget()
        self._plots_layout = QHBoxLayout(self._plots_container)
        self._plots_layout.setContentsMargins(0, 0, 0, 0)
        self._plots_layout.setSpacing(0)
        self._plots_layout.addWidget(self._plot_widget, _SPLIT_HI_FRAC)
        layout.addWidget(self._plots_container)

    # ── Split-view helpers ────────────────────────────────────────────────────

    def _create_fp_plot_widget(self) -> pg.PlotWidget:
        """Create and configure the fingerprint-region PlotWidget."""
        fp = pg.PlotWidget()
        fp.setBackground("w")
        fp.showGrid(x=False, y=False)
        fp.invertX(True)
        fp.setXRange(_X_DEFAULT_MIN, _SPLIT_WN, padding=0.0)
        fp.hideAxis("left")
        for axis_name in ("bottom",):
            ax = fp.getAxis(axis_name)
            ax.setPen(pg.mkPen(color="k", width=1))
            ax.setTextPen(pg.mkPen(color="k"))
        label_style = {"color": "#000000", "font-size": "10pt"}
        fp.setLabel("bottom", "Wavenumber (cm⁻¹)", **label_style)
        self._spectrum_curve_fp = fp.plot(pen=pg.mkPen("k", width=1))
        fp.scene().sigMouseClicked.connect(self._on_fp_mouse_clicked)
        fp.scene().sigMouseMoved.connect(self._on_fp_mouse_moved)
        self._apply_tool_mode_to(fp)
        return fp

    def _on_split_toggled(self, checked: bool) -> None:
        """Enable or disable the split-view mode."""
        self._split_mode = checked
        if checked:
            if self._fp_plot_widget is None:
                self._fp_plot_widget = self._create_fp_plot_widget()
                self._plots_layout.addWidget(self._fp_plot_widget, _SPLIT_LO_FRAC)
                self._fp_plot_widget.getPlotItem().vb.setYLink(self._plot_widget.getPlotItem().vb)
            self._fp_plot_widget.setVisible(True)
            self._plot_widget.setXRange(_SPLIT_WN, self._default_x_range()[1], padding=0.0)
            if self._spectrum is not None and self._spectrum_curve_fp is not None:
                self._spectrum_curve_fp.setData(
                    x=self._spectrum.wavenumbers,
                    y=self._spectrum.intensities,
                )
            self.set_peaks(self._peaks)
            self._redraw_overlays()
            self._redraw_diagnostic_regions()
        else:
            if self._fp_plot_widget is not None:
                self._fp_plot_widget.setVisible(False)
            # Re-render all peaks back into the main plot (set_peaks clears the
            # fingerprint panel first), then restore the full-range view.
            self.set_peaks(self._peaks)
            self.reset_view()
            self._redraw_overlays()
            self._redraw_diagnostic_regions()

    def _clear_fp_items(self) -> None:
        """Remove peak annotations added to the fingerprint panel.

        Overlay curves and diagnostic regions are owned by _redraw_overlays /
        _redraw_diagnostic_regions, which clear their own fingerprint items.
        """
        if self._fp_plot_widget is None:
            return
        for item in self._peak_items_fp:
            self._fp_plot_widget.removeItem(item)
        self._peak_items_fp.clear()

    def _render_peaks_to(
        self,
        peaks: list[Peak],
        plot_widget: pg.PlotWidget,
        items_list: list,
        peaks_are_dips: bool,
        y_span: float,
    ) -> None:
        """Render peak leaders and labels into the given plot widget."""
        if peaks_are_dips:
            label_offset = -y_span * 0.065
            anchor = (1, 0.5)
        else:
            label_offset = y_span * 0.065
            anchor = (0, 0.5)

        leader_pen = pg.mkPen((0, 0, 0), width=0.8)

        for peak in peaks:
            leader = pg.PlotCurveItem(pen=leader_pen)
            plot_widget.addItem(leader)
            items_list.append(leader)

            if peak.manual_placement:
                lx = peak.position + peak.label_offset_x
                ly = peak.intensity + peak.label_offset_y
            else:
                lx = peak.position
                ly = peak.intensity + label_offset

            label_text, label_color = self._label_text_and_color(peak)
            label = _DraggableLabel(
                peak=peak,
                peak_x=peak.position,
                peak_y=peak.intensity,
                label_offset=ly - peak.intensity,
                label_x=lx,
                label_y=ly,
                click_callback=self._on_label_clicked,
                shift_click_callback=self._on_label_shift_clicked,
                drag_finished_callback=self.peak_label_moved.emit,
                text=label_text,
                color=label_color,
                angle=90,
                anchor=anchor,
            )
            font = QFont(label.textItem.font())
            font.setPointSizeF(_PEAK_LABEL_FONT_SIZE_PT)
            label.setFont(font)
            plot_widget.addItem(label)
            label.setPos(lx, ly)
            items_list.append(label)
            label.set_leader(leader)

    # ── End split-view helpers ────────────────────────────────────────────────

    # Viewer-only peak-label markers. These decorate the live labels and are
    # NOT used by the PDF/PNG export (the renderer builds its own labels from
    # peak.position), so exported spectra stay clean.
    _MARK_SELECTED = "▶"  # currently selected peak
    _MARK_ASSIGNED = "•"  # peak that already has a vibration assignment
    _COLOR_SELECTED = (21, 101, 192)  # blue
    _COLOR_DEFAULT = (0, 0, 0)

    def _label_text_and_color(self, peak: Peak) -> tuple[str, tuple[int, int, int]]:
        """Return the on-screen label text (with markers) and color for a peak."""
        from core.peak_assignments import peak_has_assignment  # noqa: PLC0415

        number = str(int(round(peak.position)))
        is_selected = self._selected_peak is not None and peak is self._selected_peak
        prefix = ""
        if is_selected:
            prefix += self._MARK_SELECTED
        if peak_has_assignment(peak):
            prefix += self._MARK_ASSIGNED
        color = self._COLOR_SELECTED if is_selected else self._COLOR_DEFAULT
        return (f"{prefix}{number}" if prefix else number), color

    def set_selected_peak(self, peak: Peak | None, *, refresh: bool = True) -> None:
        """Mark one peak as selected in the viewer and refresh label markers.

        Only re-renders when the selection actually changes. Pass
        ``refresh=False`` when a ``set_peaks`` call will follow anyway, to avoid
        rendering the labels twice.
        """
        if peak is self._selected_peak:
            return
        self._selected_peak = peak
        if refresh and self._peaks:
            self.set_peaks(self._peaks)

    def set_add_peak_mode(self, enabled: bool) -> None:
        """Enable or disable peak-adding mode.

        Args:
            enabled: True to enter peak-add mode (clicks emit peak_clicked).
        """
        self._add_peak_mode = enabled

    def set_tool_mode(self, mode: str) -> None:
        """Switch interaction mode of the spectrum viewer.

        Applies to both panels so zoom/pan keep working in split view.

        Args:
            mode: One of "select", "zoom", "pan", "add_peak".
        """
        self._tool_mode = mode
        self._add_peak_mode = mode == "add_peak"
        self._apply_tool_mode_to(self._plot_widget)
        if self._fp_plot_widget is not None:
            self._apply_tool_mode_to(self._fp_plot_widget)

    def _apply_tool_mode_to(self, plot_widget: pg.PlotWidget) -> None:
        """Apply the current tool mode to one panel's ViewBox."""
        vb = plot_widget.getPlotItem().vb
        if self._tool_mode == "zoom":
            vb.setMouseMode(pg.ViewBox.RectMode)
        else:  # "select", "pan", "add_peak" — all use PanMode
            vb.setMouseMode(pg.ViewBox.PanMode)

    def set_spectrum(self, spectrum: Spectrum, *, preserve_view: bool = False) -> None:
        """Display a spectrum in the viewer.

        Args:
            spectrum: Spectrum to display.
            preserve_view: When True, keep the current zoom/pan instead of
                resetting to the full view. Used on undo/redo so adding a peak
                while zoomed in does not snap the graph back to the full range.
        """
        self._spectrum = spectrum
        self._spectrum_curve.setData(x=spectrum.wavenumbers, y=spectrum.intensities)

        # Update Y-axis label from spectrum unit
        label_style = {"color": "#000000", "font-size": "10pt"}
        self._plot_widget.setLabel("left", spectrum.display_y_unit.value, **label_style)

        if self._split_mode and self._spectrum_curve_fp is not None:
            self._spectrum_curve_fp.setData(x=spectrum.wavenumbers, y=spectrum.intensities)

        if not preserve_view:
            self.reset_view()

    def _default_x_range(self) -> tuple[float, float]:
        """Return the full-view x range: the standard IR window widened to the data.

        OMNIC spectra typically span 400–4000 cm⁻¹; a hardcoded 3800 top would
        hide stored peak annotations above it after load.
        """
        x_lo, x_hi = _X_DEFAULT_MIN, _X_DEFAULT_MAX
        if self._spectrum is not None and len(self._spectrum.wavenumbers):
            x_lo = min(x_lo, float(np.min(self._spectrum.wavenumbers)))
            x_hi = max(x_hi, float(np.max(self._spectrum.wavenumbers)))
        return x_lo, x_hi

    def reset_view(self) -> None:
        """Reset to full IR view, Y auto-fitted to visible data + labels."""
        x_lo, x_hi = self._default_x_range()
        if self._split_mode:
            self._plot_widget.setXRange(_SPLIT_WN, x_hi, padding=0.0)
            if self._fp_plot_widget is not None:
                self._fp_plot_widget.setXRange(x_lo, _SPLIT_WN, padding=0.0)
        else:
            self._plot_widget.setXRange(x_lo, x_hi, padding=0.0)

        if self._spectrum is None:
            return

        wn = self._spectrum.wavenumbers
        iy = self._spectrum.intensities

        # Fit Y only to data within the visible x window
        mask = (wn >= x_lo) & (wn <= x_hi)
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

        In split mode both panels are combined so callers (e.g. PDF export)
        see the full range rather than only the hi-wavenumber panel.
        """
        vb = self._plot_widget.getPlotItem().vb
        x_range = vb.viewRange()[0]
        if self._split_mode and self._fp_plot_widget is not None:
            fp_range = self._fp_plot_widget.getPlotItem().vb.viewRange()[0]
            all_x = list(x_range) + list(fp_range)
            return (float(min(all_x)), float(max(all_x)))
        return (float(min(x_range)), float(max(x_range)))

    def get_peak_label_placements(self) -> list[tuple[object, float, float]]:
        """Return the actual on-screen label position for every rendered peak label.

        Each entry is (peak, label_x, label_y) in data coordinates. Export code
        uses this so the PDF reproduces the exact viewer label layout instead of
        recomputing default offsets.
        """
        placements: list[tuple[object, float, float]] = []
        for item in self._peak_label_items():
            placements.append((item._peak, float(item._data_x), float(item._data_y)))
        return placements

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

        # Clear previous peak annotations from the main plot
        for item in self._peak_items:
            self._plot_widget.removeItem(item)
        self._peak_items.clear()

        # Clear previous peak annotations from the fingerprint panel
        self._clear_fp_items()

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

        if self._split_mode and self._fp_plot_widget is not None:
            # Split: hi peaks (>split) to main plot, lo peaks (<=split) to fp panel
            hi_peaks = [p for p in peaks if p.position > _SPLIT_WN]
            lo_peaks = [p for p in peaks if p.position <= _SPLIT_WN]
            self._render_peaks_to(
                hi_peaks, self._plot_widget, self._peak_items, peaks_are_dips, y_span
            )
            self._render_peaks_to(
                lo_peaks, self._fp_plot_widget, self._peak_items_fp, peaks_are_dips, y_span
            )
        else:
            self._render_peaks_to(
                peaks, self._plot_widget, self._peak_items, peaks_are_dips, y_span
            )

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

                best_candidate: (
                    tuple[
                        float,
                        float,
                        tuple[float, float, float, float],
                        tuple[tuple[float, float], tuple[float, float], tuple[float, float]],
                        float,
                    ]
                    | None
                ) = None

                for level in range(18):
                    candidate_y = label._peak_y + (direction * (base_gap + (level * vertical_step)))
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
        for curve in self._overlay_curves_fp:
            if self._fp_plot_widget is not None:
                self._fp_plot_widget.removeItem(curve)
        self._overlay_curves_fp.clear()

        alpha = int(self._overlay_alpha / 100 * 255)
        for i, spectrum in enumerate(self._overlay_spectra_cache):
            hex_color = _OVERLAY_COLORS[i % len(_OVERLAY_COLORS)]
            r = int(hex_color[1:3], 16)
            g = int(hex_color[3:5], 16)
            b = int(hex_color[5:7], 16)
            pen = pg.mkPen((r, g, b, alpha), width=1.5)
            curve = self._plot_widget.plot(
                x=spectrum.wavenumbers,
                y=spectrum.intensities,
                pen=pen,
            )
            self._overlay_curves.append(curve)
            if self._split_mode and self._fp_plot_widget is not None:
                curve_fp = self._fp_plot_widget.plot(
                    x=spectrum.wavenumbers,
                    y=spectrum.intensities,
                    pen=pen,
                )
                self._overlay_curves_fp.append(curve_fp)

    def _redraw_diagnostic_regions(self) -> None:
        for item in self._diagnostic_region_items:
            self._plot_widget.removeItem(item)
        self._diagnostic_region_items.clear()
        for item in self._diagnostic_region_items_fp:
            if self._fp_plot_widget is not None:
                self._fp_plot_widget.removeItem(item)
        self._diagnostic_region_items_fp.clear()

        if not self._diagnostic_regions_visible:
            return

        for region in self._diagnostic_regions_cache:
            brush, pen = self._diagnostic_region_style(region)
            rmin, rmax = float(region.range_min), float(region.range_max)

            # Add to main plot (always — the main plot shows the full range or the hi panel)
            item = pg.LinearRegionItem(
                values=(rmin, rmax),
                brush=brush,
                pen=pen,
                movable=False,
                swapMode="sort",
            )
            item.setZValue(-50)
            self._plot_widget.addItem(item)
            self._diagnostic_region_items.append(item)

            # In split mode, also add to fingerprint panel if region overlaps its range
            if self._split_mode and self._fp_plot_widget is not None:
                if rmin < _SPLIT_WN:
                    item_fp = pg.LinearRegionItem(
                        values=(rmin, min(rmax, _SPLIT_WN)),
                        brush=brush,
                        pen=pen,
                        movable=False,
                        swapMode="sort",
                    )
                    item_fp.setZValue(-50)
                    self._fp_plot_widget.addItem(item_fp)
                    self._diagnostic_region_items_fp.append(item_fp)

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
        items = [item for item in self._peak_items if isinstance(item, _DraggableLabel)]
        if self._split_mode:
            items += [item for item in self._peak_items_fp if isinstance(item, _DraggableLabel)]
        return items

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

    def _on_label_shift_clicked(self, peak_x: float) -> None:
        """Called on Shift+click of a label; delete peak in any tool mode."""
        if not self._peaks:
            return
        closest = min(self._peaks, key=lambda p: abs(p.position - peak_x))
        if abs(closest.position - peak_x) <= 1.0:
            self.peak_delete_requested.emit(closest)

    def _on_mouse_clicked(self, event) -> None:
        """Handle mouse click on the main plot scene."""
        self._handle_mouse_clicked(event, self._plot_widget)

    def _on_fp_mouse_clicked(self, event) -> None:
        """Handle mouse click on the fingerprint-panel scene."""
        if self._fp_plot_widget is not None:
            self._handle_mouse_clicked(event, self._fp_plot_widget)

    def _handle_mouse_clicked(self, event, plot_widget: pg.PlotWidget) -> None:
        """Handle mouse click for peak picking or selection.

        Coordinates are mapped through the ViewBox of the panel that produced
        the event — each panel has its own scene, so mapping through the main
        plot's ViewBox would return wrong wavenumbers for the fingerprint panel.
        """
        pos = event.scenePos()
        plot_item = plot_widget.getPlotItem()
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
        """Handle mouse move on the main plot scene."""
        self._handle_mouse_moved(pos, self._plot_widget)

    def _on_fp_mouse_moved(self, pos) -> None:
        """Handle mouse move on the fingerprint-panel scene."""
        if self._fp_plot_widget is not None:
            self._handle_mouse_moved(pos, self._fp_plot_widget)

    def _handle_mouse_moved(self, pos, plot_widget: pg.PlotWidget) -> None:
        """Emit cursor position for the panel that produced the event."""
        plot_item = plot_widget.getPlotItem()
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
