"""
SpectrumRenderer — Statický render spektra pro PDF.

Zodpovědnost:
- Renderování publication-quality spektra pomocí Matplotlib
- Vizuální styl co nejbližší Thermo OMNIC (bílé pozadí, inverzní X, box frame)
- Anotace peaků v statickém obrázku
- Export jako PNG pro vložení do PDF

Poznámka: Matplotlib je použit zde (nikoliv PyQtGraph) protože
ReportLab vyžaduje statický rastrový/vektorový obrázek.

OMNIC visual conventions implemented here:
- White background, full 4-sided box frame, no background grid
- X-axis inverted (high→low wavenumber), major ticks every 500 cm⁻¹, minor every 100 cm⁻¹
- %Transmittance Y-axis fixed 0–110; Absorbance Y-axis starts at 0, auto top
- Thin black spectrum line (0.8 pt)
- Peak labels: short vertical line from apex + rotated wavenumber text above
- Sans-serif font throughout
"""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np

from core.peak import Peak
from core.spectrum import SpectralUnit

# Approximate tick spacing used by OMNIC
_WN_MAJOR_STEP = 500.0  # cm⁻¹
_WN_MINOR_STEP = 100.0  # cm⁻¹


class SpectrumRenderer:
    """Renders IR spectrum as a static Matplotlib figure for PDF embedding."""

    def render_to_bytes(
        self,
        wavenumbers: np.ndarray,
        intensities: np.ndarray,
        peaks: list[Peak],
        dpi: int = 150,
        y_unit: SpectralUnit = SpectralUnit.ABSORBANCE,
        is_dip_spectrum: bool = False,
    ) -> bytes:
        """Render spectrum with peak annotations to PNG bytes in memory.

        Args:
            wavenumbers: X-axis data (cm⁻¹), any order — plot will invert.
            intensities: Y-axis data.
            peaks: List of peaks to annotate.
            dpi: Output resolution.
            y_unit: Spectral intensity unit — controls Y-axis label and range.
            is_dip_spectrum: When True, peaks are downward dips (%T style) and
                labels are drawn below the apex, matching the live viewer.

        Returns:
            PNG image as bytes.
        """
        import matplotlib  # noqa: PLC0415

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # noqa: PLC0415
        import matplotlib.ticker as ticker  # noqa: PLC0415

        # --- Figure / axes setup ---
        fig, ax = plt.subplots(figsize=(7.5, 3.2))
        fig.patch.set_facecolor("white")
        ax.set_facecolor("white")

        # --- Plot spectrum ---
        ax.plot(wavenumbers, intensities, color="black", linewidth=0.8, antialiased=True)

        # --- X-axis: inverted, OMNIC-style ticks ---
        ax.invert_xaxis()
        wn_min = float(np.min(wavenumbers))
        wn_max = float(np.max(wavenumbers))

        # Major ticks at every 500 cm⁻¹ rounded to grid
        major_start = np.ceil(wn_min / _WN_MAJOR_STEP) * _WN_MAJOR_STEP
        major_end = np.floor(wn_max / _WN_MAJOR_STEP) * _WN_MAJOR_STEP
        major_ticks = np.arange(major_start, major_end + 1, _WN_MAJOR_STEP)
        ax.set_xticks(major_ticks)

        minor_start = np.ceil(wn_min / _WN_MINOR_STEP) * _WN_MINOR_STEP
        minor_end = np.floor(wn_max / _WN_MINOR_STEP) * _WN_MINOR_STEP
        minor_ticks = np.arange(minor_start, minor_end + 1, _WN_MINOR_STEP)
        ax.set_xticks(minor_ticks, minor=True)

        ax.tick_params(
            axis="x", which="major", length=5, width=0.8, labelsize=8, direction="in", top=True
        )
        ax.tick_params(axis="x", which="minor", length=3, width=0.6, direction="in", top=True)

        # --- Y-axis: unit-aware range ---
        ax.tick_params(
            axis="y", which="major", length=5, width=0.8, labelsize=8, direction="in", right=True
        )
        ax.tick_params(axis="y", which="minor", length=3, width=0.6, direction="in", right=True)

        if y_unit == SpectralUnit.TRANSMITTANCE:
            ax.set_ylim(0.0, 110.0)
            ax.yaxis.set_major_locator(ticker.MultipleLocator(20))
            ax.yaxis.set_minor_locator(ticker.MultipleLocator(10))
        elif is_dip_spectrum:
            # Corrected %T: near-zero top, negative dips at bottom
            y_data_min = float(np.min(intensities))
            ax.set_ylim(bottom=y_data_min * 1.10, top=5.0)
            ax.yaxis.set_minor_locator(ticker.AutoMinorLocator(2))
        else:
            # Absorbance / Reflectance / Single Beam / non-dip BASELINE_CORRECTED
            y_data_max = float(np.max(intensities))
            ax.set_ylim(bottom=0.0, top=y_data_max * 1.10)
            ax.yaxis.set_minor_locator(ticker.AutoMinorLocator(2))

        # --- Labels ---
        ax.set_xlabel("Wavenumber (cm⁻¹)", fontsize=9, labelpad=4, fontfamily="sans-serif")
        ax.set_ylabel(y_unit.value, fontsize=9, labelpad=4, fontfamily="sans-serif")

        # --- Frame: full 4-sided box, no grid ---
        for spine in ax.spines.values():
            spine.set_linewidth(0.8)
            spine.set_color("black")
        ax.grid(False)

        # --- Peak annotations ---
        # Style: short vertical line from apex + rotated wavenumber text.
        # For dip-type spectra (%T) the line goes DOWN from the apex and the
        # label sits below, matching the live PyQtGraph viewer behaviour.
        if peaks:
            y_lo, y_hi = ax.get_ylim()
            y_span = y_hi - y_lo
            label_gap = y_span * 0.015
            tick_height = y_span * 0.055

            for peak in peaks:
                apex_y = peak.intensity
                if is_dip_spectrum:
                    line_end = max(apex_y - tick_height, y_lo + abs(y_lo) * 0.03)
                    text_y = line_end - label_gap
                    va = "top"
                else:
                    line_end = min(apex_y + tick_height, y_hi * 0.97)
                    text_y = line_end + label_gap
                    va = "bottom"
                ax.plot(
                    [peak.position, peak.position],
                    [apex_y, line_end],
                    color="black",
                    linewidth=0.7,
                    solid_capstyle="butt",
                )
                ax.text(
                    peak.position,
                    text_y,
                    str(int(round(peak.position))),
                    rotation=90,
                    va=va,
                    ha="center",
                    fontsize=7,
                    fontfamily="sans-serif",
                    color="black",
                )

        # --- X-axis limits: respect data range tightly ---
        ax.set_xlim(wn_max, wn_min)  # inverted

        fig.tight_layout(pad=0.6)

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=dpi, facecolor="white")
        plt.close(fig)
        buf.seek(0)
        return buf.read()

    def render_to_file(
        self,
        wavenumbers: np.ndarray,
        intensities: np.ndarray,
        peaks: list[Peak],
        output_path: Path,
        dpi: int = 300,
        y_unit: SpectralUnit = SpectralUnit.ABSORBANCE,
        is_dip_spectrum: bool = False,
    ) -> None:
        """Render spectrum with peak annotations to PNG file.

        Args:
            wavenumbers: X-axis data.
            intensities: Y-axis data.
            peaks: List of peaks to annotate.
            output_path: Destination PNG file.
            dpi: Output resolution.
            y_unit: Spectral intensity unit for Y-axis label.
            is_dip_spectrum: When True, peak labels are placed below the apex.
        """
        png_bytes = self.render_to_bytes(
            wavenumbers, intensities, peaks, dpi=dpi, y_unit=y_unit, is_dip_spectrum=is_dip_spectrum
        )
        output_path.write_bytes(png_bytes)
