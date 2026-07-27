"""
BandDifference — Porovnání pásů dvou spekter.

Zodpovědnost:
- Které pásy má vzorek navíc a které mu naproti referenci chybí
- Podklad pro rozhodnutí "stejný skelet, jiný substituent"

Architektonické pravidlo:
  Čistě funkcionální — vstup: Spectrum objekty, výstup: dataclass. Žádný stav.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from processing.peak_detection import default_prominence, detect_peaks

# Two bands are treated as the same band when their positions differ by less
# than this. A substituent swap shifts skeleton bands by a few cm⁻¹.
DEFAULT_MATCH_TOLERANCE_CM = 8.0


@dataclass(frozen=True)
class DifferingBand:
    """One band present in a single spectrum of the compared pair."""

    position: float
    prominence: float


@dataclass(frozen=True)
class BandComparison:
    """Which bands the two spectra do not share."""

    only_in_query: tuple[DifferingBand, ...]
    only_in_reference: tuple[DifferingBand, ...]
    shared_count: int
    query_band_count: int
    reference_band_count: int

    def summary(self, *, max_bands: int = 3) -> str:
        """One-line, human-readable difference summary for the results panel."""
        if not self.query_band_count or not self.reference_band_count:
            return ""

        def _bands(bands: tuple[DifferingBand, ...]) -> str:
            return ", ".join(f"{band.position:.0f}" for band in bands[:max_bands])

        parts = [f"{self.shared_count} shared bands"]
        if self.only_in_query:
            parts.append(f"only in sample: {_bands(self.only_in_query)} cm⁻¹")
        if self.only_in_reference:
            parts.append(f"only in reference: {_bands(self.only_in_reference)} cm⁻¹")
        return " · ".join(parts)


def compare_bands(
    query_spectrum,
    reference_spectrum,
    *,
    tolerance: float = DEFAULT_MATCH_TOLERANCE_CM,
) -> BandComparison:
    """Compare the detected bands of two spectra, strongest difference first.

    Positions with no counterpart within ``tolerance`` are reported as differing.
    Prominence is measured against the spectrum's own median level, so the two
    spectra stay comparable even when their absolute scales differ.
    """
    query_bands = _detected_bands(query_spectrum)
    reference_bands = _detected_bands(reference_spectrum)
    return BandComparison(
        only_in_query=_unmatched(query_bands, reference_bands, tolerance),
        only_in_reference=_unmatched(reference_bands, query_bands, tolerance),
        shared_count=sum(
            1
            for band in query_bands
            if any(abs(band.position - other.position) <= tolerance for other in reference_bands)
        ),
        query_band_count=len(query_bands),
        reference_band_count=len(reference_bands),
    )


def _detected_bands(spectrum) -> tuple[DifferingBand, ...]:
    """Detect bands and rate each by how far it stands out from the median level."""
    if spectrum is None or spectrum.wavenumbers.size == 0:
        return ()
    peaks = detect_peaks(
        spectrum.wavenumbers,
        spectrum.intensities,
        invert=spectrum.is_dip_spectrum,
        prominence=default_prominence(spectrum),
    )
    level = float(np.median(spectrum.intensities))
    return tuple(
        DifferingBand(position=float(peak.position), prominence=abs(level - peak.intensity))
        for peak in peaks
    )


def _unmatched(
    bands: tuple[DifferingBand, ...],
    others: tuple[DifferingBand, ...],
    tolerance: float,
) -> tuple[DifferingBand, ...]:
    """Return bands with no counterpart in ``others``, most prominent first."""
    missing = [
        band
        for band in bands
        if not any(abs(band.position - other.position) <= tolerance for other in others)
    ]
    return tuple(sorted(missing, key=lambda band: band.prominence, reverse=True))
