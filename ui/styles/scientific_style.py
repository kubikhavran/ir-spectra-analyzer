"""
ScientificStyle — Styl os, tick marks, grid pro vědecké grafy.

Zodpovědnost:
- Konfigurace PyQtGraph pro vědecký look (publikační kvalita)
- Tick marks, grid, font os
- IR spektrometrické konvence (invertovaná X osa)
"""
from __future__ import annotations

import pyqtgraph as pg


def apply_scientific_style(plot_widget: pg.PlotWidget) -> None:
    """Apply scientific plotting style to a PyQtGraph plot widget.

    Args:
        plot_widget: The PlotWidget to style.
    """
    plot_widget.setBackground("#FFFFFF")
    plot_widget.getAxis("bottom").setTextPen("#000000")
    plot_widget.getAxis("left").setTextPen("#000000")
    plot_widget.showGrid(x=True, y=True, alpha=0.2)
    plot_widget.invertX(True)  # IR convention: wavenumber decreases left to right
