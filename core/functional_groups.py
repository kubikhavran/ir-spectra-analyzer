"""Functional-group knowledge base and scoring result models."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FunctionalGroupBand:
    """One diagnostic spectral band used for functional-group scoring."""

    id: str
    label: str
    range_min: float
    range_max: float
    expected_intensity: str
    shape: str
    role: str = "supporting"
    weight: float = 1.0
    reliability: float = 1.0
    channel: str = "sharp_corrected"
    suggested_preset_names: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()

    @property
    def center(self) -> float:
        return (self.range_min + self.range_max) / 2.0

    @property
    def span(self) -> float:
        return self.range_max - self.range_min

    def covers_wavenumber(self, wavenumber: float) -> bool:
        return self.range_min <= wavenumber <= self.range_max


@dataclass(frozen=True)
class FunctionalGroupCoherenceRule:
    """Bonus rule for mutually reinforcing diagnostic bands."""

    band_ids: tuple[str, ...]
    bonus: float
    threshold: float = 0.45
    label: str = ""


@dataclass(frozen=True)
class FunctionalGroupDefinition:
    """Knowledge-base entry for a functional group."""

    id: str
    name: str
    color: str
    bands: tuple[FunctionalGroupBand, ...]
    coherence_rules: tuple[FunctionalGroupCoherenceRule, ...] = ()
    source_refs: tuple[str, ...] = ()
    summary: str = ""


@dataclass(frozen=True)
class FunctionalGroupKnowledgeBase:
    """Loaded functional-group knowledge base."""

    version: int
    sources: dict[str, str]
    groups: tuple[FunctionalGroupDefinition, ...]


@dataclass(frozen=True)
class DiagnosticBandMatch:
    """Observed evidence for one diagnostic band."""

    band_id: str
    label: str
    range_min: float
    range_max: float
    role: str
    confidence: float
    presence: float
    intensity_match: float
    shape_match: float
    center_fit: float
    matched_wavenumber: float | None
    matched_intensity: float
    expected_intensity: str
    observed_intensity_class: str
    color: str
    suggested_preset_names: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    source_links: tuple[str, ...] = ()

    def covers_wavenumber(self, wavenumber: float) -> bool:
        return self.range_min <= wavenumber <= self.range_max

    @property
    def is_assignable(self) -> bool:
        return self.confidence >= 35.0 and bool(self.suggested_preset_names)

    @property
    def is_missing_required(self) -> bool:
        return self.role == "required" and self.confidence < 40.0

    @property
    def is_confirmed(self) -> bool:
        return self.confidence >= 55.0

    @property
    def evidence_label(self) -> str:
        if self.is_missing_required:
            return "Missing"
        if self.is_confirmed:
            return "Matched"
        if self.confidence >= 35.0:
            return "Weak"
        return "Absent"


@dataclass(frozen=True)
class FunctionalGroupScore:
    """Ranked scoring result for one functional group."""

    group_id: str
    group_name: str
    color: str
    score: float
    summary: str
    bands: tuple[DiagnosticBandMatch, ...]
    matched_bonus_labels: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    source_links: tuple[str, ...] = ()

    @property
    def suggested_bands(self) -> tuple[DiagnosticBandMatch, ...]:
        return tuple(
            band for band in self.bands if band.confidence >= 35.0 and band.suggested_preset_names
        )

    @property
    def matched_bands(self) -> tuple[DiagnosticBandMatch, ...]:
        return tuple(band for band in self.bands if band.is_confirmed)

    @property
    def missing_bands(self) -> tuple[DiagnosticBandMatch, ...]:
        return tuple(band for band in self.bands if band.is_missing_required)

    @property
    def supporting_bands(self) -> tuple[DiagnosticBandMatch, ...]:
        return tuple(
            band
            for band in self.bands
            if not band.is_missing_required and not band.is_confirmed and band.confidence >= 35.0
        )


@dataclass(frozen=True)
class FunctionalGroupAnalysis:
    """Complete analysis result for one spectrum."""

    results: tuple[FunctionalGroupScore, ...] = field(default_factory=tuple)
