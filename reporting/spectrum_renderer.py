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
- Thin black spectrum line (see `_SPECTRUM_LINEWIDTH`)
- Peak labels: short vertical line from apex + rotated wavenumber text above
- Sans-serif font throughout
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import TYPE_CHECKING, cast

import numpy as np
from matplotlib import colors as mcolors

from core.peak import Peak
from core.spectrum import SpectralUnit
from file_io.atomic_output import atomic_output_path

if TYPE_CHECKING:  # heavy Matplotlib imports stay out of the runtime path
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure

    from core.functional_groups import DiagnosticBandMatch

# Approximate tick spacing used by OMNIC
_WN_MAJOR_STEP = 500.0  # cm⁻¹
_WN_MINOR_STEP = 100.0  # cm⁻¹

# Split-axis width ratios (hi-wavenumber : fingerprint)
_HI_RATIO = 35
_LO_RATIO = 65

# Spectrum curve stroke width in points. Deliberately finer than the 0.8 pt
# axis frame so printed narrow bands stay resolvable.
_SPECTRUM_LINEWIDTH = 0.55

# Tick font size the split-axis inch margins were tuned against — the size the
# framed page-1 spectrum renders at. Larger figures scale the margins up from here.
_MARGIN_TICK_SIZE = 11.0

# Occupancy grid used to locate free space inside the plot for a floating
# annotation block (full-bleed layout). Resolution is a compromise between
# accuracy and the cost of the pure-Python maximal-rectangle scan.
_GRID_NX = 220
_GRID_NY = 150

# Desired annotation block size as a fraction of the figure (width, height).
_ANNOTATION_TARGET = (0.26, 0.40)

