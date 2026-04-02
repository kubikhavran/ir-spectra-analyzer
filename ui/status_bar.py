"""
StatusBar — Stavový řádek aplikace.

Zodpovědnost:
- Zobrazení aktuálních souřadnic kurzoru v grafu (wavenumber, intensity)
- Stav operace (načítání, export, ...)
- Počet detekovaných peaků
"""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QStatusBar


class AppStatusBar(QStatusBar):
    """Application status bar showing cursor coordinates and status messages."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._cursor_label = QLabel("Ready")
        self.addPermanentWidget(self._cursor_label)

    def update_cursor(self, wavenumber: float, intensity: float) -> None:
        """Update cursor position display.

        Args:
            wavenumber: Current X position in cm⁻¹.
            intensity: Current Y value.
        """
        self._cursor_label.setText(f"{wavenumber:.1f} cm⁻¹ | {intensity:.4f}")
