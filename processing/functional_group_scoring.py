"""Functional-group scoring over actual IR spectrum data."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import find_peaks, savgol_filter

from core.functional_groups import (
    DiagnosticBandMatch,
    FunctionalGroupAnalysis,
    FunctionalGroupBand,
    FunctionalGroupDefinition,
    FunctionalGroupScore,
)
from core.spectrum import Spectrum
from storage.functional_group_repository import FunctionalGroupRepository

_INTENSITY_TARGETS = {
    "w": 0.08,
    "m": 0.18,
    "s": 0.30,
    "vs": 0.45,
}

_INTENSITY_THRESHOLDS = {
    "w": 0.04,
    "m": 0.10,
    "s": 0.18,
    "vs": 0.28,
}

_OBSERVED_INTENSITY_CLASSES = (
    (0.40, "vs"),
    (0.24, "s"),
    (0.10, "m"),
    (0.00, "w"),
)


@dataclass(frozen=True)
class _PreparedSignal:
    wavenumbers: np.ndarray
    signal: np.ndarray
    scale: float


@dataclass(frozen=True)
class _BandMetrics:
    band: FunctionalGroupBand
    confidence_fraction: float
    presence: float
    intensity_match: float
    shape_match: float
    center_fit: float
    matched_wavenumber: float | None
    matched_intensity: float
    observed_intensity_class: str


def score_functional_groups(
    raw_spectrum: Spectrum,
    corrected_spectrum: Spectrum | None = None,
    *,
    repository: FunctionalGroupRepository | None = None,
) -> FunctionalGroupAnalysis:
    """Score common functional groups from the current spectrum."""
    repo = repository or FunctionalGroupRepository()
    knowledge_base = repo.load()

    prepared_channels = {
        "broad_raw": _prepare_broad_signal(raw_spectrum),
        "sharp_corrected": _prepare_sharp_signal(raw_spectrum, corrected_spectrum),
    }

    results: list[FunctionalGroupScore] = []
    for group in knowledge_base.groups:
        metrics = [
            _score_band(
                band,
                prepared_channels.get(band.channel, prepared_channels["sharp_corrected"]),
                group.color,
            )
            for band in group.bands
        ]
        result = _score_group(group, metrics, knowledge_base.sources)
        results.append(result)

    results.sort(key=lambda result: result.score, reverse=True)
    return FunctionalGroupAnalysis(
        results=tuple(results),
    )


def _prepare_broad_signal(spectrum: Spectrum) -> _PreparedSignal:
    wn, signal = _sorted_absorption_signal(spectrum)
    signal = np.clip(signal - np.percentile(signal, 5), 0.0, None)
    scale = max(float(np.percentile(signal, 99)), 1e-6)
    return _PreparedSignal(wavenumbers=wn, signal=signal, scale=scale)


def _prepare_sharp_signal(
    raw_spectrum: Spectrum,
    corrected_spectrum: Spectrum | None,
) -> _PreparedSignal:
    if corrected_spectrum is not None:
        wn, signal = _sorted_absorption_signal(corrected_spectrum)
    else:
        wn, signal = _sorted_absorption_signal(raw_spectrum)
        window = _pick_savgol_window(signal.size)
        if window >= 7:
            baseline = savgol_filter(signal, window_length=window, polyorder=3, mode="interp")
            signal = signal - baseline
    signal = np.clip(signal - np.percentile(signal, 5), 0.0, None)
    scale = max(float(np.percentile(signal, 99)), 1e-6)
    return _PreparedSignal(wavenumbers=wn, signal=signal, scale=scale)


def _sorted_absorption_signal(spectrum: Spectrum) -> tuple[np.ndarray, np.ndarray]:
    wn = np.asarray(spectrum.wavenumbers, dtype=float)
    signal = np.asarray(spectrum.intensities, dtype=float)
    if wn.size >= 2 and wn[0] > wn[-1]:
        wn = wn[::-1]
        signal = signal[::-1]

    if spectrum.is_dip_spectrum:
        baseline = float(np.percentile(signal, 95))
        signal = baseline - signal
    else:
        baseline = float(np.percentile(signal, 5))
        signal = signal - baseline
    return wn, np.clip(signal, 0.0, None)


def _pick_savgol_window(size: int) -> int:
    if size < 7:
        return size if size % 2 == 1 else max(size - 1, 1)
    window = min(size // 6, 301)
    window = max(window, 21)
    if window % 2 == 0:
        window += 1
    return min(window, size if size % 2 == 1 else size - 1)


def _score_band(
    band: FunctionalGroupBand,
    prepared: _PreparedSignal,
    color: str,
) -> _BandMetrics:
    mask = (prepared.wavenumbers >= band.range_min) & (prepared.wavenumbers <= band.range_max)
    segment_wn = prepared.wavenumbers[mask]
    segment_signal = prepared.signal[mask]

    if segment_signal.size == 0 or float(np.max(segment_signal)) <= 1e-9:
        return _BandMetrics(
            band=band,
            confidence_fraction=0.0,
            presence=0.0,
            intensity_match=0.0,
            shape_match=0.0,
            center_fit=0.0,
            matched_wavenumber=None,
            matched_intensity=0.0,
            observed_intensity_class="w",
        )

    local_floor = _local_floor(segment_signal, band.shape)
    segment_signal = np.clip(segment_signal - local_floor, 0.0, None)
    if float(np.max(segment_signal)) <= 1e-9:
        return _BandMetrics(
            band=band,
            confidence_fraction=0.0,
            presence=0.0,
            intensity_match=0.0,
            shape_match=0.0,
            center_fit=0.0,
            matched_wavenumber=None,
            matched_intensity=0.0,
            observed_intensity_class="w",
        )

    peak_index = _select_candidate_index(segment_wn, segment_signal, band)
    matched_wavenumber = float(segment_wn[peak_index])
    matched_intensity = float(segment_signal[peak_index])
    amp_norm = matched_intensity / prepared.scale
    area_norm = float(np.trapezoid(segment_signal, segment_wn)) / max(
        band.span * prepared.scale, 1e-6
    )

    metric_for_presence = max(amp_norm, area_norm * 1.5) if band.shape == "broad" else amp_norm
    metric_for_intensity = area_norm * 1.25 if band.shape == "broad" else amp_norm
    presence = _presence_score(metric_for_presence, band.expected_intensity)
    intensity_match = _intensity_score(metric_for_intensity, band.expected_intensity)

    width_fraction = _width_fraction(segment_wn, segment_signal, matched_intensity, band.span)
    peak_count = _count_local_peaks(segment_signal, band.span)
    shape_match = _shape_score(band.shape, width_fraction, peak_count)
    center_fit = _center_fit(matched_wavenumber, band.center, band.span)

    if band.shape == "broad":
        quality = 0.40 * intensity_match + 0.35 * shape_match + 0.25 * center_fit
        confidence_fraction = float(np.clip(presence * quality, 0.0, 1.0))
    else:
        quality = 0.45 * intensity_match + 0.30 * shape_match + 0.25 * center_fit
        # Sharp bands that only survive on the edge of a range are a common false-positive source.
        edge_gate = 0.45 + (0.55 * center_fit)
        confidence_fraction = float(np.clip(presence * quality * edge_gate, 0.0, 1.0))

    return _BandMetrics(
        band=band,
        confidence_fraction=confidence_fraction,
        presence=float(presence),
        intensity_match=float(intensity_match),
        shape_match=float(shape_match),
        center_fit=float(center_fit),
        matched_wavenumber=matched_wavenumber,
        matched_intensity=matched_intensity,
        observed_intensity_class=_observed_intensity_class(metric_for_intensity),
    )


def _presence_score(metric: float, expected_intensity: str) -> float:
    threshold = _INTENSITY_THRESHOLDS.get(expected_intensity, 0.10)
    if metric <= threshold * 0.4:
        return 0.0
    if metric >= threshold:
        return min(metric / max(threshold, 1e-6), 1.0)
    return (metric - threshold * 0.4) / max(threshold * 0.6, 1e-6)


def _intensity_score(metric: float, expected_intensity: str) -> float:
    target = _INTENSITY_TARGETS.get(expected_intensity, 0.18)
    if metric <= 1e-9:
        return 0.0
    if metric >= target:
        overshoot = min((metric - target) / max(target, 1e-6), 1.0)
        return max(0.65, 1.0 - overshoot * 0.25)
    return np.clip(metric / max(target, 1e-6), 0.0, 1.0)


def _local_floor(signal: np.ndarray, shape: str) -> float:
    percentile = 12 if shape == "broad" else 20
    return float(np.percentile(signal, percentile))


def _select_candidate_index(
    wavenumbers: np.ndarray,
    signal: np.ndarray,
    band: FunctionalGroupBand,
) -> int:
    if signal.size == 1:
        return 0

    peak_height = max(float(np.max(signal)) * 0.20, 1e-9)
    distance = max(int(signal.size / max(band.span / 18.0, 2.0)), 2)
    peaks, _props = find_peaks(signal, height=peak_height, distance=distance)
    candidates = peaks if peaks.size else np.array([int(np.argmax(signal))], dtype=int)

    max_signal = max(float(np.max(signal)), 1e-9)
    best_index = int(candidates[0])
    best_score = -1.0
    for candidate in candidates:
        candidate = int(candidate)
        prominence = float(signal[candidate]) / max_signal
        center_score = _center_fit(float(wavenumbers[candidate]), band.center, band.span)
        combined_score = 0.65 * prominence + 0.35 * center_score
        if combined_score > best_score:
            best_score = combined_score
            best_index = candidate
    return best_index


def _width_fraction(
    wavenumbers: np.ndarray,
    signal: np.ndarray,
    peak_height: float,
    span: float,
) -> float:
    if signal.size == 0 or peak_height <= 1e-9 or span <= 1e-9:
        return 0.0
    above = signal >= (peak_height * 0.35)
    if not np.any(above):
        return 0.0
    selected = wavenumbers[above]
    width = float(selected[-1] - selected[0]) if selected.size > 1 else 0.0
    return np.clip(width / span, 0.0, 1.0)


def _count_local_peaks(signal: np.ndarray, span: float) -> int:
    if signal.size < 5:
        return 1 if float(np.max(signal)) > 0 else 0
    distance = max(int(signal.size / max(span / 25.0, 2.0)), 2)
    height = max(float(np.max(signal)) * 0.35, 1e-9)
    peaks, _props = find_peaks(signal, height=height, distance=distance)
    return int(peaks.size)


def _shape_score(shape: str, width_fraction: float, peak_count: int) -> float:
    if shape == "broad":
        return float(np.clip(width_fraction / 0.28, 0.0, 1.0))
    if shape == "paired":
        if peak_count >= 2:
            count_score = 1.0
        elif peak_count == 1:
            count_score = 0.2
        else:
            count_score = 0.0
        if width_fraction < 0.12:
            width_score = width_fraction / 0.12
        elif width_fraction <= 0.92:
            width_score = 1.0
        else:
            width_score = max(0.0, 1.0 - ((width_fraction - 0.92) / 0.30))
        return float(np.clip(0.8 * count_score + 0.2 * width_score, 0.0, 1.0))
    if shape == "doublet":
        if peak_count == 2:
            return 1.0
        if peak_count >= 3:
            return 0.6
        return 0.3 if peak_count == 1 else 0.0
    target_max = 0.38
    if width_fraction <= target_max:
        return 1.0
    return float(max(0.0, 1.0 - ((width_fraction - target_max) / 0.55)))


def _center_fit(center: float, expected_center: float, span: float) -> float:
    if span <= 1e-9:
        return 1.0
    distance = abs(center - expected_center)
    return float(max(0.0, 1.0 - (distance / (span / 2.0))))


def _observed_intensity_class(metric: float) -> str:
    for threshold, label in _OBSERVED_INTENSITY_CLASSES:
        if metric >= threshold:
            return label
    return "w"


def _score_group(
    group: FunctionalGroupDefinition,
    metrics: list[_BandMetrics],
    source_lookup: dict[str, str],
) -> FunctionalGroupScore:
    positive_total = 0.0
    penalty_total = 0.0
    bonus_total = 0.0
    max_positive_total = 0.0
    max_bonus_total = sum(rule.bonus for rule in group.coherence_rules)
    band_metrics_by_id: dict[str, _BandMetrics] = {}
    band_matches: list[DiagnosticBandMatch] = []

    for metric in metrics:
        band = metric.band
        weight = band.weight * band.reliability
        if band.role != "exclusion":
            max_positive_total += weight
            positive_total += weight * metric.confidence_fraction
        band_metrics_by_id[band.id] = metric

        if band.role == "required" and metric.confidence_fraction < 0.40:
            penalty_total += weight * ((0.40 - metric.confidence_fraction) / 0.40)
        elif band.role == "exclusion" and metric.confidence_fraction > 0.55:
            penalty_total += weight * metric.confidence_fraction * 0.85

        band_matches.append(
            DiagnosticBandMatch(
                band_id=band.id,
                label=band.label,
                range_min=band.range_min,
                range_max=band.range_max,
                role=band.role,
                confidence=round(metric.confidence_fraction * 100.0, 1),
                presence=round(metric.presence, 3),
                intensity_match=round(metric.intensity_match, 3),
                shape_match=round(metric.shape_match, 3),
                center_fit=round(metric.center_fit, 3),
                matched_wavenumber=metric.matched_wavenumber,
                matched_intensity=metric.matched_intensity,
                expected_intensity=band.expected_intensity,
                observed_intensity_class=metric.observed_intensity_class,
                color=group.color,
                suggested_preset_names=band.suggested_preset_names,
                source_refs=band.source_refs,
                source_links=_resolve_source_links(band.source_refs, source_lookup),
            )
        )

    matched_bonus_labels: list[str] = []
    for rule in group.coherence_rules:
        if all(
            _supports_coherence(band_metrics_by_id.get(band_id), rule.threshold)
            for band_id in rule.band_ids
        ):
            bonus_total += rule.bonus
            matched_bonus_labels.append(rule.label)

    raw_score = positive_total + bonus_total - penalty_total
    max_score = max(max_positive_total + max_bonus_total, 1e-6)
    score_pct = round(float(np.clip(raw_score / max_score, 0.0, 1.0) * 100.0), 1)

    strong_labels = [
        match.label
        for match in band_matches
        if match.confidence >= 55.0 and match.role != "exclusion"
    ]
    summary = ", ".join(strong_labels[:2]) if strong_labels else group.summary or "Weak evidence"

    band_matches.sort(key=lambda match: (match.confidence, match.range_max), reverse=True)

    return FunctionalGroupScore(
        group_id=group.id,
        group_name=group.name,
        color=group.color,
        score=score_pct,
        summary=summary,
        bands=tuple(band_matches),
        matched_bonus_labels=tuple(matched_bonus_labels),
        source_refs=group.source_refs,
        source_links=_resolve_source_links(group.source_refs, source_lookup),
    )


def _supports_coherence(metric: _BandMetrics | None, threshold: float) -> bool:
    if metric is None or metric.confidence_fraction < threshold:
        return False
    if metric.band.shape == "broad":
        return metric.center_fit >= 0.25 or metric.shape_match >= 0.35
    return metric.center_fit >= 0.20 or metric.shape_match >= 0.35


def _resolve_source_links(source_refs: tuple[str, ...], source_lookup: dict[str, str]) -> tuple[str, ...]:
    links: list[str] = []
    for ref in source_refs:
        resolved = source_lookup.get(ref)
        if resolved and resolved not in links:
            links.append(resolved)
    return tuple(links)
