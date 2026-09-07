"""
YUnitCheck — Ověření, že deklarovaná Y jednotka odpovídá naměřeným datům.

Zodpovědnost:
- Z čísel odvodit, na jaké škále spektrum leží (%-škála vs. absorbance)
- Porovnat odvozené s tím, co o sobě tvrdí soubor, a nesoulad pojmenovat
- Rozhodnout, jestli se absorpční pásy kreslí jako propady dolů

Architektonické pravidlo:
  Čistě funkcionální. Vstup: numpy array. Výstup: hodnoty, žádný stav.

Proč to existuje:
  Hlavičky SPA souborů lžou. OMNIC zapisuje jednotku do historie a analytik ji
  cestou několikrát přepne; když se do souboru nedostane poslední přepnutí,
  spektrum se v %T tváří jako absorbance — jiná osa, pásy nahoru místo dolů a
  rozházené popisky peaků. Tenhle modul je poslední pojistka: čísla nelžou,
  a spektrum v %T vypadá úplně jinak než spektrum v absorbanci.

  Každá redukce je proto ``nan``-aware. OMNIC umí část spektra „blanknout"
  (funkce Blank, typicky pásmo rozpouštědla) a tyhle body přijdou jako NaN.
  Obyčejné ``np.min``/``np.median`` na nich vrátí NaN, každé porovnání s NaN je
  False a celá pojistka tiše propadne — přesně tak se JUS251-SE.SPA dostalo do
  aplikace jako absorbance.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from core.spectrum import SpectralUnit

# ── Meze pro rozpoznání škály (infer_y_unit) ─────────────────────────────────
# Absorbance se u reálných vzorků drží pod ~3; strop 10 nechává rezervu i na
# saturované pásy, a pořád je řádově pod %-škálou.
_ABSORBANCE_MAX = 10.0
_ABSORBANCE_MIN = -1.0
# %-škála: baseline u 100, pásy dolů. Dolní mez 20 je schválně vysoko nad
# stropem absorbance, aby se ty dvě rodiny nemohly potkat. Spodní hranice je
# volná, protože přeodečtené spektrum umí spadnout hluboko pod nulu a pořád
# je to %T (BST94-Be.SPA jde na -15).
_PERCENT_MIN_TOP = 20.0
_PERCENT_MAX_TOP = 130.0
_PERCENT_MIN_BOTTOM = -25.0

# ── Meze pro tvar křivky (is_dip_shaped) ─────────────────────────────────────
# Vlastní sada: tohle nerozhoduje o jednotce, ale o tom, kam se kreslí popisky
# peaků, a je odladěná na laboratorní knihovně.
_DIP_MIN_TOP = 5.0
_DIP_MAX_TOP = 120.0
_DIP_MIN_BOTTOM = -5.0
# O kolik musí propady převážit nad výstupky, aby se křivka četla jako %T.
_DIP_DOMINANCE = 1.25

# Jednotky, které leží na %-škále a kreslí se jako propady dolů.
_PERCENT_FAMILY = frozenset(
    {SpectralUnit.TRANSMITTANCE, SpectralUnit.REFLECTANCE, SpectralUnit.SINGLE_BEAM}
)
_ABSORBANCE_FAMILY = frozenset({SpectralUnit.ABSORBANCE})


@dataclass(frozen=True)
class YUnitCheck:
    """Co o jednotce tvrdí soubor, co říkají čísla, a co z toho aplikace použije."""

    declared: SpectralUnit
    inferred: SpectralUnit | None
    trusted: SpectralUnit
    is_dip: bool
    warning: str

    @property
    def agrees(self) -> bool:
        """True když data deklarované jednotce neodporují."""
        return not self.warning


@dataclass(frozen=True)
class _Profile:
    """Tvar křivky ve třech číslech, spočítaný jen z konečných bodů."""

    low: float
    high: float
    median: float


def _profile(intensities: np.ndarray) -> _Profile | None:
    """Min, max a medián přes konečné body; None když žádné nejsou.

    Blanknutá pásma (NaN) i ±inf se sem nedostanou — jsou to díry v datech,
    ne hodnoty, a jediné jejich započítání otráví celý výsledek.
    """
    values = np.asarray(intensities, dtype=float)
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return None
    return _Profile(
        low=float(finite.min()),
        high=float(finite.max()),
        median=float(np.median(finite)),
    )


def infer_y_unit(intensities: np.ndarray) -> SpectralUnit | None:
    """Na jaké škále spektrum leží podle samotných čísel.

    Vrací ``TRANSMITTANCE`` pro %-škálu, ``ABSORBANCE`` pro absorbanci a None
    když se to z hodnot poznat nedá. ``TRANSMITTANCE`` tu zastupuje celou
    %-rodinu — %R a single beam vypadají stejně, rozliší je jen hlavička.
    """
    profile = _profile(intensities)
    if profile is None:
        return None
    if profile.high <= _ABSORBANCE_MAX and profile.low >= _ABSORBANCE_MIN:
        return SpectralUnit.ABSORBANCE
    if _PERCENT_MIN_TOP < profile.high <= _PERCENT_MAX_TOP and profile.low > _PERCENT_MIN_BOTTOM:
        return SpectralUnit.TRANSMITTANCE
    return None


def is_dip_shaped(intensities: np.ndarray, declared: SpectralUnit) -> bool:
    """True když se absorpční pásy mají kreslit jako propady dolů.

    Deklarovaná jednotka rozhoduje, pokud je z %-rodiny. U souboru, který se
    hlásí jako absorbance, rozhodnou čísla: mnoho souborů v laboratorní
    knihovně nese %T křivku pod hlavičkou „Absorbance".
    """
    if declared in _PERCENT_FAMILY:
        return True

    profile = _profile(intensities)
    if profile is None:
        return False

    if declared == SpectralUnit.BASELINE_CORRECTED:
        # Zkorigované %T: baseline u nuly, pásy jako záporné propady.
        return profile.low < -5.0 and profile.high <= 5.0

    if profile.high <= _DIP_MIN_TOP or profile.low < _DIP_MIN_BOTTOM or profile.high > _DIP_MAX_TOP:
        return False
    lower_drop = profile.median - profile.low
    upper_headroom = profile.high - profile.median
    return lower_drop > upper_headroom * _DIP_DOMINANCE


def check_y_unit(intensities: np.ndarray, declared: SpectralUnit) -> YUnitCheck:
    """Porovnat deklarovanou jednotku s tvarem dat.

    ``trusted`` je jednotka, kterou má aplikace ukázat: deklarovaná, dokud jí
    data neodporují. Nesoulad se nikdy neopravuje potichu — ``warning`` je
    věta pro analytika, protože špatná jednotka znamená obrácené pásy i
    posunuté popisky peaků, a to je lepší vidět než uhodnout.
    """
    inferred = infer_y_unit(intensities)
    trusted = declared
    warning = ""

    if inferred is not None and not _same_family(inferred, declared):
        trusted = inferred
        warning = (
            f"file declares {declared.value}, but the values look like "
            f"{inferred.value} — showing {trusted.value}"
        )

    return YUnitCheck(
        declared=declared,
        inferred=inferred,
        trusted=trusted,
        is_dip=is_dip_shaped(intensities, declared),
        warning=warning,
    )


def _same_family(inferred: SpectralUnit, declared: SpectralUnit) -> bool:
    """True když odvozená škála sedí na deklarovanou jednotku.

    %R a single beam leží na téže %-škále jako %T, takže je odvození nemá čím
    rozlišit a nesmí je „opravovat" na transmitanci. Baseline-corrected data
    nemají svou vlastní škálu vůbec.
    """
    if declared == SpectralUnit.BASELINE_CORRECTED:
        return True
    if inferred == SpectralUnit.TRANSMITTANCE:
        return declared in _PERCENT_FAMILY
    return declared in _ABSORBANCE_FAMILY
