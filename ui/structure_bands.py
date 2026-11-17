"""Where the groups of the drawn structure show up in the spectrum.

The groups found in a structure (``chemistry.structure_motifs``) each get a
colour, used both for their section in the Vibrations panel and for their
lane of bands at the top of the spectrum, so the two can be read together.
"""

from __future__ import annotations

from dataclasses import dataclass

from chemistry.structure_motifs import FoundMotif
from core.vibration_presets import VibrationPreset

# Distinct hues that read on both the light and the dark plot background.
_PALETTE = (
    "#E4572E",
    "#2E86AB",
    "#A23B72",
    "#3BB273",
    "#F1A208",
    "#7768AE",
    "#17BEBB",
    "#D7263D",
    "#8D6A9F",
    "#4D9078",
    "#C17C74",
    "#5C80BC",
)

# Skeleton groups every organic molecule has: listed in the panel, but drawn
# as lanes they would only crowd the plot.
_NO_LANE = frozenset({"methyl", "methylene", "methine", "long_chain"})


@dataclass(frozen=True)
class StructureBand:
    """One vibration window of one group of the drawn structure."""

    motif_id: str
    group: str
    vibration: str
    low: float
    high: float
    color: str
    lane: int


def motif_colors(found: list[FoundMotif]) -> dict[str, str]:
    """A stable colour per found group (in the order they are listed)."""
    return {f.id: _PALETTE[index % len(_PALETTE)] for index, f in enumerate(found)}


def presets_for(found: FoundMotif, presets: list[VibrationPreset]) -> list[VibrationPreset]:
    """The library entries of a group, highest wavenumber first."""
    names = set(found.vibrations)
    members = [preset for preset in presets if preset.answers_to(names)]
    members.sort(key=lambda p: (-p.typical_range_max, p.typical_range_min))
    return members


def structure_bands(found: list[FoundMotif], presets: list[VibrationPreset]) -> list[StructureBand]:
    """Every vibration window of the drawn structure, one lane per group."""
    colors = motif_colors(found)
    bands: list[StructureBand] = []
    lane = 0
    for motif in found:
        if motif.id in _NO_LANE:
            continue
        members = presets_for(motif, presets)
        if not members:
            continue
        for preset in members:
            low, high = sorted((float(preset.typical_range_min), float(preset.typical_range_max)))
            bands.append(
                StructureBand(
                    motif_id=motif.id,
                    group=motif.name,
                    vibration=preset.name,
                    low=low,
                    high=high,
                    color=colors[motif.id],
                    lane=lane,
                )
            )
        lane += 1
    return bands
