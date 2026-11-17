"""Does the spectrum agree with the structure the user drew?

Guessing groups from a spectrum alone is hard; checking a proposed structure
is not. When a project carries a structure, every functional group in it is
looked up in the spectrum:

* **found** — the learned model, or for groups it does not cover the group's
  required bands, support it;
* **weak** — some support, not enough to call it;
* **not seen** — the spectrum does not show it (a failed reaction, a wrong
  structure, or a band too weak to see).

Strong bands that no group of the structure explains are listed too, with
the usual suspects for that region: residual chloroform or methanol from a
cast film, water in a KBr pellet, atmospheric CO₂, or a carbonyl that should
not be there.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import find_peaks

from chemistry.functional_group_smarts import groups_in_smiles
from core.functional_groups import FunctionalGroupAnalysis, FunctionalGroupScore
from core.spectrum import Spectrum
from processing.fg_features import absorbance_profile

FOUND = "found"
WEAK = "weak"
NOT_SEEN = "not_seen"

# Not checked against a drawn structure: generic C-H, and the "how much CH2 /
# CH3" categories, which describe proportions rather than a group a chemist
# draws — a structure with two methyls is not wrong because they are faint.
_TOO_GENERIC = frozenset(
    {
        "aliphatic_hydrocarbon",
        "methyl_rich_alkyl",
        "methylene_rich_alkyl",
        "long_chain_n_alkyl",
        "isopropyl_group",
    }
)
# The model's verdict "not in the spectrum" is trusted only for groups it
# recognised well on held-out spectra (cross-validated F1) and only when it is
# clearly below its threshold; otherwise the group is reported as uncertain.
_TRUSTED_ABSENCE_F1 = 0.6
_ABSENT_SCORE = 15.0

# Bands every organic structure with C-H explains without a dedicated group.
_ALWAYS_EXPLAINED = ((2840.0, 3000.0), (1340.0, 1480.0))

# Motifs outside the group knowledge base that still explain bands of their
# own: (SMARTS, windows in cm⁻¹).
_EXTRA_MOTIFS: tuple[tuple[str, tuple[tuple[float, float], ...]], ...] = (
    ("[OX2][CX3](=O)[OX2]", ((1730.0, 1800.0), (1150.0, 1290.0))),  # carbonate
    (
        "[NX3][CX3](=O)[OX2]",
        ((1680.0, 1745.0), (1200.0, 1270.0), (3200.0, 3460.0), (1500.0, 1560.0)),
    ),
    ("[NX3][CX3](=O)[NX3]", ((1620.0, 1710.0), (3200.0, 3460.0), (1500.0, 1600.0))),  # urea
    ("[CX3](=O)[NX3][CX3](=O)", ((1680.0, 1800.0),)),  # imide
    ("[#6]F", ((1000.0, 1400.0),)),
    ("[#6]Cl", ((540.0, 850.0),)),
    ("[#6]Br", ((500.0, 700.0),)),
    ("n", ((1380.0, 1630.0),)),  # heteroaromatic ring stretches
    ("[#6]=[#7]", ((1590.0, 1690.0),)),
    ("[NX3+](=O)[O-]", ((1500.0, 1570.0), (1290.0, 1390.0))),
    ("[OX2H]", ((3150.0, 3600.0), (1000.0, 1260.0))),
    ("[#6X3]=[OX1]", ((1630.0, 1830.0),)),  # any carbonyl, also in aromatic rings
    ("[#6,#7]#[#6,#7]", ((2100.0, 2290.0),)),  # any triple bond
    ("[CX3](=O)[OX2H1]", ((2400.0, 3300.0), (880.0, 960.0))),  # acid O-H, dimer
    ("[N+,NX4]", ((2300.0, 3200.0), (1480.0, 1640.0))),  # ammonium N-H
    ("[SX2H]", ((2500.0, 2620.0),)),
    ("[#7;H1,H2]", ((3100.0, 3520.0), (1550.0, 1680.0))),
    ("[CX3]=[CX3]", ((3000.0, 3100.0), (1600.0, 1680.0), (880.0, 1000.0))),
    ("a", ((3000.0, 3110.0), (1440.0, 1630.0), (680.0, 900.0))),
)
# Below this every molecule has strong skeletal bands no group table lists, so
# an unexplained band there is only reported when it points at something
# specific (residual chloroform or methanol).
_FINGERPRINT_LIMIT = 1400.0
_GENERIC_HINT = "strong band not explained by the structure's groups"


@dataclass(frozen=True)
class GroupCheck:
    group_id: str
    group_name: str
    status: str
    score: float
    evidence_source: str
    detail: str


@dataclass(frozen=True)
class UnexplainedBand:
    wavenumber: float
    relative_intensity: float
    hint: str


@dataclass(frozen=True)
class StructureCheck:
    groups: tuple[GroupCheck, ...]
    unexplained: tuple[UnexplainedBand, ...]

    @property
    def found(self) -> tuple[GroupCheck, ...]:
        return tuple(g for g in self.groups if g.status == FOUND)

    @property
    def not_seen(self) -> tuple[GroupCheck, ...]:
        return tuple(g for g in self.groups if g.status == NOT_SEEN)

    @property
    def consistent(self) -> bool:
        return not self.not_seen and not any(b.relative_intensity >= 0.35 for b in self.unexplained)


def check_structure(
    smiles: str,
    analysis: FunctionalGroupAnalysis,
    spectrum: Spectrum | None,
) -> StructureCheck | None:
    """Compare a structure with the spectrum's analysis (``None`` without a structure)."""
    structure = groups_in_smiles(smiles)
    if structure is None or not structure.present:
        return None
    by_id = {result.group_id: result for result in analysis.results}
    groups: list[GroupCheck] = []
    reliability = _model_reliability()
    for group_id in structure.present:
        result = by_id.get(group_id)
        if result is None or group_id in _TOO_GENERIC:
            continue
        groups.append(_judge(result, reliability.get(group_id, 0.0)))
    groups = _drop_covered_parents(groups)
    groups.sort(key=lambda g: ({NOT_SEEN: 0, WEAK: 1, FOUND: 2}[g.status], -g.score))
    unexplained = (
        _unexplained_bands(
            spectrum,
            [by_id[g] for g in structure.present if g in by_id],
            _extra_windows(smiles),
        )
        if spectrum is not None
        else ()
    )
    return StructureCheck(groups=tuple(groups), unexplained=tuple(unexplained))