# Bounded y-range expansions tried when the plot has no room for the block.
# 1.0 = leave the spectrum exactly as-is.
_ANNOTATION_Y_EXPANSIONS = (1.0, 1.15, 1.30)


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
        label_placements: dict[int, tuple[float, float]] | None = None,
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
        return self._render(
            wavenumbers,
            intensities,
            peaks,
            dpi=dpi,
            y_unit=y_unit,
            is_dip_spectrum=is_dip_spectrum,
            figsize=figsize,
            x_min=x_min,
            x_max=x_max,
            y_view_range=y_view_range,
            diagnostic_regions=diagnostic_regions,
            split_at=split_at,
            label_placements=label_placements,
        )[0]

    def render_with_annotation_box(
        self,
        wavenumbers: np.ndarray,
        intensities: np.ndarray,
        peaks: list[Peak],
        *,
        dpi: int = 150,
        y_unit: SpectralUnit = SpectralUnit.ABSORBANCE,
        is_dip_spectrum: bool = False,
        figsize: tuple[float, float] = (7.5, 3.2),
        x_min: float = 400.0,
        x_max: float = 3800.0,
        y_view_range: tuple[float, float] | None = None,
        diagnostic_regions: tuple[object, ...] | list[object] = (),
        split_at: float | None = 2000.0,
        label_placements: dict[int, tuple[float, float]] | None = None,
        annotation_target: tuple[float, float] = _ANNOTATION_TARGET,
    ) -> tuple[bytes, tuple[float, float, float, float] | None]:
        """Render the spectrum and locate a free rectangle for a floating annotation.

        Same output as :meth:`render_to_bytes`, plus the largest empty area found
        inside the plot, expressed as ``(x0, y0, x1, y1)`` in figure fractions with
        y measured from the bottom — ready to be mapped onto a PDF page.

        The spectrum itself is never scaled down for the block. Only when the plot
        offers no usable gap at all is the y-range stretched (bounded by
        ``_ANNOTATION_Y_EXPANSIONS``) so a readable block still fits.

        Returns:
            (PNG bytes, box in figure fractions) — box is None when nothing fits.
        """
        return self._render(
            wavenumbers,
            intensities,
            peaks,
            dpi=dpi,
            y_unit=y_unit,
            is_dip_spectrum=is_dip_spectrum,
            figsize=figsize,
            x_min=x_min,
            x_max=x_max,
            y_view_range=y_view_range,
            diagnostic_regions=diagnostic_regions,
            split_at=split_at,
            label_placements=label_placements,
            annotation_target=annotation_target,
        )

    def _render(
        self,
        wavenumbers: np.ndarray,
        intensities: np.ndarray,
        peaks: list[Peak],
        *,
        dpi: int = 150,
        y_unit: SpectralUnit = SpectralUnit.ABSORBANCE,
        is_dip_spectrum: bool = False,
        figsize: tuple[float, float] = (7.5, 3.2),
        x_min: float = 400.0,
        x_max: float = 3800.0,
        y_view_range: tuple[float, float] | None = None,
        diagnostic_regions: tuple[object, ...] | list[object] = (),
        split_at: float | None = 2000.0,
        label_placements: dict[int, tuple[float, float]] | None = None,
        annotation_target: tuple[float, float] | None = None,
    ) -> tuple[bytes, tuple[float, float, float, float] | None]:
        """Render the spectrum, optionally reporting a free area for an annotation."""
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
            label_placements=label_placements,
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
                label_placements=label_placements,
                annotation_target=annotation_target,
            )

        # ── Single-axis (original) rendering ──────────────────────────────────
        fig, ax = plt.subplots(figsize=figsize)
        fig.patch.set_facecolor("white")
        ax.set_facecolor("white")

        if diagnostic_regions:
            for raw_region in diagnostic_regions:
                region = cast("DiagnosticBandMatch", raw_region)
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
            wavenumbers,
            intensities,
            color="black",
            linewidth=_SPECTRUM_LINEWIDTH,
            antialiased=True,
            zorder=1.0,
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
                label_x, label_y = self._resolve_label_position(
                    peak,
                    data_y_span=data_y_span,
                    is_dip_spectrum=is_dip_spectrum,
                    label_placements=label_placements,
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

        annotation_box = None
        if annotation_target is not None:
            annotation_box = self._resolve_annotation_box(
                fig=fig,
                panels=[(ax, _plot_x_lo, _plot_x_hi)],
                wavenumbers=wavenumbers,
                intensities=intensities,
                peaks=peaks,
                is_dip_spectrum=is_dip_spectrum,
                expand_down=_is_dip,
                fs_peak=_fs_peak,
                y_lo=_y_min,
                y_hi=_y_max,
                label_placements=label_placements,
                target=annotation_target,
            )

        buf = io.BytesIO()
        try:
            fig.savefig(buf, format="png", dpi=dpi, facecolor="white")
        finally:
            plt.close(fig)
        buf.seek(0)
        return buf.read(), annotation_box

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
        label_placements: dict[int, tuple[float, float]] | None = None,
        annotation_target: tuple[float, float] | None = None,
    ) -> tuple[bytes, tuple[float, float, float, float] | None]:
        """Render spectrum using a split-axis layout (hi-wavenumber | fingerprint).

        Uses add_axes with manually computed figure-fraction positions so that
        tight_layout / GridSpec wspace interactions cannot corrupt the layout.
        """
        fig_w, fig_h = figsize
        fig = plt.figure(figsize=figsize)
        fig.patch.set_facecolor("white")

        # --- Axis geometry in figure fractions ----------------------------------
        # Fixed inch margins → figure fractions (scale with figsize automatically).
        # They were tuned for the margined page-1 frame (_MARGIN_TICK_SIZE) and only
        # grow beyond it, so a bigger figure with larger type still fits its tick
        # labels and axis titles while every existing layout stays untouched.
        _mscale = max(1.0, fs_tick / _MARGIN_TICK_SIZE)
        lm = 0.75 * _mscale / fig_w  # left  — room for Y-axis label + tick labels
        rm = 0.10 * _mscale / fig_w  # right — thin margin
        bm = 0.45 * _mscale / fig_h  # bottom — room for X-axis tick labels + label
        tm = 0.10 * _mscale / fig_h  # top   — thin margin

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
                linewidth=_SPECTRUM_LINEWIDTH,
                antialiased=True,
                zorder=1.0,
            )

        # --- Diagnostic regions ---
        if diagnostic_regions:
            for raw_region in diagnostic_regions:
                region = cast("DiagnosticBandMatch", raw_region)
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
                label_x, label_y = self._resolve_label_position(
                    peak,
                    data_y_span=data_y_span,
                    is_dip_spectrum=is_dip_spectrum,
                    label_placements=label_placements,
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

        annotation_box = None
        if annotation_target is not None:
            annotation_box = self._resolve_annotation_box(
                fig=fig,
                panels=[(ax_hi, split_at, plot_x_hi), (ax_lo, plot_x_lo, split_at)],
                wavenumbers=wavenumbers,
                intensities=intensities,
                peaks=peaks,
                is_dip_spectrum=is_dip_spectrum,
                expand_down=is_dip_spectrum or y_unit == SpectralUnit.TRANSMITTANCE,
                fs_peak=fs_peak,
                y_lo=y_min,
                y_hi=y_max,
                label_placements=label_placements,
                target=annotation_target,
            )

        buf = io.BytesIO()
        try:
            fig.savefig(buf, format="png", dpi=dpi, facecolor="white")
        finally:
            plt.close(fig)
        buf.seek(0)
        return buf.read(), annotation_box

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
        with atomic_output_path(output_path) as temp_path:
            temp_path.write_bytes(png_bytes)

    @classmethod
    def _resolve_label_position(
        cls,
        peak: Peak,
        *,
        data_y_span: float,
        is_dip_spectrum: bool,
        label_placements: dict[int, tuple[float, float]] | None,
    ) -> tuple[float, float]:
        """Prefer the exact viewer label placement; fall back to the default formula."""
        if label_placements is not None:
            placement = label_placements.get(id(peak))
            if placement is not None:
                return (float(placement[0]), float(placement[1]))
        return cls._label_position(peak, data_y_span=data_y_span, is_dip_spectrum=is_dip_spectrum)

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
        label_placements: dict[int, tuple[float, float]] | None = None,
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
                cls._resolve_label_position(
                    peak,
                    data_y_span=data_y_span,
                    is_dip_spectrum=is_dip_spectrum,
                    label_placements=label_placements,
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

    # ------------------------------------------------------------------
    # Free-area search for the floating annotation block (full-bleed layout)
    # ------------------------------------------------------------------

    @classmethod
    def _resolve_annotation_box(
        cls,
        *,
        fig: Figure,
        panels: list[tuple[Axes, float, float]],
        wavenumbers: np.ndarray,
        intensities: np.ndarray,
        peaks: list[Peak],
        is_dip_spectrum: bool,
        expand_down: bool,
        fs_peak: int,
        y_lo: float,
        y_hi: float,
        label_placements: dict[int, tuple[float, float]] | None,
        target: tuple[float, float],
    ) -> tuple[float, float, float, float] | None:
        """Find the best free rectangle, stretching the y-range only if forced to.

        Every expansion step is applied to the live axes before measuring, so the
        winning y-range is the one left on the figure when this returns.
        """
        best: tuple[float, tuple[float, float, float, float], tuple[float, float]] | None = None

        for factor in _ANNOTATION_Y_EXPANSIONS:
            lo, hi = cls._expanded_y_limits(y_lo, y_hi, factor, expand_down=expand_down)
            for ax, _, _ in panels:
                ax.set_ylim(bottom=lo, top=hi)

            found = cls._annotation_box(
                fig=fig,
                panels=panels,
                wavenumbers=wavenumbers,
                intensities=intensities,
                peaks=peaks,
                is_dip_spectrum=is_dip_spectrum,
                fs_peak=fs_peak,
                y_lo=lo,
                y_hi=hi,
                label_placements=label_placements,
                target=target,
                anchor_bottom=expand_down,
            )
            if found is not None:
                score, box = found
                if best is None or score > best[0]:
                    best = (score, box, (lo, hi))
                if score >= 0.98:
                    break

        if best is None:
            for ax, _, _ in panels:
                ax.set_ylim(bottom=y_lo, top=y_hi)
            return None

        for ax, _, _ in panels:
            ax.set_ylim(bottom=best[2][0], top=best[2][1])
        return best[1]

    @staticmethod
    def _expanded_y_limits(
        y_lo: float, y_hi: float, factor: float, *, expand_down: bool
    ) -> tuple[float, float]:
        """Grow the y-range away from the curve so an empty band appears."""
        if factor <= 1.0:
            return (y_lo, y_hi)
        extra = (y_hi - y_lo) * (factor - 1.0)
        return (y_lo - extra, y_hi) if expand_down else (y_lo, y_hi + extra)

    @classmethod
    def _annotation_box(
        cls,
        *,
        fig: Figure,
        panels: list[tuple[Axes, float, float]],
        wavenumbers: np.ndarray,
        intensities: np.ndarray,
        peaks: list[Peak],
        is_dip_spectrum: bool,
        fs_peak: int,
        y_lo: float,
        y_hi: float,
        label_placements: dict[int, tuple[float, float]] | None,
        target: tuple[float, float],
        anchor_bottom: bool,
    ) -> tuple[float, tuple[float, float, float, float]] | None:
        """Return (fit score, box) for the emptiest spot in the plot, or None.

        The box is pushed to the far edge of the gap it was found in — down for
        dip spectra, up for absorbance — so the block ends up in the corner of the
        axes rather than floating in the middle of the free area.
        """
        occupied, region = cls._occupancy_grid(
            fig=fig,
            panels=panels,
            wavenumbers=wavenumbers,
            intensities=intensities,
            peaks=peaks,
            is_dip_spectrum=is_dip_spectrum,
            fs_peak=fs_peak,
            y_lo=y_lo,
            y_hi=y_hi,
            label_placements=label_placements,
        )
        reg_x0, reg_y0, reg_x1, reg_y1 = region
        reg_w = reg_x1 - reg_x0
        reg_h = reg_y1 - reg_y0
        if reg_w <= 0 or reg_h <= 0:
            return None

        target_w, target_h = target
        target_cols = max(1.0, target_w / reg_w * _GRID_NX)
        target_rows = max(1.0, target_h / reg_h * _GRID_NY)

        found = cls._best_free_rect(~occupied, target_cols, target_rows)
        if found is None:
            return None
        score, c0, c1, r0, r1 = found

        cell_w = reg_w / _GRID_NX
        cell_h = reg_h / _GRID_NY
        # One cell of breathing room keeps the block off the curve it hugs.
        x0 = reg_x0 + (c0 + 1) * cell_w
        x1 = reg_x0 + c1 * cell_w
        y0 = reg_y0 + (r0 + 1) * cell_h
        y1 = reg_y0 + r1 * cell_h
        if x1 <= x0 or y1 <= y0:
            return None

        # Never grow past the target — a huge empty plot should not produce a
        # billboard-sized structure.
        width = min(x1 - x0, target_w)
        height = min(y1 - y0, target_h)
        box_y0 = y0 if anchor_bottom else y1 - height
        return (min(score, 1.0), (x0, box_y0, x0 + width, box_y0 + height))

    @staticmethod
    def _to_figure_x(
        values: np.ndarray | float, geometry: tuple[float, float, float, float]
    ) -> np.ndarray:
        """Map wavenumbers to figure fractions (the axis runs high → low)."""
        axis_x0, axis_width, x_lo, x_hi = geometry
        span = max(x_hi - x_lo, 1e-12)
        return axis_x0 + (x_hi - np.clip(values, x_lo, x_hi)) / span * axis_width

    @staticmethod
    def _to_figure_y(
        values: np.ndarray | float, geometry: tuple[float, float, float, float]
    ) -> np.ndarray:
        """Map intensities to figure fractions."""
        axis_y0, axis_height, y_lo, y_hi = geometry
        span = max(y_hi - y_lo, 1e-12)
        return axis_y0 + (np.clip(values, y_lo, y_hi) - y_lo) / span * axis_height

    @classmethod
    def _occupancy_grid(
        cls,
        *,
        fig: Figure,
        panels: list[tuple[Axes, float, float]],
        wavenumbers: np.ndarray,
        intensities: np.ndarray,
        peaks: list[Peak],
        is_dip_spectrum: bool,
        fs_peak: int,
        y_lo: float,
        y_hi: float,
        label_placements: dict[int, tuple[float, float]] | None,
    ) -> tuple[np.ndarray, tuple[float, float, float, float]]:
        """Mark grid cells covered by the curve, leader lines and peak labels."""
        positions = [ax.get_position() for ax, _, _ in panels]
        reg_x0 = min(pos.x0 for pos in positions)
        reg_x1 = max(pos.x1 for pos in positions)
        reg_y0 = min(pos.y0 for pos in positions)
        reg_y1 = max(pos.y1 for pos in positions)
        region = (reg_x0, reg_y0, reg_x1, reg_y1)

        occupied = np.zeros((_GRID_NY, _GRID_NX), dtype=bool)
        cell_w = (reg_x1 - reg_x0) / _GRID_NX
        cell_h = (reg_y1 - reg_y0) / _GRID_NY
        if cell_w <= 0 or cell_h <= 0:
            return occupied, region

        fig_w_pt = fig.get_figwidth() * 72.0
        fig_h_pt = fig.get_figheight() * 72.0
        data_y_span = float(np.ptp(intensities)) or 1.0

        def _col(fx: float) -> int:
            return int(np.clip((fx - reg_x0) / cell_w, 0, _GRID_NX - 1))

        def _row(fy: float) -> int:
            return int(np.clip((fy - reg_y0) / cell_h, 0, _GRID_NY - 1))

        def _mark(fx0: float, fy0: float, fx1: float, fy1: float) -> None:
            c_a, c_b = sorted((_col(fx0), _col(fx1)))
            r_a, r_b = sorted((_row(fy0), _row(fy1)))
            occupied[r_a : r_b + 1, c_a : c_b + 1] = True

        for pos, (_ax, x_lo, x_hi) in zip(positions, panels, strict=True):
            x_geometry = (float(pos.x0), float(pos.width), x_lo, x_hi)
            y_geometry = (float(pos.y0), float(pos.height), y_lo, y_hi)

            in_panel = (wavenumbers >= x_lo) & (wavenumbers <= x_hi)
            if in_panel.any():
                cols = np.clip(
                    (
                        (cls._to_figure_x(wavenumbers[in_panel], x_geometry) - reg_x0) / cell_w
                    ).astype(int),
                    0,
                    _GRID_NX - 1,
                )
                rows = np.clip(
                    (
                        (cls._to_figure_y(intensities[in_panel], y_geometry) - reg_y0) / cell_h
                    ).astype(int),
                    0,
                    _GRID_NY - 1,
                )
                col_min = np.full(_GRID_NX, _GRID_NY, dtype=int)
                col_max = np.full(_GRID_NX, -1, dtype=int)
                np.minimum.at(col_min, cols, rows)
                np.maximum.at(col_max, cols, rows)
                # Dilate by one column so steep flanks stay a connected barrier.
                span_lo = np.minimum(col_min, np.minimum(np.roll(col_min, 1), np.roll(col_min, -1)))
                span_hi = np.maximum(col_max, np.maximum(np.roll(col_max, 1), np.roll(col_max, -1)))
                for col in range(_GRID_NX):
                    if span_hi[col] >= 0:
                        occupied[max(int(span_lo[col]), 0) : int(span_hi[col]) + 1, col] = True

            for peak in peaks:
                if not x_lo <= peak.position <= x_hi:
                    continue
                label_x, label_y = cls._resolve_label_position(
                    peak,
                    data_y_span=data_y_span,
                    is_dip_spectrum=is_dip_spectrum,
                    label_placements=label_placements,
                )
                peak_fx = float(cls._to_figure_x(peak.position, x_geometry))
                peak_fy = float(cls._to_figure_y(peak.intensity, y_geometry))
                label_fx = float(cls._to_figure_x(label_x, x_geometry))
                label_fy = float(cls._to_figure_y(label_y, y_geometry))
                _mark(peak_fx, peak_fy, label_fx, label_fy)

                text = str(int(round(peak.position)))
                half_w = fs_peak * 0.75 / fig_w_pt
                length = (len(text) * 0.62 * fs_peak + 2.0) / fig_h_pt
                if label_fy <= peak_fy:
                    _mark(label_fx - half_w, label_fy - length, label_fx + half_w, label_fy)
                else:
                    _mark(label_fx - half_w, label_fy, label_fx + half_w, label_fy + length)

        # Keep the block clear of the axis frame.
        occupied[:2, :] = True
        occupied[-2:, :] = True
        occupied[:, :2] = True
        occupied[:, -2:] = True
        return occupied, region

    @staticmethod
    def _best_free_rect(
        free: np.ndarray, target_cols: float, target_rows: float
    ) -> tuple[float, int, int, int, int] | None:
        """Largest-rectangle-in-histogram scan scored by how well the target fits.

        Returns (score, col_first, col_last, row_first, row_last); the score is
        ``min(width/target_w, height/target_h)`` — 1.0 means the block fits at full
        size — with rectangle area as tie-breaker.
        """
        n_rows, n_cols = free.shape
        heights = np.zeros(n_cols, dtype=int)
        best_key: tuple[float, int] | None = None
        best: tuple[float, int, int, int, int] | None = None

        for row in range(n_rows):
            heights = np.where(free[row], heights + 1, 0)
            bar = heights.tolist()
            stack: list[tuple[int, int]] = []
            for col in range(n_cols + 1):
                current = bar[col] if col < n_cols else 0
                start = col
                while stack and stack[-1][1] >= current:
                    left, height = stack.pop()
                    start = left
                    if height <= 0:
                        continue
                    width = col - left
                    score = min(width / target_cols, height / target_rows)
                    key = (min(score, 1.0), width * height)
                    if best_key is None or key > best_key:
                        best_key = key
                        best = (score, left, col - 1, row - height + 1, row)
                stack.append((start, current))

        return best

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
