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
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from rdkit import Chem, rdBase
from rdkit.Chem import Descriptors, rdDepictor, rdMolDescriptors
from rdkit.Geometry import Point3D

BOND_LENGTH = 1.50
UNDO_LIMIT = 100

STEREO_NONE = "none"
STEREO_WEDGE = "wedge"
STEREO_HASH = "hash"
_STEREO_TO_DIR = {
    STEREO_NONE: Chem.BondDir.NONE,
    STEREO_WEDGE: Chem.BondDir.BEGINWEDGE,
    STEREO_HASH: Chem.BondDir.BEGINDASH,
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


RING_TEMPLATES: dict[str, _RingTemplate] = {
    "cyclopropane": _RingTemplate("C1CC1", 0, (0, 1), False),
    "cyclobutane": _RingTemplate("C1CCC1", 0, (0, 1), False),
    "cyclopentane": _RingTemplate("C1CCCC1", 0, (0, 1), False),
    "cyclohexane": _RingTemplate("C1CCCCC1", 0, (0, 1), False),
    "cycloheptane": _RingTemplate("C1CCCCCC1", 0, (0, 1), False),
    "benzene": _RingTemplate("c1ccccc1", 0, (0, 1), True),
    # 4-pyridyl when attached, N para to the attachment point.
    "pyridine": _RingTemplate("c1ccncc1", 0, (0, 1), True),
    # 2-furyl / 2-thienyl / 2-pyrrolyl; fusion gives benzofuran-type rings.
    "furan": _RingTemplate("c1ccco1", 0, (0, 1), True),
    "thiophene": _RingTemplate("c1cccs1", 0, (0, 1), True),
    "pyrrole": _RingTemplate("c1ccc[nH]1", 0, (0, 1), True),
    # 1-naphthyl when attached.
    "naphthalene": _RingTemplate("c1ccc2ccccc2c1", 9, (0, 1), True),
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
}


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
        with _quiet_rdkit():
            Chem.WedgeMolBonds(parsed, parsed.GetConformer())
        if record_undo:
            self._push_undo()
        self._set_mol(Chem.RWMol(parsed))
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
        if record_undo:
            self._push_undo()
        self._set_mol(mol)
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
            return Chem.MolToSmiles(mol)

    def to_mol_block(self) -> str:
        """V2000 MOL block with the drawn 2D coordinates; ``""`` if empty."""
        if self.atom_count == 0:
            return ""
        mol = Chem.Mol(self._mol)
        with _quiet_rdkit():
            mol.UpdatePropertyCache(strict=False)
            Chem.FastFindRings(mol)
            Chem.AssignChiralTypesFromBondDirs(mol)
            return Chem.MolToMolBlock(mol, kekulize=False)

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
        return self._mol.GetNumAtoms()

    @property
    def bond_count(self) -> int:
        return self._mol.GetNumBonds()

    def is_empty(self) -> bool:
        return self.atom_count == 0

    def atom_symbol(self, atom_idx: int) -> str:
        return self._mol.GetAtomWithIdx(atom_idx).GetSymbol()

    def atom_charge(self, atom_idx: int) -> int:
        return self._mol.GetAtomWithIdx(atom_idx).GetFormalCharge()

    def atom_position(self, atom_idx: int) -> tuple[float, float]:
        pos = self._mol.GetConformer().GetAtomPosition(atom_idx)
        return (pos.x, pos.y)

    def atom_neighbors(self, atom_idx: int) -> list[int]:
        return [n.GetIdx() for n in self._mol.GetAtomWithIdx(atom_idx).GetNeighbors()]

    def atom_degree(self, atom_idx: int) -> int:
        return self._mol.GetAtomWithIdx(atom_idx).GetDegree()

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
        return STEREO_NONE

    def find_bond(self, atom_a: int, atom_b: int) -> int | None:
        bond = self._mol.GetBondBetweenAtoms(atom_a, atom_b)
        return None if bond is None else bond.GetIdx()

    def atom_bonds(self, atom_idx: int) -> list[int]:
        return [b.GetIdx() for b in self._mol.GetAtomWithIdx(atom_idx).GetBonds()]

    def implicit_hydrogens(self, atom_idx: int) -> int:
        """Hydrogens shown in the atom label (implicit + explicit H count)."""
        atom = self._mol.GetAtomWithIdx(atom_idx)
        return atom.GetNumImplicitHs() + atom.GetNumExplicitHs()

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
            return float(Descriptors.MolWt(mol))  # type: ignore[attr-defined]

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
        with _quiet_rdkit():
            self._mol.UpdatePropertyCache(strict=False)
        self._revision += 1

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
        return idx

    def _set_position(self, atom_idx: int, x: float, y: float) -> None:
        self._mol.GetConformer().SetAtomPosition(atom_idx, Point3D(x, y, 0.0))

    def _add_bond(self, a: int, b: int, order: int = 1, stereo_dir: str = STEREO_NONE) -> int:
        self._mol.AddBond(a, b, _ORDER_TO_TYPE.get(order, Chem.BondType.SINGLE))
        bond = self._mol.GetBondBetweenAtoms(a, b)
        bond.SetBondDir(_STEREO_TO_DIR.get(stereo_dir, Chem.BondDir.NONE))
        return bond.GetIdx()

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
        best_gap = -1.0
        best_mid = 0.0
        for i, start in enumerate(ordered):
            end = ordered[(i + 1) % len(ordered)]
            gap = (end - start) % (2 * math.pi)
            if gap == 0:
                gap = 2 * math.pi
            if gap > best_gap:
                best_gap = gap
                best_mid = start + gap / 2
        return _normalize(best_mid)

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
    ) -> int:
        angle = self._sprout_direction(
            from_atom_idx, bond_order=bond_order, preferred_angle=preferred_angle
        )
        ax, ay = self.atom_position(from_atom_idx)
        x = ax + BOND_LENGTH * math.cos(angle)
        y = ay + BOND_LENGTH * math.sin(angle)
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
    ) -> int:
        """Add a new atom bonded to *from_atom_idx*; returns its index.

        *preferred_angle* is in degrees (y up).  Without it the direction
        follows the usual drawing conventions: a lone atom grows at +30°, a
        chain end continues as a trans zig-zag, a two-substituted atom grows
        along the outer bisector and a crowded atom into its largest gap.
        """
        atom = self._make_atom(symbol)
        self._push_undo()
        idx = self._sprout(from_atom_idx, atom, bond_order, stereo_dir, preferred_angle)
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
            self._mol.RemoveBond(begin, bond.GetEndAtomIdx())
            idx = self._add_bond(atom_a, atom_b, 1, stereo_dir)
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
        return bond.GetIdx()

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
        template = _kekulized_template(RING_TEMPLATES[ring_type].smiles)
        return [atom.GetSymbol() for atom in template.GetAtoms()]

    @staticmethod
    def ring_template_bonds(ring_type: str) -> list[tuple[int, int, int]]:
        """``(atom_a, atom_b, order)`` of a template, matching the preview coordinates."""
        template = _kekulized_template(RING_TEMPLATES[ring_type].smiles)
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
            index_map[t_idx] = self._add_atom(atom, x, y)
        new_bonds: list[int] = []
        for t_bond in template.GetBonds():
            a = index_map[t_bond.GetBeginAtomIdx()]
            b = index_map[t_bond.GetEndAtomIdx()]
            if a == b or self.find_bond(a, b) is not None:
                continue
            order = 2 if t_bond.GetBondType() == Chem.BondType.DOUBLE else 1
            new_bonds.append(self._add_bond(a, b, order))
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
        if ring_type not in RING_TEMPLATES:
            raise ValueError(f"Unknown ring template: {ring_type!r}")
        spec = RING_TEMPLATES[ring_type]
        template = _kekulized_template(spec.smiles)
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
            mapping = {t0: a, t1: b}
        elif target_atom_idx is not None:
            anchor = complex(*self.atom_position(target_atom_idx))
            t_a = spec.attach_atom
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
                placed = [attach_pos + (p - pts[t_a]) * rotation for p in pts]
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

    def attach_functional_group(self, atom_idx: int, group_key: str) -> list[int]:
        """Attach an IR-relevant group (``-OH``, ``-COOH``, ``-NO2`` …) to *atom_idx*."""
        if group_key not in FUNCTIONAL_GROUPS:
            raise ValueError(f"Unknown functional group: {group_key!r}")
        if group_key == "-Ph":
            return self.add_ring_template("benzene", target_atom_idx=atom_idx)
        with _quiet_rdkit():
            fragment = Chem.MolFromSmiles(FUNCTIONAL_GROUPS[group_key])
        Chem.Kekulize(fragment, clearAromaticFlags=True)
        self._push_undo()
        index_map: dict[int, int] = {}
        root = fragment.GetAtomWithIdx(0)
        index_map[0] = self._sprout(atom_idx, self._copy_fragment_atom(root), 1, STEREO_NONE, None)
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
        self._touch()
        return [index_map[i] for i in range(fragment.GetNumAtoms())]

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
        directions = [
            (b.GetBeginAtomIdx(), b.GetEndAtomIdx(), b.GetBondDir()) for b in work.GetBonds()
        ]
        for begin, end, direction in directions:
            target = self._mol.GetBondBetweenAtoms(begin, end)
            if target.GetBeginAtomIdx() != begin and direction != Chem.BondDir.NONE:
                # WedgeMolBonds may need the wedge to start at the other atom.
                bond_type = target.GetBondType()
                self._mol.RemoveBond(end, begin)
                self._mol.AddBond(begin, end, bond_type)
                target = self._mol.GetBondBetweenAtoms(begin, end)
            target.SetBondDir(direction)
        self._touch()
