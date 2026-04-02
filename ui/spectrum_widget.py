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


class SpectrumWidget(QWidget):
    """PyQtGraph-based interactive IR spectrum viewer."""

    peak_clicked = Signal(float, float)  # (wavenumber, intensity)
    cursor_moved = Signal(float, float)  # (wavenumber, intensity_at_cursor)

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
        self._plot_widget.setLabel("left", spectrum.y_unit.value, **label_style)

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

        # Draw new peak annotations
        for peak in peaks:
            # Dashed vertical line at peak position
            line = pg.InfiniteLine(
                pos=peak.position,
                angle=90,
                pen=pg.mkPen("r", width=1, style=Qt.PenStyle.DashLine),
            )
            self._plot_widget.addItem(line)
            self._peak_items.append(line)

            # Text label above the peak
            label = pg.TextItem(
                text=peak.display_label,
                color="r",
                anchor=(0.5, 1.0),
            )
            label.setPos(peak.position, peak.intensity)
            self._plot_widget.addItem(label)
            self._peak_items.append(label)

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

    def _on_mouse_clicked(self, event) -> None:
        """Handle mouse click on the plot scene for peak picking."""
        if not self._add_peak_mode:
            return

        pos = event.scenePos()
        plot_item = self._plot_widget.getPlotItem()
        vb = plot_item.vb

        if not vb.sceneBoundingRect().contains(pos):
            return

        mouse_point = vb.mapSceneToView(pos)
        wavenumber = mouse_point.x()
        intensity = self._intensity_at(wavenumber)
        self.peak_clicked.emit(wavenumber, intensity)

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
        return float(
            np.interp(
                wavenumber, self._spectrum.wavenumbers[::-1], self._spectrum.intensities[::-1]
            )
        )
