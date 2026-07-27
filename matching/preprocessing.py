"""
MatchingPreprocessing — Preprocessing pro spectral matching.

Zodpovědnost:
- Normalizace a resampling spektra před porovnáváním
- Zajišťuje, že všechna porovnávaná spektra mají stejnou osu

Proč komprese intenzity a rozmazání pásů (v0.22.0):
Spektrum se normalizuje svým nejsilnějším pásem. Když analyt nese jeden velmi
silný pás, který reference nemá (typicky azid ~2100 cm⁻¹), vydělí se tím pásem
i všechny sdílené pásy a dvě jinak shodná spektra skončí v jiném měřítku.
Na reálném páru PAR1706-HA (N₃) vs PAR1507-MK (OMe) to dávalo 47 % a 67. místo
z 201 referencí. Komprese intenzity to vrací na 77 % a 8. místo; derivační
kanál se navíc ukázal jako čistě škodlivý (na posun pásů o jednotky cm⁻¹
reagoval ztrátou ~20 bodů), proto je nahrazen mírným rozmazáním pásů.
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.signal import savgol_filter

from processing.interpolation import resample

# Exponent applied to the peak-normalized signal. Values below 1 compress the
# dynamic range, so one dominant band cannot swamp the shared fingerprint.
INTENSITY_COMPRESSION = 1.0 / 3.0
# Gaussian band broadening applied before comparison, in cm⁻¹. Makes the metric
# tolerant of the few-cm⁻¹ shifts a substituent change causes.
BAND_BLUR_SIGMA_CM = 6.0
# Skeleton region: substituent changes add and remove bands mostly above it,
# so scoring it separately identifies "same compound, different group".
FINGERPRINT_RANGE = (400.0, 1600.0)


def prepare_for_matching(
    wavenumbers: np.ndarray,
    intensities: np.ndarray,
    target_axis: np.ndarray,
    y_unit: object | None = None,
    *,
    region: tuple[float, float] | None = None,
) -> np.ndarray:
    """Preprocess spectrum for database matching.

    Resamples to a common axis, aligns spectral polarity, compresses the
    intensity range, and broadens bands so the metric tolerates small shifts.

    Args:
        wavenumbers: Original X-axis.
        intensities: Original intensities.
        target_axis: Common wavenumber axis for matching.
        y_unit: Optional spectral intensity unit used to align transmittance-like
            spectra with absorbance-like spectra before matching.
        region: Optional (min, max) wavenumber window to score on its own; the
            vector is renormalized over the window, so a region score is not
            diluted by the rest of the spectrum.

    Returns:
        Unit-normalized feature vector suitable for cosine similarity.
    """
    signal = resample(wavenumbers, intensities, target_axis).astype(np.float64, copy=False)
    signal = np.nan_to_num(signal, nan=0.0, posinf=0.0, neginf=0.0)

    sig_min = float(np.nanmin(signal))
    sig_max = float(np.nanmax(signal))
    _is_corrected_t = sig_min < -5.0 and sig_max <= 5.0  # corrected %T has negative dips

    if _is_transmittance_like(y_unit) or _is_corrected_t:
        signal = float(np.nanmax(signal)) - signal
    else:
        signal = signal - float(np.nanmin(signal))

    window = _matching_window_length(signal.size)
    if window is not None:
        baseline = savgol_filter(signal, window_length=window, polyorder=3, mode="interp")
        signal = signal - baseline

    signal = np.clip(signal, 0.0, None)
    peak = float(np.nanmax(signal))
    if peak > 0.0:
        signal = signal / peak

    signal = np.power(signal, INTENSITY_COMPRESSION)

    step = _axis_step(target_axis)
    if step > 0.0:
        sigma_samples = BAND_BLUR_SIGMA_CM / step
        if sigma_samples >= 0.5:
            signal = gaussian_filter1d(signal, sigma=sigma_samples, mode="nearest")

    if region is not None:
        lo, hi = min(region), max(region)
        mask = (target_axis >= lo) & (target_axis <= hi)
        if mask.any():
            signal = signal[mask]

    norm = float(np.linalg.norm(signal))
    if norm > 0.0:
        return signal / norm
    return signal


def _axis_step(target_axis: np.ndarray) -> float:
    """Return the grid spacing in cm⁻¹, or 0.0 for an axis too short to tell."""
    if target_axis.size < 2:
        return 0.0
    return float(abs(target_axis[1] - target_axis[0]))


def _is_transmittance_like(y_unit: object | None) -> bool:
    """Return True for spectral units where absorptions appear as dips."""
    text = getattr(y_unit, "value", y_unit)
    if text is None:
        return False
    return str(text) in {"Transmittance", "Reflectance", "Single Beam"}


def _matching_window_length(n_points: int) -> int | None:
    """Pick a stable Savitzky-Golay window length for baseline suppression."""
    if n_points < 7:
        return None
    window = min(n_points, 151)
    if window % 2 == 0:
        window -= 1
    if window < 7:
        return None
    return window
