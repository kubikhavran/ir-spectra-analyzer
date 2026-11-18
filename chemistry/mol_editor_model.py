"""Editable 2D molecule model for the native structure editor.

``MolEditorModel`` wraps an :class:`rdkit.Chem.RWMol` plus one 2D
:class:`rdkit.Chem.Conformer`.  The molecule is always kept in Kekulé form
(explicit single/double bonds, no aromatic flags) so every bond can be drawn
and edited directly; aromaticity is perceived again only when SMILES or a MOL
block is exported.

Coordinates are in Ångström-like units with a standard bond length of
:data:`BOND_LENGTH` and the y axis pointing *up* (RDKit convention).  The
canvas flips the y axis when it draws.

Every public editing method records an undo snapshot first (capped at
:data:`UNDO_LIMIT`).  Methods that are called continuously while dragging
(``move_atom`` / ``move_fragment``) only do so when asked to; the caller then
uses :meth:`MolEditorModel.checkpoint` once at the beginning of the drag.
"""

from __future__ import annotations

import cmath
import math
import re
from collections import deque
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache

from rdkit import Chem, rdBase
from rdkit.Chem import Descriptors, rdDepictor, rdMolDescriptors
from rdkit.Geometry import Point3D

from chemistry.mol_fragments import Fragment, parse_group

BOND_LENGTH = 1.50
UNDO_LIMIT = 100

STEREO_NONE = "none"
STEREO_WEDGE = "wedge"
STEREO_HASH = "hash"
STEREO_WAVY = "wavy"
_STEREO_TO_DIR = {
    STEREO_NONE: Chem.BondDir.NONE,
    STEREO_WEDGE: Chem.BondDir.BEGINWEDGE,
    STEREO_HASH: Chem.BondDir.BEGINDASH,
    STEREO_WAVY: Chem.BondDir.UNKNOWN,
}
_ORDER_TO_TYPE = {
    1: Chem.BondType.SINGLE,
    2: Chem.BondType.DOUBLE,
    3: Chem.BondType.TRIPLE,
}

ELEMENT_SYMBOLS: tuple[str, ...] = (
    "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne",
    "Na", "Mg", "Al", "Si", "P", "S", "Cl", "Ar", "K", "Ca",
    "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn",
    "Ga", "Ge", "As", "Se", "Br", "Kr", "Rb", "Sr", "Y", "Zr",
    "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "In", "Sn",
    "Sb", "Te", "I", "Xe", "Cs", "Ba", "La", "Ce", "Pr", "Nd",
    "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb",
    "Lu", "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg",
    "Tl", "Pb", "Bi", "Po", "At", "Rn", "Fr", "Ra", "Ac", "Th",
    "Pa", "U", "Np", "Pu", "Am", "Cm", "Bk", "Cf", "Es", "Fm",
    "Md", "No", "Lr", "Rf", "Db", "Sg", "Bh", "Hs", "Mt", "Ds",
    "Rg", "Cn", "Nh", "Fl", "Mc", "Lv", "Ts", "Og",
)  # fmt: skip

# Elements whose hydrogen count is derived from the default valence.  Other
# elements (metals, noble gases, explicit H atoms) get no implicit hydrogens,
# so drawing "Na" does not silently turn into sodium hydride.
_IMPLICIT_H_ELEMENTS = frozenset(
    {"B", "C", "N", "O", "P", "S", "F", "Cl", "Br", "I", "Si", "Se", "As", "Ge", "Te"}
)

# Maximum covalent bond order an anion (formal charge < 0) can carry before a
# newly added bond neutralizes the negative charge (e.g. R-COO⁻ + Me → R-COOMe).
_MAX_ANION_BONDS: dict[str, int] = {
    "C": 3,
    "N": 2,
    "O": 1,
    "S": 1,
    "Se": 1,
    "F": 0,
    "Cl": 0,
    "Br": 0,
    "I": 0,
}

# Bond / atom properties kept on the RWMol (they survive undo copies).
_BOLD = "_bold"
_AUTO_CHARGE = "_auto_charge"
_MANUAL_CHARGE = "_manual_charge"
_AUTO_ZWITTER = "_auto_zwitter"
# The MOL file's comment line (line 3) carries what V2000 cannot: bold bonds.
_MOLFILE_TAG = "IRSA"

# Formal charge an atom gets automatically from its bond count, as ChemDraw
# and Marvin do: a four-bonded N is N⁺, a three-bonded O is O⁺, a four-bonded
# B/Al/Ga is M⁻, six-bonded P/Sb is M⁻.  (symbol, bonds incl. H) → charge.
_AUTO_CHARGES: dict[tuple[str, int], int] = {
    ("N", 4): 1,
    ("O", 3): 1,
    ("B", 4): -1,
    ("Al", 4): -1,
    ("Ga", 4): -1,
    ("P", 6): -1,
    ("Sb", 6): -1,
}

# Onium ions formed only when every bond to the atom is a single bond, so
# double-bonded species like sulfoxides, H-phosphonates (R2P(=O)H) or PhI=O
# stay neutral.
_AUTO_CHARGES_ALL_SINGLE: dict[tuple[str, int], int] = {
    ("S", 3): 1,
    ("Se", 3): 1,
    ("P", 4): 1,
    ("As", 4): 1,
    ("Cl", 2): 1,
    ("Br", 2): 1,
    ("I", 2): 1,
}

_SUBSCRIPTS = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")
_SUPERSCRIPTS = str.maketrans("0123456789+-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻")


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _RingTemplate:
    smiles: str
    attach_atom: int  # template atom bonded to the target atom
    fusion_bond: tuple[int, int]  # template edge laid onto a target bond
    aromatic: bool
    # Hand-made 2D coordinates (e.g. a chair), in template atom order.
    coords: tuple[tuple[float, float], ...] | None = None
    # Whole building blocks (sugars) are attached through an atom, never fused.
    fusable: bool = True
    # Template bonds drawn bold (the front edge of a chair).
    bold_bonds: tuple[tuple[int, int], ...] = ()


# Chair conformation as chemists draw it: three pairs of parallel bonds.
# Chair as in textbooks (4C1): left tip up, right tip down, ring O (for the
# pyranose) at the back right.  Atom order: left tip, front left, front right,
# right tip, back right, back left.  The three front bonds are drawn bold.
_CHAIR = ((0.0, 0.0), (0.55, -0.9), (1.6, -0.65), (2.65, -0.95), (2.1, -0.05), (1.05, -0.3))
_CHAIR_FRONT = ((0, 1), (1, 2), (2, 3))

# A new atom closer than this to an existing one reads as an overlap.
_CLEAR = 0.6 * BOND_LENGTH
# Turns (degrees) of a new bond tried when the usual direction is crowded.
_TURN_STEPS = (0, 15, -15, 30, -30, 45, -45, 60, -60)


def _folded_branches(
    fragment: Fragment, pts: list[complex], outward: complex
) -> list[complex] | None:
    """*pts* redrawn as a compact fan pointing along *outward*.

    Branches leave each atom 60° apart (the attach atom's over at least
    120°), chains zig-zag, and ring systems keep their shape:
    how a group is drawn on a crowded atom. ``None`` when the attach atom is
    in a ring or has no branch.
    """
    if fragment.attach is None or abs(outward) < 1e-9:
        return None
    mol = fragment.mol
    attach = fragment.attach
    root = mol.GetAtomWithIdx(attach)
    if root.IsInRing() or root.GetDegree() < 1:
        return None
    folded = list(pts)

    def subtree(start: int, parent: int) -> set[int]:
        members = {start}
        queue = deque([start])
        while queue:
            current = queue.popleft()
            for nbr in mol.GetAtomWithIdx(current).GetNeighbors():
                idx = nbr.GetIdx()
                if idx != parent and idx not in members:
                    members.add(idx)
                    queue.append(idx)
        return members

    def place(atom: int, parent: int, direction: complex, depth: int, flip: int) -> None:
        children = [n.GetIdx() for n in mol.GetAtomWithIdx(atom).GetNeighbors()]
        children = [c for c in children if c != parent]
        if not children:
            return
        if len(children) == 1:
            offsets = [0.0 if depth == 0 else 30.0 * flip]
        else:
            # Neighbouring branches stay 60° apart (one bond length).
            width = max(60.0 * (len(children) - 1), 120.0 if depth == 0 else 0.0)
            offsets = [-width / 2 + width * i / (len(children) - 1) for i in range(len(children))]
        centre = folded[atom]
        # The largest branches take the middle directions, the smallest the sides.
        by_size = sorted(children, key=lambda c: (-len(subtree(c, atom)), c))
        middle_first = sorted(offsets, key=lambda o: (abs(o), o))
        for child, offset in zip(by_size, middle_first, strict=True):
            heading = direction * cmath.exp(1j * math.radians(offset))
            if mol.GetAtomWithIdx(child).IsInRing():
                # A ring system keeps its drawn shape, turned so that it
                # points straight along the new bond.
                members = subtree(child, atom)
                middle = sum(pts[idx] for idx in members) / len(members)
                old = middle - pts[child]
                if abs(old) < 1e-9:
                    old = pts[child] - pts[atom]
                turn = (heading / abs(heading)) / (old / abs(old))
                start = centre + BOND_LENGTH * heading
                for idx in members:
                    folded[idx] = start + (pts[idx] - pts[child]) * turn
                continue
            folded[child] = centre + BOND_LENGTH * heading
            place(child, atom, heading, depth + 1, -flip if flip else 1)

    axis = outward / abs(outward)
    place(attach, -1, axis, 0, 1)
    return folded


def _self_clearance(points: list[complex]) -> float:
    """Smallest distance between two atoms of one layout."""
    return min(
        (abs(a - b) for i, a in enumerate(points) for b in points[i + 1 :]), default=math.inf
    )


def _clearance(placed: list[complex], others: list[complex]) -> float:
    return min((abs(p - o) for p in placed for o in others), default=math.inf)


def _least_clashing(
    options: list[tuple[int, bool, list[complex]]],
    others: list[complex],
    crowding: Callable[[list[complex]], float],
) -> tuple[int, bool, list[complex]]:
    """The smallest turn that clears every atom, else the one that clears most."""
    clear = [o for o in options if _clearance(o[2], others) >= _CLEAR]
    if clear:
        return min(clear, key=lambda o: (abs(o[0]), crowding(o[2])))
    return max(options, key=lambda o: _clearance(o[2], others))


RING_TEMPLATES: dict[str, _RingTemplate] = {
    "cyclopropane": _RingTemplate("C1CC1", 0, (0, 1), False),
    "cyclobutane": _RingTemplate("C1CCC1", 0, (0, 1), False),
    "cyclopentane": _RingTemplate("C1CCCC1", 0, (0, 1), False),
    "cyclohexane": _RingTemplate("C1CCCCC1", 0, (0, 1), False),
    "cycloheptane": _RingTemplate("C1CCCCCC1", 0, (0, 1), False),
    "benzene": _RingTemplate("c1ccccc1", 0, (0, 1), True),
    # 4-pyridyl / 4-pyrimidinyl when attached.
    "pyridine": _RingTemplate("c1ccncc1", 0, (0, 1), True),
    "pyrimidine": _RingTemplate("c1ncncc1", 4, (4, 5), True),
    "pyrazine": _RingTemplate("c1cnccn1", 0, (0, 1), True),
    # 2-Pyridone attached through its N (N-substituted pyridones).
    "pyridone": _RingTemplate("O=c1cccc[nH]1", 6, (3, 4), True),
    # 2-furyl / 2-thienyl / 2-pyrrolyl / 2-imidazolyl; fusion gives benzo-rings.
    "furan": _RingTemplate("c1ccco1", 0, (0, 1), True),
    "thiophene": _RingTemplate("c1cccs1", 0, (0, 1), True),
    "pyrrole": _RingTemplate("c1ccc[nH]1", 0, (0, 1), True),
    "imidazole": _RingTemplate("c1cnc[nH]1", 3, (0, 1), True),
    "pyrazole": _RingTemplate("c1cc[nH]n1", 0, (0, 1), True),
    "oxazole": _RingTemplate("c1cocn1", 3, (0, 1), True),
    "isoxazole": _RingTemplate("c1cnoc1", 1, (0, 1), True),
    "thiazole": _RingTemplate("c1cscn1", 3, (0, 1), True),
    # 1,2,3-triazole attached at C4 (the "click" 1,4-substitution).
    "triazole_123": _RingTemplate("c1c[nH]nn1", 0, (0, 1), True),
    "triazole_124": _RingTemplate("c1nc[nH]n1", 0, (0, 1), True),
    "tetrazole": _RingTemplate("c1nn[nH]n1", 0, (0, 1), True),
    # 1-naphthyl / 3-indolyl / 2-quinolyl when attached.
    "naphthalene": _RingTemplate("c1ccc2ccccc2c1", 9, (0, 1), True),
    "indole": _RingTemplate("c1ccc2[nH]ccc2c1", 6, (0, 1), True),
    "quinoline": _RingTemplate("c1ccc2ncccc2c1", 5, (0, 1), True),
    "indane": _RingTemplate("C1Cc2ccccc2C1", 4, (4, 5), True),
    # Biphenyl attached through the para position of one ring.
    "biphenyl": _RingTemplate("c1ccc(cc1)-c1ccccc1", 0, (0, 1), True, fusable=False),
    "benzisoxazole": _RingTemplate("c1ccc2oncc2c1", 6, (0, 1), True),
    "benzimidazole": _RingTemplate("c1ccc2[nH]cnc2c1", 5, (0, 1), True),
    "benzodioxole": _RingTemplate("c1ccc2c(c1)OCO2", 1, (0, 1), True),
    "pyrene": _RingTemplate("c1cc2ccc3cccc4ccc(c1)c2c34", 0, (0, 1), True, fusable=False),
    # Saturated heterocycles: the ether rings sugars are built on, and amines.
    "oxane": _RingTemplate("C1CCOCC1", 0, (0, 1), False),
    "oxolane": _RingTemplate("C1CCOC1", 0, (0, 1), False),
    "dioxane": _RingTemplate("C1COCCO1", 0, (0, 1), False),
    "piperidine": _RingTemplate("N1CCCCC1", 0, (1, 2), False),
    "morpholine": _RingTemplate("N1CCOCC1", 0, (1, 2), False),
    "piperazine": _RingTemplate("N1CCNCC1", 0, (1, 2), False),
    "pyrrolidine": _RingTemplate("N1CCCC1", 0, (1, 2), False),
    "thiazolidine": _RingTemplate("N1CCSC1", 0, (1, 2), False),
    # 2-Oxazolidinone attached through its N (Evans auxiliaries, linezolid).
    "oxazolidinone": _RingTemplate("O=C1NCCO1", 2, (3, 4), False),
    # Steroid skeleton (gonane), attached at C3.
    "steroid": _RingTemplate("C1CCC2C(C1)CCC1C3CCCC3CCC21", 1, (0, 1), False, fusable=False),
    # 2-Pyrrolidone (γ-lactam) attached through its N.
    "pyrrolidone": _RingTemplate("O=C1CCCN1", 5, (2, 3), False),
    # Chair conformations; the oxane chair has O at the back, next to the
    # right-hand tip (C1 of a pyranose).
    "chair": _RingTemplate("C1CCCCC1", 3, (0, 1), False, _CHAIR, bold_bonds=_CHAIR_FRONT),
    "oxane_chair": _RingTemplate("C1CCCOC1", 3, (0, 1), False, _CHAIR, bold_bonds=_CHAIR_FRONT),
    # Sugars with wedges; they attach through the anomeric OH oxygen
    # (a glycosidic bond) and are never fused.
    "beta_glucopyranose": _RingTemplate(
        "OC[C@H]1O[C@@H](O)[C@H](O)[C@@H](O)[C@@H]1O", 5, (2, 3), False, fusable=False
    ),
    "alpha_glucopyranose": _RingTemplate(
        "OC[C@H]1O[C@H](O)[C@H](O)[C@@H](O)[C@@H]1O", 5, (2, 3), False, fusable=False
    ),
    "beta_ribofuranose": _RingTemplate(
        "OC[C@H]1O[C@@H](O)[C@H](O)[C@@H]1O", 5, (2, 3), False, fusable=False
    ),
}

