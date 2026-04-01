"""
PeakPicker — Interaktivní přidávání peaků klikáním.

Zodpovědnost:
- Zachycení kliknutí v SpectrumWidget v režimu "Add Peak"
- Přepočet souřadnic kliknutí na wavenumber + intensity
- Emitování signálu pro přidání peaku do Project

Architektonické pravidlo:
  PeakPicker POUZE převádí UI akci na doménový event.
  Samotné vytvoření Peak objektu provádí core vrstva.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class PeakPicker(QObject):
    """Handles click-to-add-peak interaction mode."""

    peak_added = Signal(float, float)  # (wavenumber, intensity)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._active = False

    def activate(self) -> None:
        """Enable peak picking mode."""
        self._active = True

    def deactivate(self) -> None:
        """Disable peak picking mode."""
        self._active = False

    def on_plot_click(self, wavenumber: float, intensity: float) -> None:
        """Process a plot click event.

        Args:
            wavenumber: Clicked wavenumber position (cm⁻¹).
            intensity: Spectrum intensity at click position.
        """
        if self._active:
            self.peak_added.emit(wavenumber, intensity)
