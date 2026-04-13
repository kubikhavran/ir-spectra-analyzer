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
from PySide6.QtWidgets import QVBoxLayout, QWidget

from core.peak import Peak
from core.spectrum import Spectrum


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

    _SIDE_LABEL_DIAGONAL_FACTOR = 0.35

    def __init__(
        self,
        peak: Peak,
        peak_x: float,
        peak_y: float,
        label_offset: float,
        label_x: float,
        label_y: float,
        click_callback=None,
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
        self._leader: pg.PlotCurveItem | None = None

    def set_leader(self, leader: pg.PlotCurveItem) -> None:
        """Attach the leader line item and draw initial position."""
        self._leader = leader
        self._update_leader()

    def _update_leader(self) -> None:
        """Recompute leader using explicitly stored data coordinates."""
        if self._leader is None:
            return
        lx = self._data_x
        ly = self._data_y
        px = self._peak_x
        py = self._peak_y
        # Keep the default vertical-only appearance when the label stays centered
        # above the peak. When the label is moved sideways, shorten the angled
        # branch so the diagonal connector does not dominate the annotation.
        diagonal_factor = 1.0
        if abs(lx - px) > 1e-6:
            diagonal_factor = self._SIDE_LABEL_DIAGONAL_FACTOR

        # Elbow is `label_offset` below the label (toward peak), dynamic with drag.
        ey = ly - (self._label_offset * diagonal_factor)
        # Clamp: elbow must not overshoot the peak apex
        if self._label_offset > 0:
            ey = max(py, ey)  # absorbance: elbow stays at or above peak
        else:
            ey = min(py, ey)  # transmittance: elbow stays at or below peak
        self._leader.setData(
            x=np.array([px, px, lx], dtype=float),
            y=np.array([py, ey, ly], dtype=float),
        )

    def mouseClickEvent(self, ev) -> None:  # noqa: N802
        """Handle single click: notify parent so peak can be selected/assigned."""
        if ev.button() != Qt.MouseButton.LeftButton:
            ev.ignore()
            return
        ev.accept()
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

    peak_clicked = Signal(float, float)  # (wavenumber, intensity)
    cursor_moved = Signal(float, float)  # (wavenumber, intensity_at_cursor)
    peak_selected_in_viewer = Signal(object)  # emits Peak instance

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._spectrum: Spectrum | None = None
        self._peaks: list[Peak] = []
        self._peak_items: list = []
        self._add_peak_mode: bool = False
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Initialize PyQtGraph plot widget with OMNIC-like white style."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._plot_widget = pg.PlotWidget()

        # OMNIC-like style: white background, black axes
        self._plot_widget.setBackground("w")

        # Axis labels with black color
        label_style = {"color": "#000000", "font-size": "10pt"}
        self._plot_widget.setLabel("bottom", "Wavenumber (cm⁻¹)", **label_style)
        self._plot_widget.setLabel("left", "Absorbance", **label_style)

        # Light gray grid
        self._plot_widget.showGrid(x=True, y=True, alpha=0.15)

        # IR convention: high to low wavenumber
        self._plot_widget.invertX(True)

        # Style axis ticks/labels black
        for axis in ("bottom", "left"):
            ax = self._plot_widget.getAxis(axis)
            ax.setPen(pg.mkPen(color="k", width=1))
            ax.setTextPen(pg.mkPen(color="k"))

        layout.addWidget(self._plot_widget)

        # Spectrum curve: black, width 1
        self._spectrum_curve = self._plot_widget.plot(pen=pg.mkPen("k", width=1))

        self._overlay_curves: list = []

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

        self._plot_widget.autoRange()

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
                text=f"{peak.position:.1f}",
                color=(0, 0, 0),
                angle=90,
                anchor=anchor,
            )
            # IMPORTANT: addItem BEFORE setPos so ViewBox is the parent when the
            # position is stored.  Without a ViewBox parent, PyQtGraph interprets
            # the coordinates as scene-pixel values; after addItem it re-interprets
            # the stored value as data coordinates — giving the wrong visual position.
            self._plot_widget.addItem(label)
            label.setPos(lx, ly)
            self._peak_items.append(label)
            label.set_leader(leader)

    def set_overlay_spectra(self, spectra: list) -> None:
        """Overlay additional spectra (e.g. reference candidates) in gray.

        Args:
            spectra: List of Spectrum objects to overlay. Pass empty list to clear.
        """
        for curve in self._overlay_curves:
            self._plot_widget.removeItem(curve)
        self._overlay_curves.clear()

        for i, spectrum in enumerate(spectra):
            # Cycle through grays: 160, 140, 120 for top candidates
            gray_level = max(100, 180 - i * 20)
            color = f"#{gray_level:02x}{gray_level:02x}{gray_level:02x}"
            curve = self._plot_widget.plot(
                x=spectrum.wavenumbers,
                y=spectrum.intensities,
                pen=pg.mkPen(color, width=1, style=Qt.PenStyle.DotLine),
            )
            self._overlay_curves.append(curve)

    def _on_label_clicked(self, peak_x: float) -> None:
        """Called when a peak label is directly clicked; find and select the peak."""
        if not self._peaks:
            return
        closest = min(self._peaks, key=lambda p: abs(p.position - peak_x))
        if abs(closest.position - peak_x) <= 1.0:  # exact match (label stores peak_x)
            self.peak_selected_in_viewer.emit(closest)

    def _on_mouse_clicked(self, event) -> None:
        """Handle mouse click on the plot scene for peak picking or selection."""
        pos = event.scenePos()
        plot_item = self._plot_widget.getPlotItem()
        vb = plot_item.vb

        if not vb.sceneBoundingRect().contains(pos):
            return

        mouse_point = vb.mapSceneToView(pos)
        wavenumber = mouse_point.x()

        if self._add_peak_mode:
            # Don't add a new peak if the click landed on an existing label
            if self._peaks:
                closest = min(self._peaks, key=lambda p: abs(p.position - wavenumber))
                if abs(closest.position - wavenumber) <= 5.0:
                    return  # user clicked on/near an existing label — label handles it
            intensity = self._intensity_at(wavenumber)
            self.peak_clicked.emit(wavenumber, intensity)
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
