"""
ReportTemplate — Šablona PDF reportu.

Zodpovědnost:
- Definice layoutu stránky (hlavička, zápatí, logo)
- Styly textu (fonty, velikosti, barvy)
- Konfigurovatelné sekce reportu
"""

from __future__ import annotations


class ReportTemplate:
    """Defines the visual layout and style for PDF reports."""

    # Page layout (A4 in mm)
    PAGE_WIDTH_MM = 210
    PAGE_HEIGHT_MM = 297

    # Margins in mm
    MARGIN_TOP = 20
    MARGIN_BOTTOM = 20
    MARGIN_LEFT = 20
    MARGIN_RIGHT = 20

    # Header
    HEADER_TITLE = "IR Spectrum Analysis Report"
    INCLUDE_LOGO = False
