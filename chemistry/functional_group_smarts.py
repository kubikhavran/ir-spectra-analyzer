"""Which functional groups of the IR knowledge base a structure contains.

Every group of ``storage/data/functional_groups.v1.json`` is described here as
a substructure pattern (SMARTS) or, for the benzene substitution patterns, as a
small ring analysis. The mapping serves two purposes:

* **structure check** — a drawn structure says which groups the spectrum has
  to show, so the program verifies their bands instead of guessing among all
  68 groups;
* **benchmarking** — public reference spectra with a known structure get their
  ground-truth groups from the same definitions the program checks.

``groups_in_structure`` answers three ways per group: present (with the atoms
that carry it), absent, or *undetermined* — a cis/trans alkene drawn without
stereo cannot be called either.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cache
from typing import Any

from rdkit import Chem

# group id -> SMARTS alternatives (a match of any one means "present").
_SMARTS: dict[str, tuple[str, ...]] = {
    "carboxylic_acid": ("[CX3](=O)[OX2H1]",),
    "amide": ("[#6,#1][CX3](=[OX1])[NX3;!$(N[OX2]);!$(N=*)]", "[CX3H1](=[OX1])[NX3]"),
    "primary_amide": ("[#6][CX3](=[OX1])[NX3H2]", "[CX3H1](=[OX1])[NX3H2]"),
    "secondary_amide": ("[#6,#1][CX3](=[OX1])[NX3H1][#6]", "[CX3H1](=[OX1])[NX3H1][#6]"),
    "ester": ("[#6][CX3](=[OX1])[OX2H0][#6]", "[CX3H1](=[OX1])[OX2H0][#6]"),
    "aldehyde": ("[CX3H1](=[OX1])[#6]", "[CX3H2]=[OX1]"),
    "ketone": ("[#6][CX3](=[OX1])[#6]",),
    "alcohol": ("[OX2H][CX4]",),
    "primary_alcohol": ("[OX2H][CX4H2][#6]", "[OX2H][CH3]"),
    "secondary_alcohol": ("[OX2H][CX4H1]([#6])[#6]",),
    "tertiary_alcohol": ("[OX2H][CX4H0]([#6])([#6])[#6]",),
    "phenol": ("[OX2H]c",),
    "amine": ("[NX3;H2,H1;!$(N[C,S,P]=[O,S,N]);!$(N-[N,O]);!$(N#*);!$(N=*)][#6]",),
    "primary_amine": ("[NX3;H2;!$(N[C,S,P]=[O,S,N]);!$(N-[N,O])][#6]",),
    "secondary_amine": ("[NX3;H1;!$(N[C,S,P]=[O,S,N]);!$(N-[N,O])]([#6])[#6]",),
    "aliphatic_hydrocarbon": ("[CX4;H1,H2,H3]",),
    "isopropyl_group": ("[CH3][CX4H1][CH3]",),
    "tert_butyl_group": ("[CH3][CX4]([CH3])([CH3])[!#1]",),
    "long_chain_n_alkyl": ("[CH2X4][CH2X4][CH2X4][CH2X4]",),
    "carboxylate": ("[CX3](=[OX1])[OX1-]",),
    "oxime": ("[CX3]=[NX2][OX2H]",),
    "nitrile": ("[NX1]#[CX2][#6]",),
    "nitro": ("[#6][$([NX3](=O)=O),$([NX3+](=O)[O-])]",),
    "alkene": ("[CX3;!a;!$(C=[!#6])]=[CX3;!a;!$(C=[!#6])]",),
    "terminal_alkene": ("[CX3H2;!a]=[CX3H1;!a]",),
    "vinylidene_alkene": ("[CX3H2;!a]=[CX3H0;!a]([#6])[#6]",),
    "trisubstituted_alkene": ("[#6][CX3H1;!a]=[CX3H0;!a]([#6])[#6]",),
    "aromatic_ring": ("a1aaaaa1",),
    "benzene": ("[cH]1[cH][cH][cH][cH][cH]1",),
    "terminal_alkyne": ("[CX2H1]#[CX2]",),
    "acid_halide": ("[CX3](=[OX1])[F,Cl,Br,I]",),
    "anhydride": ("[CX3](=[OX1])[OX2][CX3](=[OX1])",),
    "aliphatic_ether": ("[OX2;!$(O[CX3]=[O,S,N]);!$(O-[O,N,S,P,Si])]([CX4])[CX4]",),
    "aryl_ether": ("[OX2;!$(O[CX3]=[O,S,N]);!$(O-[O,N,S,P,Si])](c)[#6]",),
    "amine_salt": ("[NX4+;H1,H2,H3]",),
    "aromatic_amine": ("[NX3;H2,H1;!$(N[C,S,P]=[O,S,N]);!$(N-[N,O])]c",),
    "azide": ("[NX2]=[NX2+]=[NX1-]", "[NX2-][NX2+]#[NX1]", "N=[N+]=[N-]"),
    "isocyanate": ("[NX2]=[CX2]=[OX1]",),
    "thiocyanate": ("[SX2][CX2]#[NX1]",),
    "allene": ("[CX3]=[CX2]=[CX3]",),
    "thiol": ("[SX2H]",),
    "sulfoxide": ("[SX3](=[OX1])([#6])[#6]", "[SX3+]([OX1-])([#6])[#6]"),
    "sulfone": ("[SX4](=[OX1])(=[OX1])([#6])[#6]",),
    "sulfonamide": ("[SX4](=[OX1])(=[OX1])[NX3]",),
    "sulfonyl_chloride": ("[SX4](=[OX1])(=[OX1])Cl",),
    "carbodiimide": ("[NX2]=[CX2]=[NX2]",),
    "isothiocyanate": ("[NX2]=[CX2]=[SX1]",),
    "sulfate": ("[OX2][SX4](=[OX1])(=[OX1])[OX2,OX1-]",),
    "sulfonate": ("[#6][SX4](=[OX1])(=[OX1])[OX2,OX1-]",),
    "vinyl_ether": ("[OX2;!$(O[CX3]=O)][CX3;!a]=[CX3;!a]",),
    "imine": ("[#6][CX3;!$(C-[O,N,S])]=[NX2;!$(N-[O,N]);!$(N=*=*)]",),
    "epoxide": ("[CX4]1[OX2][CX4]1",),
    "siloxane_silicone": ("[Si][OX2][Si]",),
    "organophosphate": ("[PX4](=[OX1])",),
    "internal_alkyne": ("[#6][CX2]#[CX2][#6]",),
    "tms_group": ("[Si]([CH3])([CH3])[CH3]",),
    "tbs_group": ("[Si]([CH3])([CH3])[CX4]([CH3])([CH3])[CH3]",),
}

# Groups judged by how much of something a molecule carries, not by one motif.
# (group id, SMARTS of the counted unit, minimum count)
_COUNTED: tuple[tuple[str, str, int], ...] = (
    ("methylene_rich_alkyl", "[CH2X4]", 3),
    ("methyl_rich_alkyl", "[CH3X4]", 2),
)

# Stereo-dependent alkenes: decided only when the double bond's geometry is drawn.
_CIS_TRANS = ("cis_disubstituted_alkene", "trans_disubstituted_alkene")

_BENZENE_PATTERNS = {
    (1,): "monosubstituted_benzene",
    (1, 2): "ortho_disubstituted_benzene",
    (1, 3): "meta_disubstituted_benzene",
    (1, 4): "para_disubstituted_benzene",
    (1, 2, 4): "trisubstituted_benzene_1_2_4",
    (1, 2, 3): "trisubstituted_benzene_1_2_3",
    (1, 3, 5): "trisubstituted_benzene_1_3_5",
}

#: Every group id this module can decide.
KNOWN_GROUP_IDS: frozenset[str] = frozenset(
    set(_SMARTS)
    | {group for group, _smarts, _count in _COUNTED}
    | set(_CIS_TRANS)
    | set(_BENZENE_PATTERNS.values())
)


@dataclass(frozen=True)
class StructureGroups:
    """What a structure says about each knowledge-base group."""

    present: dict[str, tuple[tuple[int, ...], ...]] = field(default_factory=dict)
    undetermined: frozenset[str] = frozenset()

    def has(self, group_id: str) -> bool:
        return group_id in self.present

    def is_known(self, group_id: str) -> bool:
        """Whether the structure decides this group (present or clearly absent)."""
        return group_id in KNOWN_GROUP_IDS and group_id not in self.undetermined


@cache
def _pattern(smarts: str) -> Any:
    pattern = Chem.MolFromSmarts(smarts)
    if pattern is None:  # pragma: no cover - guarded by the test suite
        raise ValueError(f"invalid SMARTS: {smarts}")
    return pattern


def groups_in_structure(mol: Any) -> StructureGroups:
    """Groups of the knowledge base found in an RDKit molecule."""
    if mol is None or mol.GetNumAtoms() == 0:
        return StructureGroups()
    present: dict[str, tuple[tuple[int, ...], ...]] = {}
    for group_id, alternatives in _SMARTS.items():
        matches: list[tuple[int, ...]] = []
        for smarts in alternatives:
            matches.extend(tuple(m) for m in mol.GetSubstructMatches(_pattern(smarts)))
        if matches:
            present[group_id] = tuple(dict.fromkeys(matches))
    for group_id, smarts, minimum in _COUNTED:
        matches = mol.GetSubstructMatches(_pattern(smarts))
        if len(matches) >= minimum:
            present[group_id] = tuple(tuple(m) for m in matches)
    for group_id, atoms in _benzene_substitution(mol).items():
        present[group_id] = atoms
    stereo, undetermined = _cis_trans(mol)
    present.update(stereo)
    return StructureGroups(present=present, undetermined=frozenset(undetermined))


def groups_in_smiles(smiles: str) -> StructureGroups | None:
    """``groups_in_structure`` for a SMILES string (``None`` when it does not parse)."""
    mol = Chem.MolFromSmiles(smiles) if smiles else None
    if mol is None:
        return None
    return groups_in_structure(mol)


def _benzene_substitution(mol: Any) -> dict[str, tuple[tuple[int, ...], ...]]:
    """Substitution pattern of every isolated (not fused) benzene ring."""
    found: dict[str, list[tuple[int, ...]]] = {}
    ring_info = mol.GetRingInfo()
    for ring in ring_info.AtomRings():
        if len(ring) != 6:
            continue
        atoms = [mol.GetAtomWithIdx(i) for i in ring]
        if not all(a.GetSymbol() == "C" and a.GetIsAromatic() for a in atoms):
            continue
        if any(ring_info.NumAtomRings(i) > 1 for i in ring):
            continue  # fused ring: its out-of-plane pattern is not the textbook one
        ring_set = set(ring)
        substituted = [
            position
            for position, atom in enumerate(atoms)
            if any(n.GetIdx() not in ring_set and n.GetAtomicNum() > 1 for n in atom.GetNeighbors())
        ]
        key = _canonical_positions(substituted)
        group = _BENZENE_PATTERNS.get(key) if key else None
        if group is not None:
            found.setdefault(group, []).append(tuple(ring))
    return {group: tuple(rings) for group, rings in found.items()}


def _canonical_positions(positions: list[int]) -> tuple[int, ...] | None:
    """Lowest locant set (1-based) of substituent positions on a six-ring."""
    if not positions:
        return None
    best: tuple[int, ...] | None = None
    for start in positions:
        for direction in (1, -1):
            locants = tuple(sorted(((p - start) * direction) % 6 + 1 for p in positions))
            if best is None or locants < best:
                best = locants
    return best


def _cis_trans(mol: Any) -> tuple[dict[str, tuple[tuple[int, ...], ...]], set[str]]:
    """1,2-Disubstituted alkenes: cis or trans when drawn, undetermined otherwise."""
    present: dict[str, list[tuple[int, ...]]] = {}
    undetermined: set[str] = set()
    pattern = _pattern("[#6][CX3H1;!a]=[CX3H1;!a][#6]")
    for match in mol.GetSubstructMatches(pattern):
        bond = mol.GetBondBetweenAtoms(match[1], match[2])
        if bond is None:
            continue
        if bond.IsInRing() and _ring_size_of(mol, bond) < 8:
            # A double bond in a small ring is cis by construction.
            present.setdefault("cis_disubstituted_alkene", []).append(tuple(match))
            continue
        stereo = bond.GetStereo()
        if stereo in (Chem.BondStereo.STEREOE, Chem.BondStereo.STEREOTRANS):
            present.setdefault("trans_disubstituted_alkene", []).append(tuple(match))
        elif stereo in (Chem.BondStereo.STEREOZ, Chem.BondStereo.STEREOCIS):
            present.setdefault("cis_disubstituted_alkene", []).append(tuple(match))
        else:
            undetermined.update(_CIS_TRANS)
    return {group: tuple(atoms) for group, atoms in present.items()}, undetermined


def _ring_size_of(mol: Any, bond: Any) -> int:
    sizes = [len(ring) for ring in mol.GetRingInfo().BondRings() if bond.GetIdx() in ring]
    return min(sizes) if sizes else 0
