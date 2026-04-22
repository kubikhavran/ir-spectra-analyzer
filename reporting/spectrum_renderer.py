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
from matplotlib import colors as mcolors

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
        figsize: tuple[float, float] = (7.5, 3.2),
        x_min: float = 400.0,
        x_max: float = 3800.0,
        y_view_range: tuple[float, float] | None = None,
        diagnostic_regions: tuple[object, ...] | list[object] = (),
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
        fig, ax = plt.subplots(figsize=figsize)
        _fscale = figsize[0] / 7.5  # font scale relative to default width
        _fs_label = max(8, round(9 * _fscale))
        _fs_tick = max(7, round(8 * _fscale))
        _fs_peak = max(6, round(7 * _fscale))
        fig.patch.set_facecolor("white")
        ax.set_facecolor("white")

        if diagnostic_regions:
            for region in diagnostic_regions:
                facecolor, edgecolor, linestyle, linewidth, alpha = self._diagnostic_region_style(
                    region
                )
                ax.axvspan(
                    float(region.range_min),
                    float(region.range_max),
                    facecolor=facecolor,
                    edgecolor=edgecolor,
                    linestyle=linestyle,
                    linewidth=linewidth,
                    alpha=alpha,
                    zorder=0.1,
                )

        # --- Plot spectrum ---
        ax.plot(wavenumbers, intensities, color="black", linewidth=0.8, antialiased=True, zorder=1.0)

        # --- X-axis: inverted, OMNIC-style ticks ---
        ax.invert_xaxis()
        _plot_x_lo, _plot_x_hi = min(x_min, x_max), max(x_min, x_max)

        # Major ticks at every 500 cm⁻¹ within the visible range
        major_start = np.ceil(_plot_x_lo / _WN_MAJOR_STEP) * _WN_MAJOR_STEP
        major_end = np.floor(_plot_x_hi / _WN_MAJOR_STEP) * _WN_MAJOR_STEP
        major_ticks = np.arange(major_start, major_end + 1, _WN_MAJOR_STEP)
        ax.set_xticks(major_ticks)

        minor_start = np.ceil(_plot_x_lo / _WN_MINOR_STEP) * _WN_MINOR_STEP
        minor_end = np.floor(_plot_x_hi / _WN_MINOR_STEP) * _WN_MINOR_STEP
        minor_ticks = np.arange(minor_start, minor_end + 1, _WN_MINOR_STEP)
        ax.set_xticks(minor_ticks, minor=True)

        ax.tick_params(
            axis="x", which="major", length=5, width=0.8, labelsize=_fs_tick, direction="in", top=True
        )
        ax.tick_params(axis="x", which="minor", length=3, width=0.6, direction="in", top=True)

        # --- Y-axis: auto-fit to visible data (matches live viewer reset_view) ---
        ax.tick_params(
            axis="y", which="major", length=5, width=0.8, labelsize=_fs_tick, direction="in", right=True
        )
        ax.tick_params(axis="y", which="minor", length=3, width=0.6, direction="in", right=True)

        _y_min, _y_max = self._resolve_y_limits(
            wavenumbers=wavenumbers,
            intensities=intensities,
            peaks=peaks,
            x_min=_plot_x_lo,
            x_max=_plot_x_hi,
            y_view_range=y_view_range,
            is_dip_spectrum=is_dip_spectrum or y_unit == SpectralUnit.TRANSMITTANCE,
        )
        ax.set_ylim(bottom=_y_min, top=_y_max)
        ax.yaxis.set_major_locator(ticker.AutoLocator())
        ax.yaxis.set_minor_locator(ticker.AutoMinorLocator(2))

        # --- Labels ---
        ax.set_xlabel("Wavenumber (cm⁻¹)", fontsize=_fs_label, labelpad=4, fontfamily="sans-serif")
        ax.set_ylabel(y_unit.value, fontsize=_fs_label, labelpad=4, fontfamily="sans-serif")

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
            data_y_span = float(np.ptp(intensities))
            if data_y_span == 0:
                data_y_span = 1.0

            for peak in peaks:
                label_x, label_y = self._label_position(
                    peak,
                    data_y_span=data_y_span,
                    is_dip_spectrum=is_dip_spectrum,
                )
                leader_points = self._leader_points(
                    peak_x=peak.position,
                    peak_y=peak.intensity,
                    label_x=label_x,
                    label_y=label_y,
                )
                ax.plot(
                    [point[0] for point in leader_points],
                    [point[1] for point in leader_points],
                    color="black",
                    linewidth=0.7,
                    solid_capstyle="butt",
                    zorder=1.2,
                )
                ax.text(
                    label_x,
                    label_y,
                    str(int(round(peak.position))),
                    rotation=90,
                    va="bottom" if label_y >= peak.intensity else "top",
                    ha="center",
                    fontsize=_fs_peak,
                    fontfamily="sans-serif",
                    color="black",
                    zorder=1.3,
                )

        # --- X-axis limits: use the requested visible range ---
        ax.set_xlim(_plot_x_hi, _plot_x_lo)  # inverted: high→low

        fig.tight_layout(pad=0.6 if figsize[0] <= 8.0 else 1.2)

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
            wavenumbers,
            intensities,
            peaks,
            dpi=dpi,
            y_unit=y_unit,
            is_dip_spectrum=is_dip_spectrum,
        )
        output_path.write_bytes(png_bytes)

    @staticmethod
    def _label_position(
        peak: Peak,
        *,
        data_y_span: float,
        is_dip_spectrum: bool,
    ) -> tuple[float, float]:
        """Return the same label position used by the live spectrum viewer."""
        default_offset = (-data_y_span if is_dip_spectrum else data_y_span) * 0.065
        if peak.manual_placement:
            return (
                float(peak.position + peak.label_offset_x),
                float(peak.intensity + peak.label_offset_y),
            )
        return (float(peak.position), float(peak.intensity + default_offset))

    @staticmethod
    def _leader_points(
        *,
        peak_x: float,
        peak_y: float,
        label_x: float,
        label_y: float,
    ) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]]:
        """Return the 3-point leader geometry matching the live PyQtGraph viewer."""
        label_offset = label_y - peak_y
        diagonal_factor = 1.0 if abs(label_x - peak_x) <= 1e-6 else 0.05
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

    @classmethod
    def _resolve_y_limits(
        cls,
        *,
        wavenumbers: np.ndarray,
        intensities: np.ndarray,
        peaks: list[Peak],
        x_min: float,
        x_max: float,
        y_view_range: tuple[float, float] | None,
        is_dip_spectrum: bool,
    ) -> tuple[float, float]:
        """Resolve the y-axis limits, matching the live viewer's auto-fit when possible."""
        if y_view_range is not None:
            return (float(min(y_view_range)), float(max(y_view_range)))

        visible_mask = (wavenumbers >= x_min) & (wavenumbers <= x_max)
        visible_y = intensities[visible_mask] if visible_mask.any() else intensities
        y_min = float(np.min(visible_y))
        y_max = float(np.max(visible_y))
        data_y_span = max(y_max - y_min, 1e-9)

        visible_peaks = [peak for peak in peaks if x_min <= peak.position <= x_max]
        if visible_peaks:
            label_margin = data_y_span * 0.08
            label_y_values = [
                cls._label_position(
                    peak,
                    data_y_span=data_y_span,
                    is_dip_spectrum=is_dip_spectrum,
                )[1]
                for peak in visible_peaks
            ]
            if label_y_values:
                if is_dip_spectrum:
                    y_min = min(y_min, min(label_y_values) - label_margin)
                else:
                    y_max = max(y_max, max(label_y_values) + label_margin)

        if is_dip_spectrum:
            return (y_min - data_y_span * 0.20, y_max + data_y_span * 0.05)
        return (max(0.0, y_min - data_y_span * 0.05), y_max + data_y_span * 0.20)

    @staticmethod
    def _diagnostic_region_style(
        region,
    ) -> tuple[tuple[float, float, float], tuple[float, float, float], str, float, float]:
        """Return a Matplotlib style tuple mirroring the live viewer overlays."""
        if getattr(region, "is_missing_required", False):
            return (
                mcolors.to_rgb("#FDEDEC"),
                mcolors.to_rgb("#C0392B"),
                "--",
                1.2,
                0.35,
            )
        if getattr(region, "is_confirmed", False):
            color = mcolors.to_rgb(region.color)
            return (color, color, "-", 1.0, 0.18)
        return (
            mcolors.to_rgb("#FCF3CF"),
            mcolors.to_rgb("#AF6E00"),
            "--",
            1.0,
            0.24,
        )