# Functional groups: SMILES whose atom 0 bonds to the target atom.
FUNCTIONAL_GROUPS: dict[str, str] = {
    "-OH": "O",
    "-NH2": "N",
    "-COOH": "C(=O)O",
    "-COOMe": "C(=O)OC",
    "-CHO": "C=O",
    "-CN": "C#N",
    "-NO2": "[N+](=O)[O-]",
    "-SO3H": "S(=O)(=O)O",
    "-CF3": "C(F)(F)F",
    "-SiMe3": "[Si](C)(C)C",
    "-TMS": "[Si](C)(C)C",
    "-Ph": "c1ccccc1",
    "-Ac": "C(C)=O",
    "-Boc": "C(=O)OC(C)(C)C",
    "-OMe": "OC",
    "-OAc": "OC(C)=O",
    "-tBu": "C(C)(C)C",
    "-OtBu": "OC(C)(C)C",
    "-NHAc": "NC(C)=O",
    "-NHBoc": "NC(=O)OC(C)(C)C",
    "-N3": "N=[N+]=[N-]",
    "-OTIPS": "O[Si](C(C)C)(C(C)C)C(C)C",
    "-OTBS": "O[Si](C)(C)C(C)(C)C",
    "-SO3-": "S(=O)(=O)[O-]",
    "-OEt": "OCC",
    "-COOEt": "C(=O)OCC",
    "-NEt2": "N(CC)CC",
    "-Piv": "C(=O)C(C)(C)C",
    "-OPiv": "OC(=O)C(C)(C)C",
    "-OSO3H": "OS(=O)(=O)O",
    "-Ts": "S(=O)(=O)c1ccc(C)cc1",
    "-NHTs": "NS(=O)(=O)c1ccc(C)cc1",
    "-TIPS": "[Si](C(C)C)(C(C)C)C(C)C",
}
# Groups with three branches on one atom: placed with a computed layout.
# Groups with a ring are placed the same way (atom-by-atom sprouting cannot
# close a ring).
_LAID_OUT_GROUPS = frozenset({"-OTIPS", "-OTBS", "-TIPS", "-Ts", "-NHTs"})


@contextmanager
def _quiet_rdkit() -> Iterator[None]:
    """Silence RDKit's stderr logging for operations that may legitimately fail."""
    blocker = rdBase.BlockLogs()
    try:
        yield
    finally:
        del blocker


def is_element_symbol(symbol: str) -> bool:
    return symbol in ELEMENT_SYMBOLS


def format_formula(formula: str) -> str:
    """Render an RDKit Hill formula with Unicode sub-/superscripts.

    ``C2H3O2-`` → ``C₂H₃O₂⁻``; ``O-2`` → ``O²⁻``.
    """
    if not formula:
        return ""
    match = re.match(r"^(.*?)([+-])(\d*)$", formula)
    charge = ""
    body = formula
    if match:
        body, sign, count = match.groups()
        charge = (count + sign).translate(_SUPERSCRIPTS)
    return body.translate(_SUBSCRIPTS) + charge


def _kekulized_template(smiles: str) -> Chem.Mol:
    with _quiet_rdkit():
        mol = Chem.MolFromSmiles(smiles)
    if mol is None:  # pragma: no cover - static templates
        raise ValueError(f"Invalid template SMILES: {smiles}")
    Chem.Kekulize(mol, clearAromaticFlags=True)
    rdDepictor.Compute2DCoords(mol)
    return mol


@lru_cache(maxsize=64)
def _template_cached(ring_type: str) -> Chem.Mol:
    spec = RING_TEMPLATES[ring_type]
    mol = _kekulized_template(spec.smiles)
    if spec.coords is not None:
        conf = mol.GetConformer()
        lengths = [
            math.dist(spec.coords[b.GetBeginAtomIdx()], spec.coords[b.GetEndAtomIdx()])
            for b in mol.GetBonds()
        ]
        factor = BOND_LENGTH / (sum(lengths) / len(lengths))
        for idx, (x, y) in enumerate(spec.coords):
            conf.SetAtomPosition(idx, Point3D(x * factor, y * factor, 0.0))
    if any(a.GetChiralTag() != Chem.ChiralType.CHI_UNSPECIFIED for a in mol.GetAtoms()):
        with _quiet_rdkit():
            Chem.WedgeMolBonds(mol, mol.GetConformer())
    return mol


def _template_mol(ring_type: str) -> Chem.Mol:
    """Template molecule with 2D coordinates (and wedges for stereo templates)."""
    if ring_type not in RING_TEMPLATES:
        raise ValueError(f"Unknown ring template: {ring_type!r}")
    return Chem.Mol(_template_cached(ring_type))


def _swap_wedges(mol: Chem.Mol) -> None:
    """Swap wedge ↔ hash: a 2D mirror image needs it to stay the same molecule."""
    for bond in mol.GetBonds():
        if bond.GetBondDir() == Chem.BondDir.BEGINWEDGE:
            bond.SetBondDir(Chem.BondDir.BEGINDASH)
        elif bond.GetBondDir() == Chem.BondDir.BEGINDASH:
            bond.SetBondDir(Chem.BondDir.BEGINWEDGE)


def _arrange_components(mol: Chem.Mol) -> None:
    """Lay disconnected molecules/ions out side by side, largest first.

    RDKit packs the components of ``CC[NH3+].[Cl-].[Na+]`` so tightly that
    the labels run into each other; this puts a clear gap between them.
    """
    frags = Chem.GetMolFrags(mol, asMols=False, sanitizeFrags=False)
    if len(frags) < 2 or mol.GetNumConformers() == 0:
        return
    conf = mol.GetConformer()
    ordered = sorted(frags, key=lambda f: (-len(f), min(conf.GetAtomPosition(i).x for i in f)))
    cursor_x = 0.0
    for frag in ordered:
        xs = [conf.GetAtomPosition(i).x for i in frag]
        ys = [conf.GetAtomPosition(i).y for i in frag]
        dx = cursor_x - min(xs)
        dy = -(min(ys) + max(ys)) / 2
        for i in frag:
            pos = conf.GetAtomPosition(i)
            conf.SetAtomPosition(i, Point3D(pos.x + dx, pos.y + dy, 0.0))
        cursor_x += (max(xs) - min(xs)) + 2.0 * BOND_LENGTH


def _angle_of(dx: float, dy: float) -> float:
    return math.atan2(dy, dx)