def _model_reliability() -> dict[str, float]:
    """Cross-validated F1 of the model per group (0 when unknown)."""
    from processing.fg_model import load_model  # noqa: PLC0415

    model = load_model()
    if model is None:
        return {}
    return {
        group: float(f1)
        for group, f1 in zip(model.groups, model.info.get("cv_f1", []), strict=False)
    }


def _judge(result: FunctionalGroupScore, reliability: float) -> GroupCheck:
    if result.evidence_source == "model":
        score = float(result.score)
        if score >= 55.0:
            status = FOUND
        elif score < _ABSENT_SCORE and reliability >= _TRUSTED_ABSENCE_F1:
            status = NOT_SEEN
        else:
            status = WEAK
        detail = ""
    else:
        # The model does not cover this group: its own required bands decide.
        required = [b for b in result.bands if b.role == "required"]
        matched = [b for b in required if b.confidence >= 55.0]
        weak = [b for b in required if 35.0 <= b.confidence < 55.0]
        score = float(result.rule_score if result.rule_score is not None else result.score)
        if required and len(matched) == len(required):
            status = FOUND
        elif matched or weak:
            status = WEAK
        else:
            status = NOT_SEEN
        detail = ", ".join(b.label for b in required if b.confidence < 55.0)
    return GroupCheck(
        group_id=result.group_id,
        group_name=result.group_name,
        status=status,
        score=round(score, 1),
        evidence_source=result.evidence_source,
        detail=detail,
    )


# A child pattern that is found makes its parent's line redundant.
_PARENT_OF = {
    "primary_alcohol": "alcohol",
    "secondary_alcohol": "alcohol",
    "tertiary_alcohol": "alcohol",
    "primary_amide": "amide",
    "secondary_amide": "amide",
    "primary_amine": "amine",
    "secondary_amine": "amine",
    "monosubstituted_benzene": "aromatic_ring",
    "ortho_disubstituted_benzene": "aromatic_ring",
    "meta_disubstituted_benzene": "aromatic_ring",
    "para_disubstituted_benzene": "aromatic_ring",
    "trisubstituted_benzene_1_2_4": "aromatic_ring",
    "trisubstituted_benzene_1_2_3": "aromatic_ring",
    "trisubstituted_benzene_1_3_5": "aromatic_ring",
    "terminal_alkene": "alkene",
    "vinylidene_alkene": "alkene",
    "cis_disubstituted_alkene": "alkene",
    "trans_disubstituted_alkene": "alkene",
    "trisubstituted_alkene": "alkene",
}


