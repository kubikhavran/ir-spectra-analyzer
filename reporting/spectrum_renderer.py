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

# Split-axis width ratios (hi-wavenumber : fingerprint)
_HI_RATIO = 35
_LO_RATIO = 65


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
        split_at: float | None = 2000.0,
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
            split_at: When not None and within the x range, render two side-by-side
                axes split at this wavenumber (hi-region left, fingerprint right).

        Returns:
            PNG image as bytes.
        """
        import matplotlib  # noqa: PLC0415

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # noqa: PLC0415
        import matplotlib.ticker as ticker  # noqa: PLC0415

        _fscale = figsize[0] / 7.5  # font scale relative to default width
        _fs_label = max(8, round(9 * _fscale))
        _fs_tick = max(7, round(8 * _fscale))
        _fs_peak = max(5, round(5.5 * _fscale))
        _plot_x_lo, _plot_x_hi = min(x_min, x_max), max(x_min, x_max)
        _is_dip = is_dip_spectrum or y_unit == SpectralUnit.TRANSMITTANCE

        _y_min, _y_max = self._resolve_y_limits(
            wavenumbers=wavenumbers,
            intensities=intensities,
            peaks=peaks,
            x_min=_plot_x_lo,
            x_max=_plot_x_hi,
            y_view_range=y_view_range,
            is_dip_spectrum=_is_dip,
        )

        # Decide rendering mode
        _use_split = split_at is not None and _plot_x_lo < split_at < _plot_x_hi

        if _use_split:
            return self._render_split(
                wavenumbers=wavenumbers,
                intensities=intensities,
                peaks=peaks,
                dpi=dpi,
                y_unit=y_unit,
                is_dip_spectrum=is_dip_spectrum,
                figsize=figsize,
                split_at=float(split_at),  # type: ignore[arg-type]
                plot_x_lo=_plot_x_lo,
                plot_x_hi=_plot_x_hi,
                y_min=_y_min,
                y_max=_y_max,
                diagnostic_regions=diagnostic_regions,
                fscale=_fscale,
                fs_label=_fs_label,
                fs_tick=_fs_tick,
                fs_peak=_fs_peak,
                plt=plt,
                ticker=ticker,
            )

        # ── Single-axis (original) rendering ──────────────────────────────────
        fig, ax = plt.subplots(figsize=figsize)
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
        ax.plot(
            wavenumbers, intensities, color="black", linewidth=0.8, antialiased=True, zorder=1.0
        )

        # --- X-axis: inverted, OMNIC-style ticks ---
        ax.invert_xaxis()

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
            axis="x",
            which="major",
            length=5,
            width=0.8,
            labelsize=_fs_tick,
            direction="in",
            top=True,
        )
        ax.tick_params(axis="x", which="minor", length=3, width=0.6, direction="in", top=True)

        # --- Y-axis: auto-fit to visible data (matches live viewer reset_view) ---
        ax.tick_params(
            axis="y",
            which="major",
            length=5,
            width=0.8,
            labelsize=_fs_tick,
            direction="in",
            right=True,
        )
        ax.tick_params(axis="y", which="minor", length=3, width=0.6, direction="in", right=True)

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

    def _render_split(  # noqa: PLR0913, PLR0914
        self,
        *,
        wavenumbers: np.ndarray,
        intensities: np.ndarray,
        peaks: list[Peak],
        dpi: int,
        y_unit: SpectralUnit,
        is_dip_spectrum: bool,
        figsize: tuple[float, float],
        split_at: float,
        plot_x_lo: float,
        plot_x_hi: float,
        y_min: float,
        y_max: float,
        diagnostic_regions,
        fscale: float,
        fs_label: int,
        fs_tick: int,
        fs_peak: int,
        plt,
        ticker,
    ) -> bytes:
        """Render spectrum using a split-axis layout (hi-wavenumber | fingerprint).

        Uses add_axes with manually computed figure-fraction positions so that
        tight_layout / GridSpec wspace interactions cannot corrupt the layout.
        """
        fig_w, fig_h = figsize
        fig = plt.figure(figsize=figsize)
        fig.patch.set_facecolor("white")

        # --- Axis geometry in figure fractions ----------------------------------
        # Fixed inch margins → figure fractions (scale with figsize automatically)
        lm = 0.75 / fig_w  # left  — room for Y-axis label + tick labels
        rm = 0.10 / fig_w  # right — thin margin
        bm = 0.45 / fig_h  # bottom — room for X-axis tick labels + label
        tm = 0.10 / fig_h  # top   — thin margin

        total_w = 1.0 - lm - rm
        hi_frac = _HI_RATIO / (_HI_RATIO + _LO_RATIO)  # 0.35
        lo_frac = _LO_RATIO / (_HI_RATIO + _LO_RATIO)  # 0.65
        hi_w = total_w * hi_frac
        lo_w = total_w * lo_frac
        plot_h = 1.0 - bm - tm

        # Two independent axes placed side-by-side with zero gap
        ax_hi = fig.add_axes([lm, bm, hi_w, plot_h])
        ax_lo = fig.add_axes([lm + hi_w, bm, lo_w, plot_h])

        # --- Plot spectrum on both axes ---
        for _ax in (ax_hi, ax_lo):
            _ax.plot(
                wavenumbers,
                intensities,
                color="black",
                linewidth=0.8,
                antialiased=True,
                zorder=1.0,
            )

        # --- Diagnostic regions ---
        if diagnostic_regions:
            for region in diagnostic_regions:
                facecolor, edgecolor, linestyle, linewidth, alpha = self._diagnostic_region_style(
                    region
                )
                rmin, rmax = float(region.range_min), float(region.range_max)
                if rmax > split_at:
                    ax_hi.axvspan(
                        max(rmin, split_at),
                        rmax,
                        facecolor=facecolor,
                        edgecolor=edgecolor,
                        linestyle=linestyle,
                        linewidth=linewidth,
                        alpha=alpha,
                        zorder=0.1,
                    )
                if rmin < split_at:
                    ax_lo.axvspan(
                        rmin,
                        min(rmax, split_at),
                        facecolor=facecolor,
                        edgecolor=edgecolor,
                        linestyle=linestyle,
                        linewidth=linewidth,
                        alpha=alpha,
                        zorder=0.1,
                    )

        # --- Ticks on hi panel ---
        # The boundary tick (split_at itself) is drawn by the lo panel only, so
        # its label is not printed twice at the shared spine.
        hi_major_start = np.ceil(split_at / _WN_MAJOR_STEP) * _WN_MAJOR_STEP
        hi_major_end = np.floor(plot_x_hi / _WN_MAJOR_STEP) * _WN_MAJOR_STEP
        hi_majors = np.arange(hi_major_start, hi_major_end + 1, _WN_MAJOR_STEP)
        ax_hi.set_xticks(hi_majors[hi_majors > split_at])
        hi_minor_start = np.ceil(split_at / _WN_MINOR_STEP) * _WN_MINOR_STEP
        hi_minor_end = np.floor(plot_x_hi / _WN_MINOR_STEP) * _WN_MINOR_STEP
        hi_minors = np.arange(hi_minor_start, hi_minor_end + 1, _WN_MINOR_STEP)
        ax_hi.set_xticks(hi_minors[hi_minors > split_at], minor=True)

        # --- Ticks on lo panel ---
        lo_major_start = np.ceil(plot_x_lo / _WN_MAJOR_STEP) * _WN_MAJOR_STEP
        lo_major_end = np.floor(split_at / _WN_MAJOR_STEP) * _WN_MAJOR_STEP
        ax_lo.set_xticks(np.arange(lo_major_start, lo_major_end + 1, _WN_MAJOR_STEP))
        lo_minor_start = np.ceil(plot_x_lo / _WN_MINOR_STEP) * _WN_MINOR_STEP
        lo_minor_end = np.floor(split_at / _WN_MINOR_STEP) * _WN_MINOR_STEP
        ax_lo.set_xticks(np.arange(lo_minor_start, lo_minor_end + 1, _WN_MINOR_STEP), minor=True)

        # --- Spine / tick style ---
        for _ax in (ax_hi, ax_lo):
            _ax.tick_params(
                axis="x",
                which="major",
                length=5,
                width=0.8,
                labelsize=fs_tick,
                direction="in",
                top=True,
            )
            _ax.tick_params(axis="x", which="minor", length=3, width=0.6, direction="in", top=True)
            _ax.tick_params(
                axis="y",
                which="major",
                length=5,
                width=0.8,
                labelsize=fs_tick,
                direction="in",
                right=True,
            )
            _ax.tick_params(
                axis="y", which="minor", length=3, width=0.6, direction="in", right=True
            )
            for spine in _ax.spines.values():
                spine.set_linewidth(0.8)
                spine.set_color("black")
            _ax.grid(False)
            _ax.set_facecolor("white")

        # --- Hide inner boundary spines ---
        ax_hi.spines["right"].set_visible(False)
        ax_lo.spines["left"].set_visible(False)
        # Suppress both major AND minor y-ticks on the lo panel — minor ticks
        # would otherwise float in the middle of the plot at the panel boundary.
        ax_lo.tick_params(which="both", left=False, labelleft=False)
        ax_hi.tick_params(which="both", right=False)

        # --- Y axis label + locators only on left panel ---
        ax_hi.set_ylabel(y_unit.value, fontsize=fs_label, labelpad=4, fontfamily="sans-serif")
        ax_hi.yaxis.set_major_locator(ticker.AutoLocator())
        ax_hi.yaxis.set_minor_locator(ticker.AutoMinorLocator(2))
        ax_lo.yaxis.set_major_locator(ticker.AutoLocator())
        ax_lo.yaxis.set_minor_locator(ticker.AutoMinorLocator(2))

        # --- Break marks at the split boundary ---
        _d = 0.015
        kw = {"color": "k", "clip_on": False, "linewidth": 0.8, "transform": ax_hi.transAxes}
        ax_hi.plot([1 - _d, 1 + _d], [-_d, +_d], **kw)
        ax_hi.plot([1 - _d, 1 + _d], [1 - _d, 1 + _d], **kw)
        kw["transform"] = ax_lo.transAxes
        ax_lo.plot([-_d, +_d], [-_d, +_d], **kw)
        ax_lo.plot([-_d, +_d], [1 - _d, 1 + _d], **kw)

        # --- Peak annotations distributed to correct panel ---
        if peaks:
            data_y_span = float(np.ptp(intensities))
            if data_y_span == 0:
                data_y_span = 1.0

            for peak in peaks:
                target_ax = ax_hi if peak.position > split_at else ax_lo
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
                target_ax.plot(
                    [point[0] for point in leader_points],
                    [point[1] for point in leader_points],
                    color="black",
                    linewidth=0.7,
                    solid_capstyle="butt",
                    zorder=1.2,
                )
                target_ax.text(
                    label_x,
                    label_y,
                    str(int(round(peak.position))),
                    rotation=90,
                    va="bottom" if label_y >= peak.intensity else "top",
                    ha="center",
                    fontsize=fs_peak,
                    fontfamily="sans-serif",
                    color="black",
                    zorder=1.3,
                )

        # --- X label centred under both panels ---
        fig.text(
            lm + total_w / 2,
            bm * 0.35,
            "Wavenumber (cm⁻¹)",
            ha="center",
            va="center",
            fontsize=fs_label,
            fontfamily="sans-serif",
        )

        # --- Apply axis limits (set_xlim(high, low) produces IR-inverted axis) ---
        ax_hi.set_xlim(plot_x_hi, split_at)
        ax_lo.set_xlim(split_at, plot_x_lo)
        ax_hi.set_ylim(bottom=y_min, top=y_max)
        ax_lo.set_ylim(bottom=y_min, top=y_max)

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
        split_at: float | None = 2000.0,
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
            split_at: When not None and within the x range, render split axis.
        """
        png_bytes = self.render_to_bytes(
            wavenumbers,
            intensities,
            peaks,
            dpi=dpi,
            y_unit=y_unit,
            is_dip_spectrum=is_dip_spectrum,
            split_at=split_at,
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