def _normalize(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


class MolEditorModel:
    """An editable 2D molecule with undo/redo."""

    def __init__(self) -> None:
        self._mol = self._empty_mol()
        self._undo: deque[Chem.RWMol] = deque(maxlen=UNDO_LIMIT)
        self._redo: list[Chem.RWMol] = []
        self._revision = 0
        self._compound_depth = 0
        self._last_fragment_mirrored = False
        self._ring_cache: tuple[int, list[tuple[tuple[int, ...], tuple[int, ...]]]] | None = None

    # ------------------------------------------------------------------
    # Construction / IO
    # ------------------------------------------------------------------

    @staticmethod
    def _empty_mol() -> Chem.RWMol:
        mol = Chem.RWMol()
        mol.AddConformer(Chem.Conformer(0), assignId=True)
        return mol

    @classmethod
    def from_smiles(cls, smiles: str) -> MolEditorModel:
        model = cls()
        if not model.load_smiles(smiles, record_undo=False):
            raise ValueError(f"Invalid SMILES: {smiles!r}")
        return model

    @classmethod
    def from_mol_block(cls, mol_block: str) -> MolEditorModel:
        model = cls()
        if not model.load_mol_block(mol_block, record_undo=False):
            raise ValueError("Invalid MOL block")
        return model

    def load_smiles(self, smiles: str, *, record_undo: bool = True) -> bool:
        """Replace the structure with *smiles* (fresh 2D layout). Empty clears."""
        smiles = (smiles or "").strip()
        if not smiles:
            if record_undo:
                self._push_undo()
            self._set_mol(self._empty_mol())
            return True
        with _quiet_rdkit():
            parsed = Chem.MolFromSmiles(smiles)
        if parsed is None:
            return False
        try:
            Chem.Kekulize(parsed, clearAromaticFlags=True)
        except Exception:  # noqa: BLE001
            return False
        rdDepictor.Compute2DCoords(parsed)
        _arrange_components(parsed)
        with _quiet_rdkit():
            Chem.WedgeMolBonds(parsed, parsed.GetConformer())
        if record_undo:
            self._push_undo()
        self._set_mol(Chem.RWMol(parsed))
        self._mark_loaded_charges()
        return True

    def load_mol_block(self, mol_block: str, *, record_undo: bool = True) -> bool:
        """Replace the structure with a MOL block, keeping its 2D coordinates."""
        if not (mol_block or "").strip():
            return False
        with _quiet_rdkit():
            parsed = Chem.MolFromMolBlock(mol_block, sanitize=False, removeHs=False)
        if parsed is None or parsed.GetNumAtoms() == 0:
            return False
        try:
            with _quiet_rdkit():
                parsed.UpdatePropertyCache(strict=False)
                Chem.FastFindRings(parsed)
                if any(b.GetBondType() == Chem.BondType.AROMATIC for b in parsed.GetBonds()):
                    Chem.Kekulize(parsed, clearAromaticFlags=True)
                else:
                    for atom in parsed.GetAtoms():
                        atom.SetIsAromatic(False)
                    for bond in parsed.GetBonds():
                        bond.SetIsAromatic(False)
                Chem.AssignChiralTypesFromBondDirs(parsed)
        except Exception:  # noqa: BLE001
            return False
        mol = Chem.RWMol(parsed)
        if mol.GetNumConformers() == 0:
            mol.AddConformer(Chem.Conformer(mol.GetNumAtoms()), assignId=True)
        self._read_molfile_tags(mol, mol_block)
        if record_undo:
            self._push_undo()
        self._set_mol(mol)
        self._mark_loaded_charges()
        coords = [self.atom_position(i) for i in range(self.atom_count)]
        if len(coords) > 1 and all(abs(x) < 1e-6 and abs(y) < 1e-6 for x, y in coords):
            self._compute_layout()
        return True

    def to_smiles(self) -> str:
        """Canonical (aromatic) SMILES of the current drawing; ``""`` if empty."""
        if self.atom_count == 0:
            return ""
        mol = self._export_mol()
        with _quiet_rdkit():
            return str(Chem.MolToSmiles(mol))

    def to_mol_block(self) -> str:
        """V2000 MOL block with the drawn 2D coordinates; ``""`` if empty."""
        if self.atom_count == 0:
            return ""
        mol = Chem.Mol(self._mol)
        with _quiet_rdkit():
            mol.UpdatePropertyCache(strict=False)
            Chem.FastFindRings(mol)
            Chem.AssignChiralTypesFromBondDirs(mol)
            block = Chem.MolToMolBlock(mol, kekulize=False)
        bold = [b.GetIdx() + 1 for b in self._mol.GetBonds() if b.HasProp(_BOLD)]
        if bold:
            lines = block.split("\n")
            lines[2] = f"{_MOLFILE_TAG} bold=" + ",".join(str(i) for i in bold)
            block = "\n".join(lines)
        return str(block)

    @staticmethod
    def _read_molfile_tags(mol: Chem.RWMol, mol_block: str) -> None:
        for bond in mol.GetBonds():
            if bond.GetBondDir() == Chem.BondDir.NONE and (
                (bond.HasProp("_UnknownStereo") and bond.GetIntProp("_UnknownStereo") == 1)
                or (
                    bond.HasProp("_MolFileBondStereo")
                    and bond.GetIntProp("_MolFileBondStereo") == 4
                )
            ):
                bond.SetBondDir(Chem.BondDir.UNKNOWN)
        lines = mol_block.split("\n")
        if len(lines) < 3:
            return
        match = re.search(rf"{_MOLFILE_TAG} bold=([\d,]+)", lines[2])
        if match is None:
            return
        for token in match.group(1).split(","):
            if token.isdigit() and 0 < int(token) <= mol.GetNumBonds():
                mol.GetBondWithIdx(int(token) - 1).SetBoolProp(_BOLD, True)

    def _export_mol(self) -> Chem.Mol:
        mol = Chem.Mol(self._mol)
        has_wedges = any(b.GetBondDir() != Chem.BondDir.NONE for b in mol.GetBonds())
        with _quiet_rdkit():
            try:
                Chem.SanitizeMol(mol)
            except Exception:  # noqa: BLE001
                mol = Chem.Mol(self._mol)
                mol.UpdatePropertyCache(strict=False)
                Chem.FastFindRings(mol)
            if has_wedges:
                Chem.AssignChiralTypesFromBondDirs(mol, replaceExistingTags=True)
            Chem.AssignStereochemistry(mol, cleanIt=True, force=True)
        return mol

    def paste_text(self, text: str) -> bool:
        """Insert a SMILES string or MOL block next to the current drawing (undoable)."""
        raw = text or ""
        text = raw.strip()
        if not text:
            return False
        other = MolEditorModel()
        is_mol_block = "M  END" in text or "V2000" in text or "V3000" in text
        loaded = (
            other.load_mol_block(raw, record_undo=False)
            if is_mol_block
            else other.load_smiles(text, record_undo=False)
        )
        if not loaded or other.is_empty():
            return False
        if self.is_empty():
            self._push_undo()
            self._set_mol(Chem.RWMol(other._mol))
            return True
        bounds = self.bounds()
        other_bounds = other.bounds()
        if bounds is None or other_bounds is None:  # pragma: no cover - checked above
            return False
        dx = bounds[2] + 2 * BOND_LENGTH - other_bounds[0]
        dy = (bounds[1] + bounds[3]) / 2 - (other_bounds[1] + other_bounds[3]) / 2
        self._push_undo()
        index_map: dict[int, int] = {}
        for atom in other._mol.GetAtoms():
            x, y = other.atom_position(atom.GetIdx())
            index_map[atom.GetIdx()] = self._add_atom(Chem.Atom(atom), x + dx, y + dy)
        for bond in other._mol.GetBonds():
            self._mol.AddBond(
                index_map[bond.GetBeginAtomIdx()],
                index_map[bond.GetEndAtomIdx()],
                bond.GetBondType(),
            )
            new_bond = self._mol.GetBondBetweenAtoms(
                index_map[bond.GetBeginAtomIdx()], index_map[bond.GetEndAtomIdx()]
            )
            new_bond.SetBondDir(bond.GetBondDir())
        self._touch()
        return True

    def rdkit_mol(self) -> Chem.Mol:
        """Return a read-only copy of the underlying molecule."""
        return Chem.Mol(self._mol)

    # ------------------------------------------------------------------
    # Read access
    # ------------------------------------------------------------------

    @property
    def revision(self) -> int:
        """Incremented on every change; useful for caches in views."""
        return self._revision

    @property
    def atom_count(self) -> int:
        return int(self._mol.GetNumAtoms())

    @property
    def bond_count(self) -> int:
        return int(self._mol.GetNumBonds())

    def is_empty(self) -> bool:
        return self.atom_count == 0

    def atom_symbol(self, atom_idx: int) -> str:
        return str(self._mol.GetAtomWithIdx(atom_idx).GetSymbol())

    def atom_charge(self, atom_idx: int) -> int:
        return int(self._mol.GetAtomWithIdx(atom_idx).GetFormalCharge())

    def atom_position(self, atom_idx: int) -> tuple[float, float]:
        pos = self._mol.GetConformer().GetAtomPosition(atom_idx)
        return (pos.x, pos.y)

    def atom_neighbors(self, atom_idx: int) -> list[int]:
        return [n.GetIdx() for n in self._mol.GetAtomWithIdx(atom_idx).GetNeighbors()]

    def atom_degree(self, atom_idx: int) -> int:
        return int(self._mol.GetAtomWithIdx(atom_idx).GetDegree())

    def bond_atoms(self, bond_idx: int) -> tuple[int, int]:
        bond = self._mol.GetBondWithIdx(bond_idx)
        return (bond.GetBeginAtomIdx(), bond.GetEndAtomIdx())

    def bond_order(self, bond_idx: int) -> int:
        bond_type = self._mol.GetBondWithIdx(bond_idx).GetBondType()
        if bond_type == Chem.BondType.DOUBLE:
            return 2
        if bond_type == Chem.BondType.TRIPLE:
            return 3
        return 1

    def bond_stereo(self, bond_idx: int) -> str:
        direction = self._mol.GetBondWithIdx(bond_idx).GetBondDir()
        if direction == Chem.BondDir.BEGINWEDGE:
            return STEREO_WEDGE
        if direction == Chem.BondDir.BEGINDASH:
            return STEREO_HASH
        if direction == Chem.BondDir.UNKNOWN:
            return STEREO_WAVY
        return STEREO_NONE

    def find_bond(self, atom_a: int, atom_b: int) -> int | None:
        bond = self._mol.GetBondBetweenAtoms(atom_a, atom_b)
        return None if bond is None else bond.GetIdx()

    def atom_bonds(self, atom_idx: int) -> list[int]:
        return [b.GetIdx() for b in self._mol.GetAtomWithIdx(atom_idx).GetBonds()]

    def implicit_hydrogens(self, atom_idx: int) -> int:
        """Hydrogens shown in the atom label (implicit + explicit H count)."""
        atom = self._mol.GetAtomWithIdx(atom_idx)
        return int(atom.GetNumImplicitHs() + atom.GetNumExplicitHs())

    def invalid_atom_indices(self) -> set[int]:
        """Atoms whose explicit valence exceeds what the element allows."""
        if self.atom_count == 0:
            return set()
        mol = Chem.Mol(self._mol)
        with _quiet_rdkit():
            problems = Chem.DetectChemistryProblems(mol)
        bad: set[int] = set()
        for problem in problems:
            if problem.GetType() == "AtomValenceException":
                bad.add(problem.GetAtomIdx())
        return bad

    def bond_ring_center(self, bond_idx: int) -> tuple[float, float] | None:
        """Centre of the smallest ring containing *bond_idx* (``None`` if acyclic)."""
        rings = self._bond_rings()
        best: tuple[int, ...] | None = None
        for ring_atoms, ring_bonds in rings:
            if bond_idx in ring_bonds and (best is None or len(ring_atoms) < len(best)):
                best = ring_atoms
        if best is None:
            return None
        xs, ys = zip(*(self.atom_position(i) for i in best), strict=True)
        return (sum(xs) / len(xs), sum(ys) / len(ys))

    def _bond_rings(self) -> list[tuple[tuple[int, ...], tuple[int, ...]]]:
        cache = self._ring_cache
        if cache is not None and cache[0] == self._revision:
            return cache[1]
        mol = Chem.Mol(self._mol)
        with _quiet_rdkit():
            Chem.FastFindRings(mol)
            Chem.GetSymmSSSR(mol)
        info = mol.GetRingInfo()
        rings: list[tuple[tuple[int, ...], tuple[int, ...]]] = list(
            zip(info.AtomRings(), info.BondRings(), strict=True)
        )
        self._ring_cache = (self._revision, rings)
        return rings

    def molecular_formula(self) -> str:
        """Hill formula with Unicode subscripts (e.g. ``C₂H₆O``)."""
        if self.atom_count == 0:
            return ""
        mol = Chem.Mol(self._mol)
        with _quiet_rdkit():
            mol.UpdatePropertyCache(strict=False)
            return format_formula(rdMolDescriptors.CalcMolFormula(mol))

    def molecular_weight(self) -> float:
        if self.atom_count == 0:
            return 0.0
        mol = Chem.Mol(self._mol)
        with _quiet_rdkit():
            mol.UpdatePropertyCache(strict=False)
            return float(Descriptors.MolWt(mol))  # type: ignore[attr-defined, unused-ignore]

    def bounds(self) -> tuple[float, float, float, float] | None:
        """``(min_x, min_y, max_x, max_y)`` of all atoms, ``None`` when empty."""
        if self.atom_count == 0:
            return None
        xs, ys = zip(*(self.atom_position(i) for i in range(self.atom_count)), strict=True)
        return (min(xs), min(ys), max(xs), max(ys))

    def fragment_atoms(self, atom_idx: int) -> list[int]:
        """All atom indices in the connected component of *atom_idx*."""
        seen = {atom_idx}
        queue = deque([atom_idx])
        while queue:
            current = queue.popleft()
            for nbr in self.atom_neighbors(current):
                if nbr not in seen:
                    seen.add(nbr)
                    queue.append(nbr)
        return sorted(seen)

    def nearest_atom(
        self, x: float, y: float, tolerance: float, *, exclude: Iterable[int] = ()
    ) -> int | None:
        excluded = set(exclude)
        best: int | None = None
        best_d = tolerance
        for i in range(self.atom_count):
            if i in excluded:
                continue
            ax, ay = self.atom_position(i)
            d = math.hypot(ax - x, ay - y)
            if d <= best_d:
                best, best_d = i, d
        return best

    # ------------------------------------------------------------------
    # Undo / redo
    # ------------------------------------------------------------------

    def checkpoint(self) -> None:
        """Record the current state so the next change(s) can be undone at once."""
        self._push_undo()

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(Chem.RWMol(self._mol))
        self._set_mol(self._undo.pop())
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(Chem.RWMol(self._mol))
        self._set_mol(self._redo.pop())
        return True

    def clear(self) -> None:
        """Remove every atom (undoable)."""
        if self.atom_count == 0:
            return
        self._push_undo()
        self._set_mol(self._empty_mol())

    @contextmanager
    def compound(self) -> Iterator[None]:
        """Group several edits into a single undo step."""
        if self._compound_depth == 0:
            self._push_undo()
        self._compound_depth += 1
        try:
            yield
        finally:
            self._compound_depth -= 1

    def _push_undo(self) -> None:
        if self._compound_depth:
            return
        self._undo.append(Chem.RWMol(self._mol))
        self._redo.clear()

    def _set_mol(self, mol: Chem.RWMol) -> None:
        if mol.GetNumConformers() == 0:
            mol.AddConformer(Chem.Conformer(mol.GetNumAtoms()), assignId=True)
        self._mol = mol
        self._touch()

    def _touch(self) -> None:
        self._normalize_hypervalent_nitrogen()
        self._apply_auto_charges()
        with _quiet_rdkit():
            self._mol.UpdatePropertyCache(strict=False)
        self._revision += 1

    @staticmethod
    def _bond_valence(atom: Chem.Atom) -> int:
        """Bonds to heavy atoms plus hydrogens fixed on the atom."""
        total = sum(int(round(b.GetBondTypeAsDouble())) for b in atom.GetBonds())
        if atom.GetNoImplicit():
            total += atom.GetNumExplicitHs()
        return total

    def _auto_charge_for(self, atom: Chem.Atom) -> int:
        key = (atom.GetSymbol(), self._bond_valence(atom))
        if key in _AUTO_CHARGES:
            return _AUTO_CHARGES[key]
        if key in _AUTO_CHARGES_ALL_SINGLE and all(
            b.GetBondType() == Chem.BondType.SINGLE for b in atom.GetBonds()
        ):
            return _AUTO_CHARGES_ALL_SINGLE[key]
        return 0

    @staticmethod
    def _clear_charge_marks(atom: Chem.Atom) -> None:
        for prop in (_AUTO_CHARGE, _MANUAL_CHARGE, _AUTO_ZWITTER):
            if atom.HasProp(prop):
                atom.ClearProp(prop)

    def _normalize_hypervalent_nitrogen(self) -> None:
        """Convert pentavalent neutral N(=O)=O, R3N=O, pyN=O or R2C=N(R)=O to N⁺–O⁻."""
        for atom in self._mol.GetAtoms():
            if (
                atom.GetSymbol() != "N"
                or atom.GetFormalCharge() != 0
                or atom.HasProp(_MANUAL_CHARGE)
                or atom.GetNumRadicalElectrons()
                or self._bond_valence(atom) != 5
            ):
                continue
            candidates = [
                b
                for b in atom.GetBonds()
                if b.GetBondType() == Chem.BondType.DOUBLE
                for other in [b.GetOtherAtom(atom)]
                if (
                    other.GetSymbol() in ("O", "S")
                    and other.GetDegree() == 1
                    and other.GetFormalCharge() == 0
                    and not other.HasProp(_MANUAL_CHARGE)
                    and not other.GetNumRadicalElectrons()
                    and not (other.GetNoImplicit() and other.GetNumExplicitHs())
                )
            ]
            if not candidates:
                continue
            candidates.sort(key=lambda b: (b.GetOtherAtom(atom).GetSymbol() != "O", -b.GetIdx()))
            bond = candidates[0]
            other = bond.GetOtherAtom(atom)
            bond.SetBondType(Chem.BondType.SINGLE)
            bond.SetStereo(Chem.BondStereo.STEREONONE)
            other.SetFormalCharge(-1)
            other.SetBoolProp(_AUTO_ZWITTER, True)
            if other.GetSymbol() in _IMPLICIT_H_ELEMENTS and not other.GetNoImplicit():
                other.SetNumExplicitHs(0)

    @staticmethod
    def _is_zwitter_partner(atom: Chem.Atom) -> bool:
        """True when an automatic -1 partner is still paired with its auto N⁺/O⁺."""
        if (
            atom.GetFormalCharge() != -1
            or not atom.HasProp(_AUTO_ZWITTER)
            or atom.GetDegree() != 1
            or atom.GetNumRadicalElectrons()
            or (atom.GetNoImplicit() and atom.GetNumExplicitHs())
        ):
            return False
        bond = atom.GetBonds()[0]
        nbr = bond.GetOtherAtom(atom)
        if nbr.GetFormalCharge() != 1 or not nbr.HasProp(_AUTO_CHARGE):
            return False
        order = int(round(bond.GetBondTypeAsDouble()))
        sym = atom.GetSymbol()
        if sym in ("O", "S") and order == 1 and nbr.GetSymbol() == "N":
            return True
        if sym == "N" and order == 2 and nbr.GetSymbol() == "N":
            return True
        return sym == "C" and order == 3 and nbr.GetSymbol() in ("N", "O")

    def _apply_auto_charges(self) -> None:
        """Maintain automatic formal charges from bond counts and valence rules."""
        for atom in self._mol.GetAtoms():
            charge = atom.GetFormalCharge()
            # Alkylating/bonding onto an anion past its octet neutralizes it
            # (e.g. R-COO⁻ + Me → R-COOMe, Cl⁻ + C → R-Cl).
            if charge < 0 and not atom.GetNumRadicalElectrons():
                max_anion = _MAX_ANION_BONDS.get(atom.GetSymbol())
                if max_anion is not None:
                    valence = self._bond_valence(atom)
                    if valence > max_anion:
                        new_charge = min(0, charge + (valence - max_anion))
                        if new_charge != charge:
                            atom.SetFormalCharge(new_charge)
                            if new_charge == 0:
                                self._clear_charge_marks(atom)
                            if (
                                atom.GetSymbol() in _IMPLICIT_H_ELEMENTS
                                and not atom.GetNoImplicit()
                            ):
                                atom.SetNumExplicitHs(0)
            if atom.HasProp(_MANUAL_CHARGE) or atom.HasProp(_AUTO_ZWITTER):
                continue
            if atom.GetNumRadicalElectrons():
                continue
            wanted = self._auto_charge_for(atom)
            current = atom.GetFormalCharge()
            is_auto = atom.HasProp(_AUTO_CHARGE)
            if current == wanted:
                if wanted and not is_auto:
                    atom.SetBoolProp(_AUTO_CHARGE, True)
                continue
            if current != 0 and not is_auto:
                continue  # a charge the user (or the file) chose stays
            atom.SetFormalCharge(wanted)
            if wanted:
                atom.SetBoolProp(_AUTO_CHARGE, True)
            elif is_auto:
                atom.ClearProp(_AUTO_CHARGE)
            if atom.GetSymbol() in _IMPLICIT_H_ELEMENTS and not atom.GetNoImplicit():
                atom.SetNumExplicitHs(0)

        # Revert stale zwitterionic negative charges, then pair new ones
        # (azides R-N=[N+]=[N-], diazo R2C=[N+]=[N-], isocyanides R-[N+]#[C-]).
        for atom in self._mol.GetAtoms():
            if atom.HasProp(_AUTO_ZWITTER) and not self._is_zwitter_partner(atom):
                atom.ClearProp(_AUTO_ZWITTER)
                if atom.GetFormalCharge() == -1:
                    atom.SetFormalCharge(0)
                    if atom.GetSymbol() in _IMPLICIT_H_ELEMENTS and not atom.GetNoImplicit():
                        atom.SetNumExplicitHs(0)

        for center in self._mol.GetAtoms():
            if (
                center.GetFormalCharge() != 1
                or not center.HasProp(_AUTO_CHARGE)
                or center.HasProp(_MANUAL_CHARGE)
                or any(n.GetFormalCharge() < 0 for n in center.GetNeighbors())
            ):
                continue
            candidates = [
                b
                for b in center.GetBonds()
                for other in [b.GetOtherAtom(center)]
                if (
                    other.GetDegree() == 1
                    and other.GetFormalCharge() == 0
                    and not other.HasProp(_MANUAL_CHARGE)
                    and not other.HasProp(_AUTO_CHARGE)
                    and not other.GetNumRadicalElectrons()
                    and not (other.GetNoImplicit() and other.GetNumExplicitHs())
                    and (
                        (
                            center.GetSymbol() == "N"
                            and other.GetSymbol() == "N"
                            and b.GetBondType() == Chem.BondType.DOUBLE
                        )
                        or (
                            center.GetSymbol() in ("N", "O")
                            and other.GetSymbol() == "C"
                            and b.GetBondType() == Chem.BondType.TRIPLE
                        )
                    )
                )
            ]
            if not candidates:
                continue
            candidates.sort(key=lambda b: -b.GetIdx())
            other = candidates[0].GetOtherAtom(center)
            other.SetFormalCharge(-1)
            other.SetBoolProp(_AUTO_ZWITTER, True)
            if other.GetSymbol() in _IMPLICIT_H_ELEMENTS and not other.GetNoImplicit():
                other.SetNumExplicitHs(0)

    def _mark_loaded_charges(self) -> None:
        """Charges read from SMILES/MOL count as automatic when the rules agree."""
        for atom in self._mol.GetAtoms():
            if atom.GetFormalCharge() == 0:
                continue
            if self._auto_charge_for(atom) == atom.GetFormalCharge():
                atom.SetBoolProp(_AUTO_CHARGE, True)
            else:
                atom.SetBoolProp(_MANUAL_CHARGE, True)

    def _mark_manual_charge(self, atom: Chem.Atom) -> None:
        for prop in (_AUTO_CHARGE, _AUTO_ZWITTER):
            if atom.HasProp(prop):
                atom.ClearProp(prop)
        atom.SetBoolProp(_MANUAL_CHARGE, True)

    # ------------------------------------------------------------------
    # Low-level helpers (no undo)
    # ------------------------------------------------------------------

    @staticmethod
    def _make_atom(symbol: str) -> Chem.Atom:
        if not is_element_symbol(symbol):
            raise ValueError(f"Unknown element symbol: {symbol!r}")
        atom = Chem.Atom(symbol)
        atom.SetNoImplicit(symbol not in _IMPLICIT_H_ELEMENTS)
        return atom

    def _add_atom(self, atom: Chem.Atom, x: float, y: float) -> int:
        idx = self._mol.AddAtom(atom)
        self._mol.GetConformer().SetAtomPosition(idx, Point3D(x, y, 0.0))
        return int(idx)

    def _set_position(self, atom_idx: int, x: float, y: float) -> None:
        self._mol.GetConformer().SetAtomPosition(atom_idx, Point3D(x, y, 0.0))

    def _add_bond(self, a: int, b: int, order: int = 1, stereo_dir: str = STEREO_NONE) -> int:
        self._mol.AddBond(a, b, _ORDER_TO_TYPE.get(order, Chem.BondType.SINGLE))
        bond = self._mol.GetBondBetweenAtoms(a, b)
        bond.SetBondDir(_STEREO_TO_DIR.get(stereo_dir, Chem.BondDir.NONE))
        return int(bond.GetIdx())

    def _sprout_direction(
        self,
        atom_idx: int,
        *,
        bond_order: int = 1,
        preferred_angle: float | None = None,
    ) -> float:
        """Angle (radians) for a new bond leaving *atom_idx*."""
        if preferred_angle is not None:
            return math.radians(preferred_angle)
        ax, ay = self.atom_position(atom_idx)
        nbrs = self.atom_neighbors(atom_idx)
        if not nbrs:
            return math.radians(30.0)
        chair = self._chair_sprout(atom_idx)
        if chair is not None:
            return chair
        angles = []
        for n in nbrs:
            nx, ny = self.atom_position(n)
            angles.append(_angle_of(nx - ax, ny - ay))
        if len(nbrs) == 1:
            back = angles[0]
            incoming = back + math.pi
            existing = self._mol.GetBondBetweenAtoms(atom_idx, nbrs[0]).GetBondType()
            if bond_order == 3 or existing == Chem.BondType.TRIPLE:
                return _normalize(incoming)
            candidates = [_normalize(incoming + math.pi / 3), _normalize(incoming - math.pi / 3)]
            grand = [g for g in self.atom_neighbors(nbrs[0]) if g != atom_idx]
            if grand:
                # Zig-zag: place the new atom trans to the grandparent.
                nx, ny = self.atom_position(nbrs[0])
                gx, gy = self.atom_position(grand[0])
                axis = (ax - nx, ay - ny)
                g_side = axis[0] * (gy - ny) - axis[1] * (gx - nx)
                for cand in candidates:
                    cx, cy = ax + math.cos(cand), ay + math.sin(cand)
                    c_side = axis[0] * (cy - ny) - axis[1] * (cx - nx)
                    if c_side * g_side < 0:
                        return self._least_crowded(atom_idx, [cand] + candidates)
            # No grandparent: prefer the more horizontal zig-zag.
            candidates.sort(key=lambda a: abs(math.sin(a)))
            return self._least_crowded(atom_idx, candidates)
        if len(nbrs) == 2:
            ux = sum(math.cos(a) for a in angles)
            uy = sum(math.sin(a) for a in angles)
            if math.hypot(ux, uy) < 1e-6:
                return _normalize(angles[0] + math.pi / 2)
            return _angle_of(-ux, -uy)
        ordered = sorted(_normalize(a) for a in angles)
        gaps: list[tuple[float, float]] = []
        for i, start in enumerate(ordered):
            end = ordered[(i + 1) % len(ordered)]
            gap = (end - start) % (2 * math.pi)
            if gap == 0:
                gap = 2 * math.pi
            gaps.append((gap, _normalize(start + gap / 2)))
        best_gap = max(gap for gap, _mid in gaps)
        # Equally wide gaps (a branched group being built): take the one
        # that does not land on a neighbour's substituent.
        widest = [mid for gap, mid in gaps if gap > best_gap - math.radians(1.0)]
        return self._least_crowded(atom_idx, widest)

    def _least_crowded(self, atom_idx: int, candidates: list[float]) -> float:
        """Return the first candidate unless it lands on top of another atom."""
        ax, ay = self.atom_position(atom_idx)
        best = candidates[0]
        best_score = -1.0
        for cand in candidates:
            px = ax + BOND_LENGTH * math.cos(cand)
            py = ay + BOND_LENGTH * math.sin(cand)
            score = min(
                (
                    math.hypot(px - bx, py - by)
                    for i in range(self.atom_count)
                    if i != atom_idx
                    for bx, by in [self.atom_position(i)]
                ),
                default=math.inf,
            )
            if score >= 0.5 * BOND_LENGTH:
                return cand
            if score > best_score:
                best, best_score = cand, score
        return best

    def _sprout(
        self,
        from_atom_idx: int,
        atom: Chem.Atom,
        bond_order: int,
        stereo_dir: str,
        preferred_angle: float | None,
        length: float | None = None,
    ) -> int:
        angle = self._sprout_direction(
            from_atom_idx, bond_order=bond_order, preferred_angle=preferred_angle
        )
        ax, ay = self.atom_position(from_atom_idx)
        bond_length = BOND_LENGTH if length is None else max(0.4 * BOND_LENGTH, float(length))
        x = ax + bond_length * math.cos(angle)
        y = ay + bond_length * math.sin(angle)
        existing = self.nearest_atom(x, y, 0.25 * BOND_LENGTH, exclude=[from_atom_idx])
        if existing is not None and self.find_bond(from_atom_idx, existing) is None:
            self._add_bond(from_atom_idx, existing, bond_order, stereo_dir)
            return existing
        new_idx = self._add_atom(atom, x, y)
        self._add_bond(from_atom_idx, new_idx, bond_order, stereo_dir)
        return new_idx

    # ------------------------------------------------------------------
    # Atom editing
    # ------------------------------------------------------------------

    def add_free_atom(self, x: float, y: float, symbol: str = "C") -> int:
        atom = self._make_atom(symbol)
        self._push_undo()
        idx = self._add_atom(atom, x, y)
        self._touch()
        return idx

    def set_atom_symbol(self, atom_idx: int, symbol: str) -> None:
        template = self._make_atom(symbol)
        atom = self._mol.GetAtomWithIdx(atom_idx)
        if atom.GetSymbol() == symbol and atom.GetFormalCharge() == 0:
            return
        self._push_undo()
        atom.SetAtomicNum(template.GetAtomicNum())
        atom.SetFormalCharge(0)
        self._clear_charge_marks(atom)
        atom.SetIsotope(0)
        atom.SetNumExplicitHs(0)
        atom.SetNoImplicit(template.GetNoImplicit())
        atom.SetIsAromatic(False)
        atom.SetChiralTag(Chem.ChiralType.CHI_UNSPECIFIED)
        self._touch()

    def set_atom_charge(
        self,
        atom_idx: int,
        delta_or_value: int,
        relative: bool = True,  # noqa: FBT001, FBT002
    ) -> None:
        atom = self._mol.GetAtomWithIdx(atom_idx)
        value = atom.GetFormalCharge() + delta_or_value if relative else delta_or_value
        value = max(-8, min(8, int(value)))
        if value == atom.GetFormalCharge():
            return
        self._push_undo()
        atom.SetFormalCharge(value)
        self._mark_manual_charge(atom)
        atom.SetNumExplicitHs(0)
        atom.SetNoImplicit(atom.GetSymbol() not in _IMPLICIT_H_ELEMENTS)
        self._touch()

    def move_atom(self, atom_idx: int, x: float, y: float, record_undo: bool = False) -> None:  # noqa: FBT001, FBT002
        if record_undo:
            self._push_undo()
        self._set_position(atom_idx, x, y)
        self._touch()

    def move_fragment(
        self,
        atom_idx: int | Iterable[int],
        dx: float,
        dy: float,
        record_undo: bool = False,  # noqa: FBT001, FBT002
    ) -> None:
        """Translate the fragment containing *atom_idx* (or the given atom list)."""
        atoms = self.fragment_atoms(atom_idx) if isinstance(atom_idx, int) else list(atom_idx)
        if record_undo:
            self._push_undo()
        for i in atoms:
            x, y = self.atom_position(i)
            self._set_position(i, x + dx, y + dy)
        self._touch()

    def delete_atom(self, atom_idx: int) -> None:
        self._push_undo()
        self._mol.RemoveAtom(atom_idx)
        self._touch()

    def delete_atoms(self, atom_indices: Iterable[int]) -> None:
        indices = sorted(set(atom_indices), reverse=True)
        if not indices:
            return
        self._push_undo()
        for idx in indices:
            self._mol.RemoveAtom(idx)
        self._touch()

    def attachment_points(self) -> list[int]:
        """Atoms drawn as ``*``: where a custom group attaches."""
        return [a.GetIdx() for a in self._mol.GetAtoms() if a.GetAtomicNum() == 0]

    def toggle_attachment_point(self, atom_idx: int) -> int | None:
        """Mark *atom_idx* as the atom a custom group attaches through.

        The mark is a ``*`` atom bonded to it (a group has one, so any other
        mark is removed). Clicking the ``*`` itself, or an atom that already
        carries it, removes the mark. Returns the ``*`` atom, or ``None``.
        """
        atom = self._mol.GetAtomWithIdx(atom_idx)
        marks = self.attachment_points()
        own = [n.GetIdx() for n in atom.GetNeighbors() if n.GetAtomicNum() == 0]
        if atom.GetAtomicNum() == 0 or own:
            self.delete_atoms([atom_idx] if atom.GetAtomicNum() == 0 else own)
            return None
        dummy = Chem.Atom(0)
        dummy.SetNoImplicit(True)
        with self.compound():
            idx = self._sprout(atom_idx, dummy, 1, STEREO_NONE, None)
            if marks:
                self._mol.BeginBatchEdit()
                for mark in marks:
                    self._mol.RemoveAtom(mark)
                self._mol.CommitBatchEdit()
                idx = self.attachment_points()[0]
            self._touch()
        return idx

    def delete_bond(self, bond_idx: int) -> None:
        a, b = self.bond_atoms(bond_idx)
        self._push_undo()
        self._mol.RemoveBond(a, b)
        self._touch()

    # ------------------------------------------------------------------
    # Bond editing
    # ------------------------------------------------------------------

    def sprout_atom(
        self,
        from_atom_idx: int,
        symbol: str = "C",
        bond_order: int = 1,
        stereo_dir: str = STEREO_NONE,
        preferred_angle: float | None = None,
        length: float | None = None,
    ) -> int:
        """Add a new atom bonded to *from_atom_idx*; returns its index.

        *preferred_angle* is in degrees (y up).  Without it the direction
        follows the usual drawing conventions: a lone atom grows at +30°, a
        chain end continues as a trans zig-zag, a two-substituted atom grows
        along the outer bisector and a crowded atom into its largest gap.
        """
        atom = self._make_atom(symbol)
        self._push_undo()
        idx = self._sprout(from_atom_idx, atom, bond_order, stereo_dir, preferred_angle, length)
        self._touch()
        return idx

    def add_or_update_bond(
        self,
        atom_a: int,
        atom_b: int,
        order: int = 1,
        stereo_dir: str = STEREO_NONE,
        cycle_on_existing: bool = True,  # noqa: FBT001, FBT002
    ) -> int:
        """Create a bond, or change an existing one.

        With ``cycle_on_existing`` an existing bond clicked with the same
        single-bond tool cycles 1 → 2 → 3 → 1.  Re-applying the same wedge or
        hash flips its direction.
        """
        if atom_a == atom_b:
            raise ValueError("Cannot bond an atom to itself")
        bond = self._mol.GetBondBetweenAtoms(atom_a, atom_b)
        self._push_undo()
        if bond is None:
            idx = self._add_bond(atom_a, atom_b, order, stereo_dir)
            self._touch()
            return idx
        current = self.bond_order(bond.GetIdx())
        current_stereo = self.bond_stereo(bond.GetIdx())
        if stereo_dir != STEREO_NONE:
            begin = bond.GetBeginAtomIdx()
            if current_stereo == stereo_dir and begin == atom_a:
                atom_a, atom_b = atom_b, atom_a  # flip the wedge
            if atom_a == begin:
                bond.SetBondType(Chem.BondType.SINGLE)
                bond.SetBondDir(_STEREO_TO_DIR.get(stereo_dir, Chem.BondDir.NONE))
                bond.SetIsAromatic(False)
                bond.SetStereo(Chem.BondStereo.STEREONONE)
                self._touch()
                return int(bond.GetIdx())
            bold = bond.HasProp(_BOLD)
            self._mol.RemoveBond(begin, bond.GetEndAtomIdx())
            idx = self._add_bond(atom_a, atom_b, 1, stereo_dir)
            if bold:
                self._mol.GetBondWithIdx(idx).SetBoolProp(_BOLD, True)
            self._touch()
            return idx
        if cycle_on_existing and order == current and current_stereo == STEREO_NONE:
            new_order = {1: 2, 2: 3, 3: 1}[current]
        elif cycle_on_existing and order == 1 and current_stereo == STEREO_NONE:
            new_order = {1: 2, 2: 3, 3: 1}[current]
        else:
            new_order = order
        bond.SetBondType(_ORDER_TO_TYPE[new_order])
        bond.SetBondDir(Chem.BondDir.NONE)
        bond.SetIsAromatic(False)
        bond.SetStereo(Chem.BondStereo.STEREONONE)
        self._touch()
        return int(bond.GetIdx())

    def set_bond_order(self, bond_idx: int, order: int) -> None:
        a, b = self.bond_atoms(bond_idx)
        self.add_or_update_bond(a, b, order, cycle_on_existing=False)

    def set_bond_stereo(self, bond_idx: int, stereo_dir: str) -> None:
        a, b = self.bond_atoms(bond_idx)
        if stereo_dir == STEREO_NONE:
            self.add_or_update_bond(a, b, 1, cycle_on_existing=False)
        else:
            self.add_or_update_bond(a, b, 1, stereo_dir)

    def add_chain(
        self,
        start_x: float,
        start_y: float,
        end_x: float,
        end_y: float,
        start_atom_idx: int | None = None,
    ) -> list[int]:
        """Draw a zig-zag carbon chain from start to end; returns new atom indices.

        The number of bonds is ``max(1, round(dist / (BOND_LENGTH·cos 30°)))``.
        """
        points = self.chain_coordinates(start_x, start_y, end_x, end_y, start_atom_idx)
        self._push_undo()
        created: list[int] = []
        if start_atom_idx is None:
            prev = self._add_atom(self._make_atom("C"), *points[0])
            created.append(prev)
        else:
            prev = start_atom_idx
        for x, y in points[1:]:
            idx = self._add_atom(self._make_atom("C"), x, y)
            self._add_bond(prev, idx, 1)
            created.append(idx)
            prev = idx
        self._touch()
        return created

    def chain_coordinates(
        self,
        start_x: float,
        start_y: float,
        end_x: float,
        end_y: float,
        start_atom_idx: int | None = None,
    ) -> list[tuple[float, float]]:
        """Zig-zag points (start included) that :meth:`add_chain` would create."""
        if start_atom_idx is not None:
            start_x, start_y = self.atom_position(start_atom_idx)
        n_bonds = self.chain_length(start_x, start_y, end_x, end_y)
        dx, dy = end_x - start_x, end_y - start_y
        dist = math.hypot(dx, dy)
        if dist < 1e-9:
            ux, uy = 1.0, 0.0
        else:
            ux, uy = dx / dist, dy / dist
        vx, vy = -uy, ux  # left normal
        side = 1.0
        if start_atom_idx is not None:
            nbrs = self.atom_neighbors(start_atom_idx)
            if nbrs:
                nx, ny = self.atom_position(nbrs[0])
                rel = (nx - start_x) * vx + (ny - start_y) * vy
                side = -1.0 if rel > 0 else 1.0
        elif vy < 0:
            side = -1.0  # first zig points up
        step = BOND_LENGTH * math.cos(math.radians(30))
        offset = BOND_LENGTH * math.sin(math.radians(30))
        points = [(start_x, start_y)]
        for k in range(1, n_bonds + 1):
            h = offset * side if k % 2 == 1 else 0.0
            points.append((start_x + ux * step * k + vx * h, start_y + uy * step * k + vy * h))
        return points

    @staticmethod
    def chain_length(start_x: float, start_y: float, end_x: float, end_y: float) -> int:
        dist = math.hypot(end_x - start_x, end_y - start_y)
        return max(1, round(dist / (BOND_LENGTH * math.cos(math.radians(30)))))

    # ------------------------------------------------------------------
    # Templates
    # ------------------------------------------------------------------

    def ring_template_coordinates(
        self,
        ring_type: str,
        *,
        center: tuple[float, float] | None = None,
        target_atom_idx: int | None = None,
        target_bond_idx: int | None = None,
    ) -> list[tuple[float, float]]:
        """Where the ring atoms would go (for ghost previews); nothing is changed."""
        target_atom_idx, target_bond_idx = self._ring_target(
            ring_type, target_atom_idx, target_bond_idx
        )
        template, coords, _mapping = self._place_ring(
            ring_type,
            center=center,
            target_atom_idx=target_atom_idx,
            target_bond_idx=target_bond_idx,
        )
        del template
        return coords

    @staticmethod
    def ring_template_symbols(ring_type: str) -> list[str]:
        """Element symbol of every template atom (same order as the coordinates)."""
        template = _template_mol(ring_type)
        return [atom.GetSymbol() for atom in template.GetAtoms()]

    @staticmethod
    def ring_template_bonds(ring_type: str) -> list[tuple[int, int, int]]:
        """``(atom_a, atom_b, order)`` of a template, matching the preview coordinates."""
        template = _template_mol(ring_type)
        return [
            (
                b.GetBeginAtomIdx(),
                b.GetEndAtomIdx(),
                2 if b.GetBondType() == Chem.BondType.DOUBLE else 1,
            )
            for b in template.GetBonds()
        ]

    def add_ring_template(
        self,
        ring_type: str,
        *,
        center: tuple[float, float] | None = None,
        target_atom_idx: int | None = None,
        target_bond_idx: int | None = None,
    ) -> list[int]:
        """Add a ring; returns the model indices of all ring atoms.

        * ``target_bond_idx`` fuses the ring onto that bond, on the less
          crowded side.
        * ``target_atom_idx`` attaches the ring through a new single bond (or,
          for a lone atom, builds the ring through it).
        * otherwise the ring is centred at *center* (or next to the drawing).
        """
        target_atom_idx, target_bond_idx = self._ring_target(
            ring_type, target_atom_idx, target_bond_idx
        )
        template, coords, mapping = self._place_ring(
            ring_type,
            center=center,
            target_atom_idx=target_atom_idx,
            target_bond_idx=target_bond_idx,
        )
        spec = RING_TEMPLATES[ring_type]
        self._push_undo()
        index_map: dict[int, int] = {}
        for t_atom in template.GetAtoms():
            t_idx = t_atom.GetIdx()
            if t_idx in mapping:
                index_map[t_idx] = mapping[t_idx]
                continue
            x, y = coords[t_idx]
            existing = self.nearest_atom(x, y, 0.3 * BOND_LENGTH)
            if existing is not None:
                index_map[t_idx] = existing
                continue
            atom = Chem.Atom(t_atom)
            atom.SetNoImplicit(atom.GetSymbol() not in _IMPLICIT_H_ELEMENTS)
            atom.SetNumExplicitHs(0)
            # Stereo comes from the copied wedges, which do not depend on the
            # order neighbours are added in (chiral tags do).
            atom.SetChiralTag(Chem.ChiralType.CHI_UNSPECIFIED)
            index_map[t_idx] = self._add_atom(atom, x, y)
        new_bonds: list[int] = []
        for t_bond in template.GetBonds():
            a = index_map[t_bond.GetBeginAtomIdx()]
            b = index_map[t_bond.GetEndAtomIdx()]
            if a == b or self.find_bond(a, b) is not None:
                continue
            order = 2 if t_bond.GetBondType() == Chem.BondType.DOUBLE else 1
            new_bonds.append(self._add_bond(a, b, order))
            if t_bond.GetBondDir() != Chem.BondDir.NONE:
                self._mol.GetBondWithIdx(new_bonds[-1]).SetBondDir(t_bond.GetBondDir())
            pair = (t_bond.GetBeginAtomIdx(), t_bond.GetEndAtomIdx())
            if pair in spec.bold_bonds or pair[::-1] in spec.bold_bonds:
                self._mol.GetBondWithIdx(new_bonds[-1]).SetBoolProp(_BOLD, True)
        if target_atom_idx is not None and target_atom_idx not in index_map.values():
            self._add_bond(target_atom_idx, index_map[spec.attach_atom], 1)
        self._touch()
        if spec.aromatic and target_bond_idx is not None:
            self._rekekulize(set(index_map.values()))
        return [index_map[i] for i in range(template.GetNumAtoms())]

    def _place_ring(
        self,
        ring_type: str,
        *,
        center: tuple[float, float] | None,
        target_atom_idx: int | None,
        target_bond_idx: int | None,
    ) -> tuple[Chem.Mol, list[tuple[float, float]], dict[int, int]]:
        spec = RING_TEMPLATES[ring_type] if ring_type in RING_TEMPLATES else None
        template = _template_mol(ring_type)
        assert spec is not None
        conf = template.GetConformer()
        pts = [
            complex(conf.GetAtomPosition(i).x, conf.GetAtomPosition(i).y)
            for i in range(template.GetNumAtoms())
        ]
        centroid = sum(pts) / len(pts)
        mapping: dict[int, int] = {}

        if target_bond_idx is not None:
            a, b = self.bond_atoms(target_bond_idx)
            qa = complex(*self.atom_position(a))
            qb = complex(*self.atom_position(b))
            t0, t1 = spec.fusion_bond
            p0, p1 = pts[t0], pts[t1]
            options = []
            # Direct and mirrored similarity transforms: the ring lands on
            # opposite sides of the bond.
            scale = (qb - qa) / (p1 - p0)
            options.append([qa + (p - p0) * scale for p in pts])
            scale_m = (qb - qa) / (p1 - p0).conjugate()
            options.append([qa + (p - p0).conjugate() * scale_m for p in pts])
            others = [
                complex(*self.atom_position(i)) for i in range(self.atom_count) if i not in (a, b)
            ]

            def crowding(placed: list[complex]) -> float:
                ring_center = sum(placed) / len(placed)
                if not others:
                    return 0.0
                return sum(1.0 / max(abs(ring_center - o), 0.1) ** 2 for o in others)

            placed = min(options, key=crowding)
            if placed is options[1]:
                _swap_wedges(template)
            mapping = {t0: a, t1: b}
        elif target_atom_idx is not None:
            anchor = complex(*self.atom_position(target_atom_idx))
            t_a = spec.attach_atom
            merged: int | None = None
            attach_atom = template.GetAtomWithIdx(t_a)
            if (
                not spec.fusable
                and self.atom_degree(target_atom_idx) > 0
                and self.atom_symbol(target_atom_idx) in ("O", "N", "S")
                and attach_atom.GetSymbol() == "O"
                and attach_atom.GetDegree() == 1
            ):
                # Sugar onto an OH / NH / SH: the target atom takes the place of
                # the anomeric OH oxygen, giving a glycoside instead of a peroxide.
                merged = t_a
                t_a = attach_atom.GetNeighbors()[0].GetIdx()
            outward = pts[t_a] - centroid
            outward /= abs(outward)
            if self.atom_degree(target_atom_idx) == 0:
                # Build the ring through the lone atom, ring body up-right.
                direction = cmath.exp(1j * math.radians(30.0))
                rotation = -direction / outward
                placed = [anchor + (p - pts[t_a]) * rotation for p in pts]
                mapping = {t_a: target_atom_idx}
            else:
                angle = self._sprout_direction(target_atom_idx)
                direction = cmath.exp(1j * angle)
                attach_pos = anchor + BOND_LENGTH * direction
                rotation = -direction / outward
                straight = [attach_pos + (p - pts[t_a]) * rotation for p in pts]
                # The mirror image about the new bond often clears a neighbour
                # (two rings side by side on a benzene, a crowded chain end).
                axis = direction
                mirrored = [
                    attach_pos + ((p - attach_pos) / axis).conjugate() * axis for p in straight
                ]
                others = [
                    complex(*self.atom_position(i))
                    for i in range(self.atom_count)
                    if i != target_atom_idx
                ]

                def clash(placed: list[complex]) -> float:
                    return sum(1.0 / max(abs(p - o), 0.2) ** 4 for p in placed for o in others)

                use_mirror = clash(mirrored) < clash(straight) / 1.001
                placed = mirrored if use_mirror else straight
                if _clearance(placed, others) < _CLEAR:
                    # Crowded (an ortho neighbour, a carbonyl O next to the
                    # attachment): turn the new bond a little.
                    turned = []
                    for step in _TURN_STEPS:
                        turn = cmath.exp(1j * math.radians(step))
                        pos = anchor + (attach_pos - anchor) * turn
                        rot = rotation * turn
                        option = [pos + (p - pts[t_a]) * rot for p in pts]
                        axis_t = direction * turn
                        turned.append((step, False, option))
                        turned.append(
                            (
                                step,
                                True,
                                [pos + ((p - pos) / axis_t).conjugate() * axis_t for p in option],
                            )
                        )
                    _step, use_mirror, placed = _least_clashing(turned, others, clash)
                if use_mirror:
                    _swap_wedges(template)
                if merged is not None:
                    placed[merged] = anchor
                    mapping = {merged: target_atom_idx}
        else:
            if center is None:
                bounds = self.bounds()
                if bounds is None:
                    target = complex(0.0, 0.0)
                else:
                    target = complex(bounds[2] + 3 * BOND_LENGTH, (bounds[1] + bounds[3]) / 2)
            else:
                target = complex(*center)
            placed = [target + (p - centroid) for p in pts]
        coords = [(p.real, p.imag) for p in placed]
        return template, coords, mapping

    def _ring_target(
        self, ring_type: str, target_atom_idx: int | None, target_bond_idx: int | None
    ) -> tuple[int | None, int | None]:
        """Building blocks that cannot be fused attach to the clicked bond's free end."""
        spec = RING_TEMPLATES.get(ring_type)
        if spec is None:
            raise ValueError(f"Unknown ring template: {ring_type!r}")
        if target_bond_idx is not None and not spec.fusable and target_atom_idx is None:
            a, b = self.bond_atoms(target_bond_idx)
            target_atom_idx = a if self.atom_degree(a) <= self.atom_degree(b) else b
            target_bond_idx = None
        return target_atom_idx, target_bond_idx

    def _rekekulize(self, atoms: set[int]) -> None:
        """Re-assign Kekulé bonds of a freshly fused aromatic system.

        Fusing an aromatic ring onto an existing bond can leave a shared atom
        with two double bonds.  Mark the involved (formerly aromatic) system
        aromatic again and let RDKit find a valid Kekulé structure.
        """
        if not (self.invalid_atom_indices() & atoms):
            return
        work = Chem.RWMol(self._mol)
        with _quiet_rdkit():
            try:
                probe = Chem.Mol(self._mol)
                for bond in probe.GetBonds():
                    bond.SetBondType(Chem.BondType.SINGLE)
                Chem.SanitizeMol(probe)
            except Exception:  # noqa: BLE001
                return
            rings = probe.GetRingInfo().BondRings()
            system: set[int] = set()
            for ring in rings:
                ring_atoms = {
                    a
                    for bidx in ring
                    for a in (
                        probe.GetBondWithIdx(bidx).GetBeginAtomIdx(),
                        probe.GetBondWithIdx(bidx).GetEndAtomIdx(),
                    )
                }
                if ring_atoms & atoms and len(ring) in (5, 6):
                    has_double = any(
                        self._mol.GetBondWithIdx(bidx).GetBondType() == Chem.BondType.DOUBLE
                        for bidx in ring
                    )
                    if has_double:
                        system.update(ring)
            for bidx in system:
                bond = work.GetBondWithIdx(bidx)
                bond.SetBondType(Chem.BondType.AROMATIC)
                bond.SetIsAromatic(True)
                for atom in (bond.GetBeginAtom(), bond.GetEndAtom()):
                    atom.SetIsAromatic(True)
                    if (
                        atom.GetSymbol() == "N"
                        and atom.GetDegree() == 2
                        and all(
                            b.GetIdx() in system or b.GetBondType() == Chem.BondType.SINGLE
                            for b in atom.GetBonds()
                        )
                        and self._mol.GetAtomWithIdx(atom.GetIdx()).GetTotalValence() == 2
                        and all(
                            self._mol.GetBondWithIdx(b.GetIdx()).GetBondType()
                            == Chem.BondType.SINGLE
                            for b in atom.GetBonds()
                        )
                    ):
                        atom.SetNumExplicitHs(1)
                        atom.SetNoImplicit(True)
            try:
                work.UpdatePropertyCache(strict=False)
                Chem.FastFindRings(work)
                Chem.Kekulize(work, clearAromaticFlags=True)
            except Exception:  # noqa: BLE001
                return
        for bidx in system:
            self._mol.GetBondWithIdx(bidx).SetBondType(work.GetBondWithIdx(bidx).GetBondType())
        self._touch()

    def attach_functional_group(
        self, atom_idx: int, group_key: str, angle: float | None = None
    ) -> list[int]:
        """Attach an IR-relevant group (``-OH``, ``-COOH``, ``-NO2`` …) to *atom_idx*.

        *angle* (degrees) sets the direction of the bond to the group.
        """
        if group_key not in FUNCTIONAL_GROUPS:
            raise ValueError(f"Unknown functional group: {group_key!r}")
        if group_key == "-Ph":
            if angle is not None:
                phenyl = parse_group("Ph")
                assert phenyl is not None
                return self.insert_fragment(phenyl, target_atom_idx=atom_idx, angle=angle)
            return self.add_ring_template("benzene", target_atom_idx=atom_idx)
        if group_key in _LAID_OUT_GROUPS:
            # Atom-by-atom sprouting crowds three branches on one atom into a
            # ring; these groups are placed with a computed layout instead.
            self._push_undo()
            return self._insert_group_layout(atom_idx, group_key, angle)
        with _quiet_rdkit():
            fragment = Chem.MolFromSmiles(FUNCTIONAL_GROUPS[group_key])
        Chem.Kekulize(fragment, clearAromaticFlags=True)
        self._push_undo()
        before = Chem.RWMol(self._mol)
        existing_atoms = self.atom_count
        index_map: dict[int, int] = {}
        root = fragment.GetAtomWithIdx(0)
        index_map[0] = self._sprout(atom_idx, self._copy_fragment_atom(root), 1, STEREO_NONE, angle)
        queue = deque([0])
        visited = {0}
        while queue:
            current = queue.popleft()
            nbr_bonds = sorted(
                fragment.GetAtomWithIdx(current).GetBonds(),
                key=lambda b: (-b.GetBondTypeAsDouble(), b.GetOtherAtomIdx(current)),
            )
            for bond in nbr_bonds:
                other = bond.GetOtherAtomIdx(current)
                if other in visited:
                    continue
                visited.add(other)
                order = int(bond.GetBondTypeAsDouble())
                index_map[other] = self._sprout(
                    index_map[current],
                    self._copy_fragment_atom(fragment.GetAtomWithIdx(other)),
                    order,
                    STEREO_NONE,
                    None,
                )
                queue.append(other)
        new_atoms = [
            complex(*self.atom_position(i)) for i in range(existing_atoms, self.atom_count)
        ]
        old_atoms = [
            complex(*self.atom_position(i)) for i in range(existing_atoms) if i != atom_idx
        ]
        if (
            any(idx < existing_atoms for idx in index_map.values())
            or _clearance(new_atoms, old_atoms) < _CLEAR
        ):
            # On a crowded atom a sprouted branch landed on (or next to) an
            # existing atom — CF₃ on a tertiary carbon used to close a
            # cyclopropane: place the whole group with a computed layout.
            self._set_mol(before)
            return self._insert_group_layout(atom_idx, group_key, angle)
        self._touch()
        return [index_map[i] for i in range(fragment.GetNumAtoms())]

    def _insert_group_layout(self, atom_idx: int, group_key: str, angle: float | None) -> list[int]:
        """Insert a group as one laid-out fragment, within the current undo step."""
        group = parse_group("*" + FUNCTIONAL_GROUPS[group_key])
        assert group is not None
        self._compound_depth += 1
        try:
            return self.insert_fragment(group, target_atom_idx=atom_idx, angle=angle)
        finally:
            self._compound_depth -= 1

    @staticmethod
    def _copy_fragment_atom(source: Chem.Atom) -> Chem.Atom:
        atom = Chem.Atom(source.GetSymbol())
        atom.SetFormalCharge(source.GetFormalCharge())
        atom.SetNoImplicit(source.GetSymbol() not in _IMPLICIT_H_ELEMENTS or source.GetNoImplicit())
        atom.SetNumExplicitHs(source.GetNumExplicitHs() if source.GetNoImplicit() else 0)
        return atom

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def clean_2d(self) -> bool:
        """Recompute a tidy 2D layout, keeping wedge stereo and the centroid."""
        if self.atom_count == 0:
            return False
        self._push_undo()
        self._compute_layout()
        return True

    def _compute_layout(self) -> None:
        old = [self.atom_position(i) for i in range(self.atom_count)]
        cx = sum(x for x, _ in old) / len(old)
        cy = sum(y for _, y in old) / len(old)
        work = Chem.Mol(self._mol)
        has_wedges = any(b.GetBondDir() != Chem.BondDir.NONE for b in work.GetBonds())
        with _quiet_rdkit():
            work.UpdatePropertyCache(strict=False)
            Chem.FastFindRings(work)
            if has_wedges:
                Chem.AssignChiralTypesFromBondDirs(work, replaceExistingTags=True)
            rdDepictor.Compute2DCoords(work)
            _arrange_components(work)
            for bond in work.GetBonds():
                bond.SetBondDir(Chem.BondDir.NONE)
            if has_wedges:
                Chem.WedgeMolBonds(work, work.GetConformer())
        conf = work.GetConformer()
        new = [(conf.GetAtomPosition(i).x, conf.GetAtomPosition(i).y) for i in range(len(old))]
        nx = sum(x for x, _ in new) / len(new)
        ny = sum(y for _, y in new) / len(new)
        for i, (x, y) in enumerate(new):
            self._set_position(i, x - nx + cx, y - ny + cy)
        wavy = {
            frozenset((b.GetBeginAtomIdx(), b.GetEndAtomIdx()))
            for b in self._mol.GetBonds()
            if b.GetBondDir() == Chem.BondDir.UNKNOWN
        }
        directions = [
            (b.GetBeginAtomIdx(), b.GetEndAtomIdx(), b.GetBondDir()) for b in work.GetBonds()
        ]
        for begin, end, direction in directions:
            target = self._mol.GetBondBetweenAtoms(begin, end)
            if frozenset((begin, end)) in wavy and direction == Chem.BondDir.NONE:
                continue  # keep the wavy "unknown stereo" bond the user drew
            if target.GetBeginAtomIdx() != begin and direction != Chem.BondDir.NONE:
                # WedgeMolBonds may need the wedge to start at the other atom.
                bond_type = target.GetBondType()
                bold = target.HasProp(_BOLD)
                self._mol.RemoveBond(end, begin)
                self._mol.AddBond(begin, end, bond_type)
                target = self._mol.GetBondBetweenAtoms(begin, end)
                if bold:
                    target.SetBoolProp(_BOLD, True)
            target.SetBondDir(direction)
        self._touch()

    # ------------------------------------------------------------------
    # Atom properties (charge, isotope, hydrogens, radicals)
    # ------------------------------------------------------------------

    def atom_isotope(self, atom_idx: int) -> int:
        return int(self._mol.GetAtomWithIdx(atom_idx).GetIsotope())

    def atom_radicals(self, atom_idx: int) -> int:
        return int(self._mol.GetAtomWithIdx(atom_idx).GetNumRadicalElectrons())

    def atom_hydrogens_fixed(self, atom_idx: int) -> bool:
        """True when the H count was set by hand (not derived from valence)."""
        atom = self._mol.GetAtomWithIdx(atom_idx)
        return atom.GetSymbol() in _IMPLICIT_H_ELEMENTS and atom.GetNoImplicit()

    def _auto_hydrogens(self, atom: Chem.Atom) -> int:
        probe = Chem.RWMol(self._mol)
        work = probe.GetAtomWithIdx(atom.GetIdx())
        work.SetNoImplicit(work.GetSymbol() not in _IMPLICIT_H_ELEMENTS)
        work.SetNumExplicitHs(0)
        work.SetNumRadicalElectrons(0)
        with _quiet_rdkit():
            probe.UpdatePropertyCache(strict=False)
        return int(work.GetNumImplicitHs())

    def set_atom_properties(
        self,
        atom_idx: int,
        *,
        symbol: str | None = None,
        charge: int | None = None,
        isotope: int | None = None,
        hydrogens: int | None | str = "keep",
        radicals: int | None = None,
    ) -> None:
        """Change several atom properties in one undo step.

        ``hydrogens``: ``"keep"`` leaves the H count alone, ``None`` returns
        it to automatic (from valence), an int fixes it.  Radicals (unpaired
        electrons) take hydrogens away from the automatic count.
        """
        if symbol is not None:
            self._make_atom(symbol)  # validates
        self._push_undo()
        atom = self._mol.GetAtomWithIdx(atom_idx)
        symbol_changed = symbol is not None and symbol != atom.GetSymbol()
        if symbol_changed:
            template = self._make_atom(symbol)  # type: ignore[arg-type]
            atom.SetAtomicNum(template.GetAtomicNum())
            atom.SetNoImplicit(template.GetNoImplicit())
            atom.SetNumExplicitHs(0)
            atom.SetIsAromatic(False)
            self._clear_charge_marks(atom)
            if charge is None:
                atom.SetFormalCharge(0)
        if charge is not None:
            new_charge = max(-8, min(8, int(charge)))
            atom.SetFormalCharge(new_charge)
            if new_charge == self._auto_charge_for(atom):
                self._clear_charge_marks(atom)
            else:
                self._mark_manual_charge(atom)
        if isotope is not None:
            atom.SetIsotope(max(0, int(isotope)))
        if radicals is not None:
            atom.SetNumRadicalElectrons(max(0, min(3, int(radicals))))
        if hydrogens != "keep":
            if hydrogens is None:
                atom.SetNoImplicit(atom.GetSymbol() not in _IMPLICIT_H_ELEMENTS)
                atom.SetNumExplicitHs(0)
            else:
                atom.SetNoImplicit(True)
                atom.SetNumExplicitHs(max(0, int(hydrogens)))
        elif charge is not None or symbol is not None:
            # A new charge or element changes how many H the atom carries.
            atom.SetNoImplicit(atom.GetSymbol() not in _IMPLICIT_H_ELEMENTS)
            atom.SetNumExplicitHs(0)
        if atom.GetNumRadicalElectrons() and not self.atom_hydrogens_fixed(atom_idx):
            auto = self._auto_hydrogens(atom)
            atom.SetNoImplicit(True)
            atom.SetNumExplicitHs(max(0, auto - atom.GetNumRadicalElectrons()))
        self._touch()

    def set_atom_isotope(self, atom_idx: int, isotope: int) -> None:
        self.set_atom_properties(atom_idx, isotope=isotope)

    def set_atom_radicals(self, atom_idx: int, radicals: int) -> None:
        atom = self._mol.GetAtomWithIdx(atom_idx)
        if radicals == 0 and atom.GetNumRadicalElectrons():
            self.set_atom_properties(atom_idx, radicals=0, hydrogens=None)
        else:
            self.set_atom_properties(atom_idx, radicals=radicals)

    def set_atom_hydrogens(self, atom_idx: int, hydrogens: int | None) -> None:
        self.set_atom_properties(atom_idx, hydrogens=hydrogens)

    # ------------------------------------------------------------------
    # Calculated values & checks
    # ------------------------------------------------------------------

    def net_charge(self) -> int:
        return sum(a.GetFormalCharge() for a in self._mol.GetAtoms())

    def components(self) -> list[list[int]]:
        """Connected components (molecules / ions), left to right."""
        seen: set[int] = set()
        parts: list[list[int]] = []
        for idx in range(self.atom_count):
            if idx not in seen:
                part = self.fragment_atoms(idx)
                seen.update(part)
                parts.append(part)
        parts.sort(key=lambda p: min(self.atom_position(i)[0] for i in p))
        return parts

    def component_formulas(self) -> list[str]:
        """Formula of each component with sub-/superscripts (e.g. ``C₆H₇N``, ``HCl``)."""
        formulas = []
        for part in self.components():
            sub = self._submol(part)
            with _quiet_rdkit():
                sub.UpdatePropertyCache(strict=False)
                formulas.append(format_formula(rdMolDescriptors.CalcMolFormula(sub)))
        return formulas

    def display_formula(self) -> str:
        """``C₆H₈N⁺ · Cl⁻`` style formula of everything drawn."""
        return " · ".join(self.component_formulas())

    def exact_mass(self) -> float:
        if self.atom_count == 0:
            return 0.0
        mol = Chem.Mol(self._mol)
        with _quiet_rdkit():
            mol.UpdatePropertyCache(strict=False)
            return float(rdMolDescriptors.CalcExactMolWt(mol))

    def unsaturation(self) -> int:
        """Rings + π bonds (double bond equivalents) of the drawn structure."""
        if self.atom_count == 0:
            return 0
        rings = self.bond_count - self.atom_count + len(self.components())
        pi_bonds = sum(self.bond_order(i) - 1 for i in range(self.bond_count))
        return rings + pi_bonds

    def structure_problems(self) -> list[tuple[str, int | None]]:
        """``(kind, atom index)`` for things a chemist would want to check.

        Kinds: ``"valence"`` (too many bonds), ``"radical"`` (unpaired
        electrons drawn on purpose or not).
        """
        problems: list[tuple[str, int | None]] = [
            ("valence", idx) for idx in sorted(self.invalid_atom_indices())
        ]
        problems += [
            ("radical", atom.GetIdx())
            for atom in self._mol.GetAtoms()
            if atom.GetNumRadicalElectrons()
        ]
        return problems

    def stereo_labels(self) -> tuple[dict[int, str], dict[int, str]]:
        """CIP labels: ``({atom: "R"/"S"}, {bond: "E"/"Z"})`` as drawn."""
        empty: tuple[dict[int, str], dict[int, str]] = ({}, {})
        if self.atom_count == 0:
            return empty
        try:
            from rdkit.Chem import rdCIPLabeler  # noqa: PLC0415

            with _quiet_rdkit():
                mol = Chem.MolFromMolBlock(self.to_mol_block(), removeHs=False)
                if mol is None:
                    return empty
                rdCIPLabeler.AssignCIPLabels(mol)
        except Exception:  # noqa: BLE001
            return empty
        atoms = {
            a.GetIdx(): str(a.GetProp("_CIPCode")).upper()
            for a in mol.GetAtoms()
            if a.HasProp("_CIPCode")
        }
        bonds: dict[int, str] = {}
        for bond in mol.GetBonds():
            if bond.HasProp("_CIPCode"):
                idx = self.find_bond(bond.GetBeginAtomIdx(), bond.GetEndAtomIdx())
                if idx is not None:
                    bonds[idx] = str(bond.GetProp("_CIPCode")).upper()
        return atoms, bonds

    def inchi(self) -> tuple[str, str]:
        """``(InChI, InChIKey)``; empty strings when unavailable."""
        if self.atom_count == 0:
            return "", ""
        try:
            with _quiet_rdkit():
                mol = self._export_mol()
                inchi = Chem.MolToInchi(mol) or ""
                key = Chem.InchiToInchiKey(inchi) if inchi else ""
        except Exception:  # noqa: BLE001
            return "", ""
        return str(inchi), str(key or "")

    # ------------------------------------------------------------------
    # Fragments: copy, paste, attach, groups
    # ------------------------------------------------------------------

    def _submol(self, atom_indices: Iterable[int]) -> Chem.RWMol:
        indices = sorted(set(atom_indices))
        index_map: dict[int, int] = {}
        sub = Chem.RWMol()
        sub.AddConformer(Chem.Conformer(0), assignId=True)
        for old in indices:
            new = sub.AddAtom(Chem.Atom(self._mol.GetAtomWithIdx(old)))
            x, y = self.atom_position(old)
            sub.GetConformer().SetAtomPosition(new, Point3D(x, y, 0.0))
            index_map[old] = new
        for bond in self._mol.GetBonds():
            a, b = bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()
            if a in index_map and b in index_map:
                sub.AddBond(index_map[a], index_map[b], bond.GetBondType())
                sub.GetBondBetweenAtoms(index_map[a], index_map[b]).SetBondDir(bond.GetBondDir())
        return sub

    def extract_fragment(self, atom_indices: Iterable[int]) -> Fragment:
        """Copy the given atoms (and bonds between them) as a :class:`Fragment`.

        If a copied atom was bonded to an atom outside the selection, it
        becomes the attachment point, so pasting onto an atom re-creates
        that bond in the same orientation.
        """
        indices = sorted(set(atom_indices))
        if not indices:
            raise ValueError("Nothing to copy")
        selected = set(indices)
        attach: int | None = None
        anchor: tuple[float, float] | None = None
        for position, old in enumerate(indices):
            outside = [n for n in self.atom_neighbors(old) if n not in selected]
            if outside:
                attach = position
                anchor = self.atom_position(outside[0])
                break
        sub = self._submol(indices)
        for atom in sub.GetAtoms():
            if atom.GetSymbol() in _IMPLICIT_H_ELEMENTS and not atom.GetNumRadicalElectrons():
                atom.SetNoImplicit(False)
                atom.SetNumExplicitHs(0)
        mol = sub.GetMol()
        with _quiet_rdkit():
            mol.UpdatePropertyCache(strict=False)
        return Fragment(mol=mol, attach=attach if attach is not None else 0, anchor=anchor)

    def fragment_coordinates(
        self,
        fragment: Fragment,
        *,
        target_atom_idx: int | None = None,
        position: tuple[float, float] | None = None,
        angle: float | None = None,
    ) -> list[tuple[float, float]]:
        """Where :meth:`insert_fragment` would put each fragment atom.

        *angle* (degrees) fixes the direction of the new bond from the target
        atom, e.g. the direction the user dragged in.
        """
        self._last_fragment_mirrored = False
        pts = [complex(x, y) for x, y in fragment.coordinates()]
        if not pts:
            return []
        centroid = sum(pts) / len(pts)
        if target_atom_idx is not None and fragment.attach is not None:
            attach = pts[fragment.attach]
            target = complex(*self.atom_position(target_atom_idx))
            bond_angle = (
                math.radians(angle)
                if angle is not None
                else self._sprout_direction(target_atom_idx)
            )
            if fragment.anchor is not None:
                inward = complex(*fragment.anchor) - attach
            else:
                inward = (attach - centroid) if abs(attach - centroid) > 1e-6 else complex(-1, 0)
                inward = -inward
            if abs(inward) < 1e-6:
                inward = complex(-1, 0)
            others = [
                complex(*self.atom_position(i))
                for i in range(self.atom_count)
                if i != target_atom_idx
            ]

            def layouts(
                direction: complex, spin: float = 0.0, source: list[complex] = pts
            ) -> list[list[complex]]:
                # The bond back to the target points along -direction; *spin*
                # (degrees) swings the group about its attach atom.
                attach_pos = target + BOND_LENGTH * direction
                swing = cmath.exp(1j * math.radians(spin))
                rotation = (-direction) / (inward / abs(inward)) * swing
                mirror = (-direction) / (inward.conjugate() / abs(inward)) * swing
                return [
                    [attach_pos + (p - attach) * rotation for p in source],
                    [attach_pos + (p - attach).conjugate() * mirror for p in source],
                ]

            def crowding(placed: list[complex]) -> float:
                return sum(1.0 / max(abs(p - o), 0.2) ** 2 for p in placed for o in others)

            folded = _folded_branches(fragment, pts, -inward)
            base = pts
            if folded is not None and _self_clearance(pts) < _CLEAR:
                base = folded  # the depiction folds the group onto itself
            options = layouts(cmath.exp(1j * bond_angle), 0.0, base)
            mirrored = crowding(options[0]) > crowding(options[1]) * 1.05
            placed = options[1] if mirrored else options[0]
            if angle is None and _clearance(placed, others) < _CLEAR:
                # A crowded atom: turn the new bond a little until the group
                # clears its neighbours (or, failing that, as far as it can),
                # also trying the group drawn as a compact fan.
                shapes = [(0, base)]
                if folded is not None and folded is not base:
                    shapes.append((90, folded))
                turned = [
                    (abs(step) + abs(spin) + cost, index == 1, option)
                    for cost, shape in shapes
                    for step in _TURN_STEPS
                    for spin in (0, 30, -30)
                    for index, option in enumerate(
                        layouts(cmath.exp(1j * (bond_angle + math.radians(step))), spin, shape)
                    )
                ]
                _step, mirrored, placed = _least_clashing(turned, others, crowding)
            self._last_fragment_mirrored = mirrored
        else:
            if position is None:
                bounds = self.bounds()
                if bounds is None:
                    target = complex(0.0, 0.0)
                else:
                    xs = [p.real for p in pts]
                    width = max(xs) - min(xs)
                    target = complex(
                        bounds[2] + 1.5 * BOND_LENGTH + width / 2, (bounds[1] + bounds[3]) / 2
                    )
            else:
                target = complex(*position)
            placed = [target + (p - centroid) for p in pts]
        return [(p.real, p.imag) for p in placed]

    def insert_fragment(
        self,
        fragment: Fragment,
        *,
        target_atom_idx: int | None = None,
        position: tuple[float, float] | None = None,
        angle: float | None = None,
    ) -> list[int]:
        """Add *fragment*; bonded to *target_atom_idx* through its attach atom.

        *angle* (degrees) sets the direction of that bond; by default it
        follows the usual sprouting rules.

        Without a target the fragment is centred at *position* (or placed to
        the right of the drawing) as a separate molecule — e.g. a counter-ion.
        """
        coords = self.fragment_coordinates(
            fragment, target_atom_idx=target_atom_idx, position=position, angle=angle
        )
        self._push_undo()
        index_map: dict[int, int] = {}
        for atom in fragment.mol.GetAtoms():
            x, y = coords[atom.GetIdx()]
            index_map[atom.GetIdx()] = self._add_atom(Chem.Atom(atom), x, y)
        for bond in fragment.mol.GetBonds():
            a = index_map[bond.GetBeginAtomIdx()]
            b = index_map[bond.GetEndAtomIdx()]
            self._mol.AddBond(a, b, bond.GetBondType())
            direction = bond.GetBondDir()
            if self._last_fragment_mirrored:
                # Placed as a mirror image: swap wedges so the stereo is unchanged.
                direction = {
                    Chem.BondDir.BEGINWEDGE: Chem.BondDir.BEGINDASH,
                    Chem.BondDir.BEGINDASH: Chem.BondDir.BEGINWEDGE,
                }.get(direction, direction)
            self._mol.GetBondBetweenAtoms(a, b).SetBondDir(direction)
        if target_atom_idx is not None and fragment.attach is not None:
            self._add_bond(target_atom_idx, index_map[fragment.attach], 1)
        self._touch()
        return [index_map[i] for i in range(fragment.atom_count)]

    def replace_atom_with_fragment(self, atom_idx: int, fragment: Fragment) -> list[int]:
        """Put a group in place of a (terminal or lone) atom, like typing ``OMe`` on it.

        Returns the new atom indices (valid after the replacement).
        """
        nbrs = self.atom_neighbors(atom_idx)
        if len(nbrs) > 1:
            raise ValueError("A group can only replace a terminal atom")
        with self.compound():
            if not nbrs:
                ax, ay = self.atom_position(atom_idx)
                if fragment.attach is not None:
                    fx, fy = fragment.coordinates()[fragment.attach]
                    cx = sum(x for x, _ in fragment.coordinates()) / fragment.atom_count
                    cy = sum(y for _, y in fragment.coordinates()) / fragment.atom_count
                    position = (ax + cx - fx, ay + cy - fy)
                else:
                    position = (ax, ay)
                created = self.insert_fragment(fragment, position=position)
            else:
                neighbour = nbrs[0]
                nx, ny = self.atom_position(neighbour)
                ax, ay = self.atom_position(atom_idx)
                bond = self.find_bond(neighbour, atom_idx)
                order = self.bond_order(bond) if bond is not None else 1
                # Temporarily drop the atom's bond so the group grows where it sat.
                self._mol.RemoveBond(neighbour, atom_idx)
                saved = self.atom_position(atom_idx)
                self._set_position(atom_idx, 1e6, 1e6)
                angle = math.degrees(math.atan2(ay - ny, ax - nx))
                coords = self._fragment_coords_at_angle(fragment, neighbour, angle)
                self._set_position(atom_idx, *saved)
                index_map: dict[int, int] = {}
                for atom in fragment.mol.GetAtoms():
                    index_map[atom.GetIdx()] = self._add_atom(
                        Chem.Atom(atom), *coords[atom.GetIdx()]
                    )
                for fbond in fragment.mol.GetBonds():
                    a = index_map[fbond.GetBeginAtomIdx()]
                    b = index_map[fbond.GetEndAtomIdx()]
                    self._mol.AddBond(a, b, fbond.GetBondType())
                attach = fragment.attach if fragment.attach is not None else 0
                self._add_bond(neighbour, index_map[attach], 1 if order > 1 else order)
                created = [index_map[i] for i in range(fragment.atom_count)]
            self._mol.RemoveAtom(atom_idx)
            self._touch()
        return [i - 1 if i > atom_idx else i for i in created]

    def _fragment_coords_at_angle(
        self, fragment: Fragment, target_atom_idx: int, angle_deg: float
    ) -> list[tuple[float, float]]:
        pts = [complex(x, y) for x, y in fragment.coordinates()]
        attach = pts[fragment.attach if fragment.attach is not None else 0]
        centroid = sum(pts) / len(pts)
        direction = cmath.exp(1j * math.radians(angle_deg))
        target = complex(*self.atom_position(target_atom_idx))
        attach_pos = target + BOND_LENGTH * direction
        if fragment.anchor is not None:
            inward = complex(*fragment.anchor) - attach
        else:
            inward = -(attach - centroid) if abs(attach - centroid) > 1e-6 else complex(-1, 0)
        if abs(inward) < 1e-6:
            inward = complex(-1, 0)
        rotation = (-direction) / (inward / abs(inward))
        return [
            (
                (attach_pos + (p - attach) * rotation).real,
                (attach_pos + (p - attach) * rotation).imag,
            )
            for p in pts
        ]

    def apply_label(
        self, atom_idx: int, text: str, custom_groups: dict[str, str] | None = None
    ) -> bool:
        """Apply what the user typed on an atom: an element or a group.

        ``N``, ``Cl``, ``Na`` change the element; ``OMe``, ``CO2Et``,
        ``CH2CH2OH``, ``*OCC`` or a custom group replace the atom by that group.
        Returns ``False`` when the text is not understood.
        """
        label = (text or "").strip()
        if not label:
            return False
        charge_match = re.fullmatch(r"([A-Z][a-z]?)(\d*)([+-])", label)
        if charge_match and is_element_symbol(charge_match.group(1)):
            symbol, count, sign = charge_match.groups()
            charge = int(count or 1) * (1 if sign == "+" else -1)
            self.set_atom_properties(atom_idx, symbol=symbol, charge=charge)
            return True
        if is_element_symbol(label):
            self.set_atom_symbol(atom_idx, label)
            return True
        if label in ("D", "T"):
            self.set_atom_properties(atom_idx, symbol="H", isotope=2 if label == "D" else 3)
            return True
        fragment = parse_group(label, custom_groups)
        if fragment is None:
            return False
        try:
            self.replace_atom_with_fragment(atom_idx, fragment)
        except ValueError:
            return False
        return True

    # ------------------------------------------------------------------
    # Transformations
    # ------------------------------------------------------------------

    def _centroid(self, atoms: list[int]) -> tuple[float, float]:
        xs = [self.atom_position(i)[0] for i in atoms]
        ys = [self.atom_position(i)[1] for i in atoms]
        return (sum(xs) / len(xs), sum(ys) / len(ys))

    def rotate_atoms(
        self,
        atom_indices: Iterable[int] | None,
        angle_deg: float,
        center: tuple[float, float] | None = None,
    ) -> None:
        """Rotate atoms (all when ``None``) counter-clockwise around their centroid."""
        atoms = list(range(self.atom_count)) if atom_indices is None else sorted(set(atom_indices))
        if not atoms:
            return
        cx, cy = center if center is not None else self._centroid(atoms)
        rotation = cmath.exp(1j * math.radians(angle_deg))
        self._push_undo()
        for idx in atoms:
            p = (complex(*self.atom_position(idx)) - complex(cx, cy)) * rotation + complex(cx, cy)
            self._set_position(idx, p.real, p.imag)
        self._touch()

    def flip_atoms(self, atom_indices: Iterable[int] | None, *, horizontal: bool = True) -> None:
        """Mirror atoms left↔right (or up↔down); wedges swap so stereo is kept."""
        atoms = list(range(self.atom_count)) if atom_indices is None else sorted(set(atom_indices))
        if not atoms:
            return
        cx, cy = self._centroid(atoms)
        chosen = set(atoms)
        self._push_undo()
        for idx in atoms:
            x, y = self.atom_position(idx)
            if horizontal:
                self._set_position(idx, 2 * cx - x, y)
            else:
                self._set_position(idx, x, 2 * cy - y)
        for bond in self._mol.GetBonds():
            if bond.GetBeginAtomIdx() in chosen and bond.GetEndAtomIdx() in chosen:
                if bond.GetBondDir() == Chem.BondDir.BEGINWEDGE:
                    bond.SetBondDir(Chem.BondDir.BEGINDASH)
                elif bond.GetBondDir() == Chem.BondDir.BEGINDASH:
                    bond.SetBondDir(Chem.BondDir.BEGINWEDGE)
        self._touch()

    def merge_atoms(self, keep: int, remove: int, *, record_undo: bool = True) -> int:
        """Fuse *remove* into *keep* (e.g. an atom dropped onto another).

        Returns the index of the kept atom after the removal.
        """
        if keep == remove:
            return keep
        if record_undo:
            self._push_undo()
        for bond in list(self._mol.GetAtomWithIdx(remove).GetBonds()):
            other = bond.GetOtherAtomIdx(remove)
            if other != keep and self.find_bond(keep, other) is None:
                self._mol.AddBond(keep, other, bond.GetBondType())
        self._mol.RemoveAtom(remove)
        self._touch()
        return keep - 1 if keep > remove else keep

    # ------------------------------------------------------------------
    # Explicit hydrogens
    # ------------------------------------------------------------------

    def add_explicit_hydrogens(self, atom_indices: Iterable[int] | None = None) -> int:
        """Draw every implicit H as an atom; returns how many were added."""
        atoms = list(range(self.atom_count)) if atom_indices is None else sorted(set(atom_indices))
        targets = [
            (idx, self.implicit_hydrogens(idx))
            for idx in atoms
            if self.atom_symbol(idx) != "H" and self.implicit_hydrogens(idx) > 0
        ]
        if not targets:
            return 0
        added = 0
        self._push_undo()
        for idx, count in targets:
            atom = self._mol.GetAtomWithIdx(idx)
            fixed = atom.GetNoImplicit() and atom.GetSymbol() in _IMPLICIT_H_ELEMENTS
            for _ in range(count):
                self._sprout(idx, self._make_atom("H"), 1, STEREO_NONE, None)
                added += 1
            if fixed:
                atom.SetNumExplicitHs(0)
            self._touch()
        return added

    def remove_explicit_hydrogens(self) -> int:
        """Fold plain H atoms back into their neighbours' labels."""
        removable = []
        for atom in self._mol.GetAtoms():
            if (
                atom.GetAtomicNum() == 1
                and atom.GetIsotope() == 0
                and atom.GetFormalCharge() == 0
                and atom.GetDegree() == 1
                and atom.GetNeighbors()[0].GetAtomicNum() > 1
                and atom.GetBonds()[0].GetBondDir() == Chem.BondDir.NONE
            ):
                removable.append(atom.GetIdx())
        if not removable:
            return 0
        self._push_undo()
        for idx in sorted(removable, reverse=True):
            heavy = self._mol.GetAtomWithIdx(idx).GetNeighbors()[0]
            if heavy.GetNoImplicit() and heavy.GetSymbol() in _IMPLICIT_H_ELEMENTS:
                heavy.SetNumExplicitHs(heavy.GetNumExplicitHs() + 1)
            self._mol.RemoveAtom(idx)
        self._touch()
        return len(removable)

    # ------------------------------------------------------------------
    # Bond cycling and bond length
    # ------------------------------------------------------------------

    def cycle_bond(self, bond_idx: int) -> int:
        """Next bond style on a click: single → double → triple → wedge one
        way → wedge the other way → single.  Returns the (new) bond index."""
        a, b = self.bond_atoms(bond_idx)
        low, high = min(a, b), max(a, b)
        order = self.bond_order(bond_idx)
        stereo = self.bond_stereo(bond_idx)
        with self.compound():
            if stereo == STEREO_WEDGE and a == low:
                return self._replace_bond(low, high, 1, STEREO_WEDGE, begin=high)
            if stereo != STEREO_NONE:
                return self._replace_bond(low, high, 1, STEREO_NONE, begin=low)
            if order == 1:
                return self._replace_bond(low, high, 2, STEREO_NONE, begin=a)
            if order == 2:
                return self._replace_bond(low, high, 3, STEREO_NONE, begin=a)
            return self._replace_bond(low, high, 1, STEREO_WEDGE, begin=low)

    def _replace_bond(self, a: int, b: int, order: int, stereo: str, *, begin: int) -> int:
        self._push_undo()
        bond = self._mol.GetBondBetweenAtoms(a, b)
        if bond.GetBeginAtomIdx() == begin:
            # Same direction: change it in place so the bond keeps its index.
            bond.SetBondType(_ORDER_TO_TYPE[order])
            bond.SetBondDir(_STEREO_TO_DIR[stereo])
            bond.SetIsAromatic(False)
            bond.SetStereo(Chem.BondStereo.STEREONONE)
            self._touch()
            return int(bond.GetIdx())
        self._mol.RemoveBond(a, b)
        end = b if begin == a else a
        idx = self._add_bond(begin, end, order, stereo)
        self._touch()
        return idx

    def bond_length(self, bond_idx: int) -> float:
        a, b = self.bond_atoms(bond_idx)
        return math.dist(self.atom_position(a), self.atom_position(b))

    def _side_atoms(self, start: int, blocked: int) -> set[int]:
        """Atoms reachable from *start* without walking through *blocked*."""
        seen = {start}
        queue = deque([start])
        while queue:
            current = queue.popleft()
            for nbr in self.atom_neighbors(current):
                if nbr == blocked and current == start:
                    continue
                if nbr not in seen:
                    seen.add(nbr)
                    queue.append(nbr)
        return seen

    def set_bond_length(self, bond_idx: int, length: float) -> None:
        """Stretch or shrink a bond, moving the smaller part of the molecule.

        A ring bond only moves its end atom, so the ring is not torn apart.
        """
        length = max(0.4 * BOND_LENGTH, min(6.0 * BOND_LENGTH, float(length)))
        a, b = self.bond_atoms(bond_idx)
        ax, ay = self.atom_position(a)
        bx, by = self.atom_position(b)
        current = math.hypot(bx - ax, by - ay)
        if current < 1e-6:
            return
        ux, uy = (bx - ax) / current, (by - ay) / current
        side_b = self._side_atoms(b, a)
        side_a = self._side_atoms(a, b)
        if a in side_b:  # ring bond
            moving, sign = {b}, 1.0
        elif len(side_b) <= len(side_a):
            moving, sign = side_b, 1.0
        else:
            moving, sign = side_a, -1.0
        delta = (length - current) * sign
        self._push_undo()
        for idx in moving:
            x, y = self.atom_position(idx)
            self._set_position(idx, x + ux * delta, y + uy * delta)
        self._touch()

    def scale_bond_length(self, bond_idx: int, factor: float) -> None:
        self.set_bond_length(bond_idx, self.bond_length(bond_idx) * factor)

    # ------------------------------------------------------------------
    # Bold bonds and chair conformations
    # ------------------------------------------------------------------

    def bond_bold(self, bond_idx: int) -> bool:
        return bool(self._mol.GetBondWithIdx(bond_idx).HasProp(_BOLD))

    def set_bond_bold(self, bond_idx: int, bold: bool = True) -> None:  # noqa: FBT001, FBT002
        """Draw a bond thick (the front edge of a chair or a perspective drawing)."""
        bond = self._mol.GetBondWithIdx(bond_idx)
        if bool(bond.HasProp(_BOLD)) == bool(bold):
            return
        self._push_undo()
        if bold:
            bond.SetBoolProp(_BOLD, True)
            bond.SetBondDir(Chem.BondDir.NONE)
        else:
            bond.ClearProp(_BOLD)
        self._touch()

    def chair_directions(self, atom_idx: int) -> tuple[float, float] | None:
        """``(equatorial, axial)`` angles (radians) for an atom of a drawn chair.

        A six-membered ring counts as a chair when it is drawn non-convex
        with its opposite bonds parallel, as in every textbook chair.  Axial
        bonds are vertical (up on the "up" atoms, down on the others);
        equatorial bonds run parallel to the ring bonds one position away.
        """
        ring = self._chair_ring(atom_idx)
        if ring is None:
            return None
        k = ring.index(atom_idx)
        prev_atom, next_atom = ring[k - 1], ring[(k + 1) % 6]
        far = ring[(k + 2) % 6]
        pos = {i: complex(*self.atom_position(i)) for i in ring}
        here = pos[atom_idx]
        centroid = sum(pos.values()) / 6
        axial_up = here.imag > (pos[prev_atom].imag + pos[next_atom].imag) / 2
        axial = math.pi / 2 if axial_up else -math.pi / 2
        parallel = pos[far] - pos[next_atom]
        if (parallel.real * (here - centroid).real + parallel.imag * (here - centroid).imag) < 0:
            parallel = -parallel
        equatorial = math.atan2(parallel.imag, parallel.real)
        return equatorial, axial

    def _chair_ring(self, atom_idx: int) -> list[int] | None:
        for ring_atoms, _ring_bonds in self._bond_rings():
            if len(ring_atoms) != 6 or atom_idx not in ring_atoms:
                continue
            ordered = self._ring_order(list(ring_atoms))
            if ordered is not None and self._looks_like_chair(ordered):
                return ordered
        return None

    def _ring_order(self, atoms: list[int]) -> list[int] | None:
        members = set(atoms)
        ordered = [atoms[0]]
        while len(ordered) < len(atoms):
            options = [
                n for n in self.atom_neighbors(ordered[-1]) if n in members and n not in ordered
            ]
            if not options:
                return None
            ordered.append(options[0])
        return ordered

    def _looks_like_chair(self, ring: list[int]) -> bool:
        pts = [complex(*self.atom_position(i)) for i in ring]
        edges = [pts[(k + 1) % 6] - pts[k] for k in range(6)]
        turns = [(edges[k].conjugate() * edges[(k + 1) % 6]).imag for k in range(6)]
        convex = all(t > 0 for t in turns) or all(t < 0 for t in turns)
        if convex:
            return False
        for k in range(3):
            a, b = edges[k], edges[k + 3]
            if abs(a) < 1e-6 or abs(b) < 1e-6:
                return False
            if abs((a.conjugate() * b).imag) / (abs(a) * abs(b)) > 0.12:
                return False
        return True

    def _chair_sprout(self, atom_idx: int) -> float | None:
        """Equatorial first, then axial, for an atom of a chair."""
        directions = self.chair_directions(atom_idx)
        if directions is None:
            return None
        ring = self._chair_ring(atom_idx) or []
        ax, ay = self.atom_position(atom_idx)
        used = [
            math.atan2(self.atom_position(n)[1] - ay, self.atom_position(n)[0] - ax)
            for n in self.atom_neighbors(atom_idx)
            if n not in ring
        ]
        for angle in directions:
            if all(abs(_normalize(angle - u)) > math.radians(20) for u in used):
                return angle
        return None