def _drop_covered_parents(groups: list[GroupCheck]) -> list[GroupCheck]:
    """Keep a parent only when it adds something its found children do not."""
    found_children_parents = {
        _PARENT_OF[g.group_id] for g in groups if g.group_id in _PARENT_OF and g.status == FOUND
    }
    return [g for g in groups if not (g.group_id in found_children_parents and g.status == FOUND)]


def _extra_windows(smiles: str) -> list[tuple[float, float]]:
    from rdkit import Chem  # noqa: PLC0415

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return []
    windows: list[tuple[float, float]] = []
    for smarts, motif_windows in _EXTRA_MOTIFS:
        pattern = Chem.MolFromSmarts(smarts)
        if pattern is not None and mol.HasSubstructMatch(pattern):
            windows.extend(motif_windows)
    return windows


def _unexplained_bands(
    spectrum: Spectrum,
    results: list[FunctionalGroupScore],
    extra_windows: list[tuple[float, float]] | None = None,
) -> list[UnexplainedBand]:
    prepared = absorbance_profile(spectrum)
    if prepared is None:
        return []
    grid, profile = prepared
    peaks, _props = find_peaks(profile, prominence=0.12, distance=5)
    windows = [
        (b.range_min, b.range_max) for r in results for b in r.bands if b.role != "exclusion"
    ]
    windows.extend(_ALWAYS_EXPLAINED)
    windows.extend(extra_windows or ())
    found: list[UnexplainedBand] = []
    for index in peaks:
        wavenumber = float(grid[index])
        height = float(profile[index])
        if any(low - 10.0 <= wavenumber <= high + 10.0 for low, high in windows):
            continue
        hint = _hint(wavenumber, profile, grid)
        if wavenumber < _FINGERPRINT_LIMIT and (hint == _GENERIC_HINT or height < 0.3):
            continue
        found.append(
            UnexplainedBand(
                wavenumber=round(wavenumber),
                relative_intensity=round(height, 2),
                hint=hint,
            )
        )
    found.sort(key=lambda band: -band.relative_intensity)
    return found[:6]


def _near(grid: np.ndarray, profile: np.ndarray, centre: float, width: float = 15.0) -> float:
    window = (grid >= centre - width) & (grid <= centre + width)
    return float(profile[window].max()) if window.any() else 0.0


def _hint(wavenumber: float, profile: np.ndarray, grid: np.ndarray) -> str:
    """The usual suspects for an unexplained band at this position."""
    if 2300.0 <= wavenumber <= 2380.0:
        return "atmospheric CO2 (background not matched)"
    if 3200.0 <= wavenumber <= 3600.0:
        if _near(grid, profile, 1640.0) > 0.15:
            return "O-H: water (moisture in KBr) or an unexpected OH/NH"
        if _near(grid, profile, 1030.0) > 0.3:
            return "O-H: residual methanol or an unexpected alcohol"
        return "O-H / N-H not in the structure: water, residual solvent or a hydrolysis product"
    if 1600.0 <= wavenumber <= 1660.0 and _near(grid, profile, 3400.0, 120.0) > 0.15:
        return "H-O-H bend: water (moisture in KBr)"
    if 1680.0 <= wavenumber <= 1820.0:
        return (
            "C=O not in the structure: oxidation, unreacted starting material or residual "
            "ester/ketone solvent"
        )
    if 2100.0 <= wavenumber <= 2280.0:
        return "triple bond or cumulated group (C#N, C#C, N=C=O, N3) not in the structure"
    if 745.0 <= wavenumber <= 770.0 and _near(grid, profile, 1216.0, 8.0) > 0.15:
        return "C-Cl: residual chloroform from casting the film"
    if 1208.0 <= wavenumber <= 1224.0 and _near(grid, profile, 757.0, 10.0) > 0.3:
        return "residual chloroform from casting the film"
    if 1000.0 <= wavenumber <= 1060.0 and _near(grid, profile, 3350.0, 120.0) > 0.15:
        return "C-O: residual methanol from casting the film"
    if 3000.0 <= wavenumber <= 3110.0:
        return "=C-H stretch (aromatic ring or C=C) not in the structure"
    if 1440.0 <= wavenumber <= 1630.0:
        return "ring or C=C / C=N stretch not in the structure"
    if 680.0 <= wavenumber <= 900.0 and _near(grid, profile, 3050.0, 40.0) > 0.12:
        return "out-of-plane C-H bend: an aromatic ring or C=C not in the structure?"
    return _GENERIC_HINT
