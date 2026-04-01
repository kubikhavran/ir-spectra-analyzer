"""
SpectrumRenderer — Statický render spektra pro PDF.

Zodpovědnost:
- Renderování publication-quality spektra pomocí Matplotlib
- Anotace peaků v statickém obrázku
- Export jako PNG pro vložení do PDF

Poznámka: Matplotlib je použit zde (nikoliv PyQtGraph) protože
ReportLab vyžaduje statický rastrový/vektorový obrázek.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from core.peak import Peak


class SpectrumRenderer:
    """Renders IR spectrum as a static Matplotlib figure for PDF embedding."""

    def render_to_file(
        self,
        wavenumbers: np.ndarray,
        intensities: np.ndarray,
        peaks: list[Peak],
        output_path: Path,
        dpi: int = 300,
    ) -> None:
        """Render spectrum with peak annotations to PNG file.

        Args:
            wavenumbers: X-axis data.
            intensities: Y-axis data.
            peaks: List of peaks to annotate.
            output_path: Destination PNG file.
            dpi: Output resolution.
        """
        import matplotlib.pyplot as plt  # noqa: PLC0415

        fig, ax = plt.subplots(figsize=(10, 4))
        ax.plot(wavenumbers, intensities, "k-", linewidth=0.8)
        ax.set_xlabel("Wavenumber (cm⁻¹)")
        ax.set_ylabel("Absorbance")
        ax.invert_xaxis()
        ax.set_title("IR Spectrum")

        for peak in peaks:
            ax.annotate(
                f"{peak.position:.0f}",
                xy=(peak.position, peak.intensity),
                xytext=(0, 10),
                textcoords="offset points",
                ha="center",
                fontsize=7,
            )

        fig.tight_layout()
        fig.savefig(output_path, dpi=dpi)
        plt.close(fig)
