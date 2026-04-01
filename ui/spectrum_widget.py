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
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout

from core.peak import Peak
from core.spectrum import Spectrum


class SpectrumWidget(QWidget):
    """PyQtGraph-based interactive IR spectrum viewer."""

    peak_clicked = Signal(float, float)  # (wavenumber, intensity)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._spectrum: Spectrum | None = None
        self._peaks: list[Peak] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Initialize PyQtGraph plot widget."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._plot_widget = pg.PlotWidget()
        self._plot_widget.setLabel("bottom", "Wavenumber (cm⁻¹)")
        self._plot_widget.setLabel("left", "Absorbance")
        self._plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self._plot_widget.invertX(True)  # IR convention: high to low wavenumber
        layout.addWidget(self._plot_widget)

        self._spectrum_curve = self._plot_widget.plot(pen="w")

    def set_spectrum(self, spectrum: Spectrum) -> None:
        """Display a spectrum in the viewer.

        Args:
            spectrum: Spectrum to display.
        """
        self._spectrum = spectrum
        self._spectrum_curve.setData(x=spectrum.wavenumbers, y=spectrum.intensities)
        self._plot_widget.autoRange()

    def set_peaks(self, peaks: list[Peak]) -> None:
        """Update peak annotations in the viewer.

        Args:
            peaks: List of peaks to annotate.
        """
        self._peaks = peaks
        # TODO: Render peak annotations as pyqtgraph InfLineItems / TextItems
