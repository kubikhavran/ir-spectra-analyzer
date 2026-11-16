"""Fragments, group abbreviations, condensed formulas and salts for the editor.

A :class:`Fragment` is a small 2D structure that can be dropped onto the
canvas — a pasted part of a molecule, a functional group typed as text
(``OMe``, ``CO2Et``, ``NHBoc``, ``CH2CH2OH``, ``*OCC(C)C``), or a counter-ion /
solvent.  ``attach`` is the fragment atom that bonds to the atom it is
dropped on; ``anchor`` (optional) is where the outside neighbour sat when the
fragment was cut out, so it keeps its original orientation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from rdkit import Chem, rdBase
from rdkit.Chem import rdDepictor

_SUBSCRIPTS = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")


@dataclass
class Fragment:
    """A detached piece of structure with optional attachment point."""

    mol: Chem.Mol  # Kekulé form, one 2D conformer, no dummy atoms
    attach: int | None = None
    anchor: tuple[float, float] | None = None
    label: str = ""

    @property
    def atom_count(self) -> int:
        return int(self.mol.GetNumAtoms())

    def coordinates(self) -> list[tuple[float, float]]:
        conf = self.mol.GetConformer()
        return [
            (conf.GetAtomPosition(i).x, conf.GetAtomPosition(i).y)
            for i in range(self.mol.GetNumAtoms())
        ]

    def smiles(self) -> str:
        mol = Chem.Mol(self.mol)
        blocker = rdBase.BlockLogs()
        try:
            try:
                Chem.SanitizeMol(mol)
            except Exception:  # noqa: BLE001
                mol.UpdatePropertyCache(strict=False)
            return str(Chem.MolToSmiles(mol))
        finally:
            del blocker

    def mol_block(self) -> str:
        mol = Chem.Mol(self.mol)
        blocker = rdBase.BlockLogs()
        try:
            mol.UpdatePropertyCache(strict=False)
            return str(Chem.MolToMolBlock(mol, kekulize=False))
        finally:
            del blocker

    def to_json(self) -> dict[str, object]:
        return {
            "mol_block": self.mol_block(),
            "attach": self.attach,
            "anchor": list(self.anchor) if self.anchor is not None else None,
            "label": self.label,
        }

    @classmethod
    def from_json(cls, data: dict[str, object]) -> Fragment | None:
        mol_block = data.get("mol_block")
        if not isinstance(mol_block, str):
            return None
        blocker = rdBase.BlockLogs()
        try:
            mol = Chem.MolFromMolBlock(mol_block, sanitize=False, removeHs=False)
        finally:
            del blocker
        if mol is None or mol.GetNumAtoms() == 0:
            return None
        mol.UpdatePropertyCache(strict=False)
        attach = data.get("attach")
        anchor = data.get("anchor")
        return cls(
            mol=mol,
            attach=attach if isinstance(attach, int) and 0 <= attach < mol.GetNumAtoms() else None,
            anchor=(float(anchor[0]), float(anchor[1]))
            if isinstance(anchor, list) and len(anchor) == 2
            else None,
            label=str(data.get("label") or ""),
        )


# ---------------------------------------------------------------------------
# Abbreviations
# ---------------------------------------------------------------------------

# Label → SMILES with ``*`` marking the bond to the rest of the molecule.
ABBREVIATIONS: dict[str, str] = {
    # alkyl / aryl
    "Me": "*C",
    "Et": "*CC",
    "Pr": "*CCC",
    "nPr": "*CCC",
    "iPr": "*C(C)C",
    "Bu": "*CCCC",
    "nBu": "*CCCC",
    "iBu": "*CC(C)C",
    "sBu": "*C(C)CC",
    "tBu": "*C(C)(C)C",
    "Pent": "*CCCCC",
    "Hex": "*CCCCCC",
    "Cy": "*C1CCCCC1",
    "Ph": "*c1ccccc1",
    "Bn": "*Cc1ccccc1",
    "Tol": "*c1ccc(C)cc1",
    "Mes": "*c1c(C)cc(C)cc1C",
    "Vinyl": "*C=C",
    "Allyl": "*CC=C",
    "Ethynyl": "*C#C",
    # oxygen
    "OH": "*O",
    "OMe": "*OC",
    "OEt": "*OCC",
    "OPr": "*OCCC",
    "OiPr": "*OC(C)C",
    "OtBu": "*OC(C)(C)C",
    "OPh": "*Oc1ccccc1",
    "OBn": "*OCc1ccccc1",
    "OAc": "*OC(C)=O",
    "OBz": "*OC(=O)c1ccccc1",
    "OCF3": "*OC(F)(F)F",
    "OTf": "*OS(=O)(=O)C(F)(F)F",
    "OTs": "*OS(=O)(=O)c1ccc(C)cc1",
    "OMs": "*OS(=O)(=O)C",
    "OTMS": "*O[Si](C)(C)C",
    "OTBS": "*O[Si](C)(C)C(C)(C)C",
    "OPO3H2": "*OP(=O)(O)O",
    # carbonyl
    "CHO": "*C=O",
    "Ac": "*C(C)=O",
    "Bz": "*C(=O)c1ccccc1",
    "COOH": "*C(=O)O",
    "CO2H": "*C(=O)O",
    "COOMe": "*C(=O)OC",
    "CO2Me": "*C(=O)OC",
    "COOEt": "*C(=O)OCC",
    "CO2Et": "*C(=O)OCC",
    "CO2tBu": "*C(=O)OC(C)(C)C",
    "COO-": "*C(=O)[O-]",
    "CO2-": "*C(=O)[O-]",
    "CONH2": "*C(N)=O",
    "CONHMe": "*C(=O)NC",
    "CONMe2": "*C(=O)N(C)C",
    "COCl": "*C(Cl)=O",
    "Boc": "*C(=O)OC(C)(C)C",
    "Cbz": "*C(=O)OCc1ccccc1",
    "Fmoc": "*C(=O)OCC1c2ccccc2-c2ccccc21",
    # nitrogen
    "NH2": "*N",
    "NHMe": "*NC",
    "NMe2": "*N(C)C",
    "NHEt": "*NCC",
    "NEt2": "*N(CC)CC",
    "NHAc": "*NC(C)=O",
    "NHBoc": "*NC(=O)OC(C)(C)C",
    "NHCbz": "*NC(=O)OCc1ccccc1",
    "NHPh": "*Nc1ccccc1",
    "NH3+": "*[NH3+]",
    "NMe3+": "*[N+](C)(C)C",
    "NO2": "*[N+](=O)[O-]",
    "NO": "*N=O",
    "N3": "*N=[N+]=[N-]",
    "NCO": "*N=C=O",
    "NCS": "*N=C=S",
    "CN": "*C#N",
    "NC": "*[N+]#[C-]",
    "SCN": "*SC#N",
    # sulfur / phosphorus / silicon / halogenated
    "SH": "*S",
    "SMe": "*SC",
    "SPh": "*Sc1ccccc1",
    "SO3H": "*S(=O)(=O)O",
    "SO3-": "*S(=O)(=O)[O-]",
    "SO2Me": "*S(C)(=O)=O",
    "SO2NH2": "*S(N)(=O)=O",
    "SO2Cl": "*S(=O)(=O)Cl",
    "Ms": "*S(C)(=O)=O",
    "Ts": "*S(=O)(=O)c1ccc(C)cc1",
    "Tf": "*S(=O)(=O)C(F)(F)F",
    "PO3H2": "*P(=O)(O)O",
    "PPh2": "*P(c1ccccc1)c1ccccc1",
    "TMS": "*[Si](C)(C)C",
    "SiMe3": "*[Si](C)(C)C",
    "TBS": "*[Si](C)(C)C(C)(C)C",
    "TBDMS": "*[Si](C)(C)C(C)(C)C",
    "TIPS": "*[Si](C(C)C)(C(C)C)C(C)C",
    "CF3": "*C(F)(F)F",
    "CCl3": "*C(Cl)(Cl)Cl",
    "CHF2": "*C(F)F",
    "C6H5": "*c1ccccc1",
    "C6H11": "*C1CCCCC1",
    "C6F5": "*c1c(F)c(F)c(F)c(F)c1F",
}


def _merge_rdkit_abbreviations() -> None:
    """Add RDKit's default abbreviations that the table above does not define."""
    try:
        from rdkit.Chem import rdAbbreviations  # noqa: PLC0415
    except ImportError:  # pragma: no cover - old RDKit
        return
    for abbreviation in rdAbbreviations.GetDefaultAbbreviations():
        label = str(abbreviation.label)
        if label in ABBREVIATIONS:
            continue
        smiles = Chem.MolToSmiles(abbreviation.mol)
        if smiles.count("*") == 1:
            ABBREVIATIONS[label] = smiles


_merge_rdkit_abbreviations()

# Display name → SMILES of common counter-ions, acids and solvents.
SALTS_AND_SOLVENTS: tuple[tuple[str, str], ...] = (
    ("HCl", "Cl"),
    ("HBr", "Br"),
    ("HI", "I"),
    ("H₂SO₄", "OS(=O)(=O)O"),
    ("TFA", "OC(=O)C(F)(F)F"),
    ("AcOH", "CC(=O)O"),
    ("Na⁺", "[Na+]"),
    ("K⁺", "[K+]"),
    ("Li⁺", "[Li+]"),
    ("NH₄⁺", "[NH4+]"),
    ("Ca²⁺", "[Ca+2]"),
    ("Mg²⁺", "[Mg+2]"),
    ("Cl⁻", "[Cl-]"),
    ("Br⁻", "[Br-]"),
    ("I⁻", "[I-]"),
    ("OH⁻", "[OH-]"),
    ("HSO₄⁻", "OS(=O)(=O)[O-]"),
    ("AcO⁻", "CC(=O)[O-]"),
    ("H₂O", "O"),
    ("MeOH", "CO"),
    ("EtOH", "CCO"),
    ("DMSO", "CS(C)=O"),
    ("CHCl₃", "ClC(Cl)Cl"),
    ("Et₂O", "CCOCC"),
)


def pretty_label(label: str) -> str:
    """``CO2Et`` → ``CO₂Et`` (digits after letters become subscripts)."""
    return re.sub(r"(?<=[A-Za-z)])(\d+)", lambda m: m.group(1).translate(_SUBSCRIPTS), label)


# ---------------------------------------------------------------------------
# Building fragments
# ---------------------------------------------------------------------------


def _with_coordinates(mol: Chem.Mol) -> Chem.Mol:
    rdDepictor.Compute2DCoords(mol)
    return mol


def fragment_from_smiles(smiles: str, label: str = "") -> Fragment | None:
    """Fragment from SMILES; a single ``*`` marks the attachment point."""
    text = (smiles or "").strip()
    if not text:
        return None
    blocker = rdBase.BlockLogs()
    try:
        mol = Chem.MolFromSmiles(text)
        if mol is None:
            return None
        try:
            Chem.Kekulize(mol, clearAromaticFlags=True)
        except Exception:  # noqa: BLE001
            return None
    finally:
        del blocker
    dummies = [a.GetIdx() for a in mol.GetAtoms() if a.GetAtomicNum() == 0]
    if len(dummies) > 1:
        return None
    _with_coordinates(mol)
    if not dummies:
        return Fragment(mol=mol, attach=0 if mol.GetNumAtoms() else None, label=label)
    dummy = mol.GetAtomWithIdx(dummies[0])
    neighbours = [n.GetIdx() for n in dummy.GetNeighbors()]
    if len(neighbours) != 1:
        return None
    pos = mol.GetConformer().GetAtomPosition(dummies[0])
    anchor = (pos.x, pos.y)
    attach = neighbours[0]
    rw = Chem.RWMol(mol)
    rw.RemoveAtom(dummies[0])
    if attach > dummies[0]:
        attach -= 1
    out = rw.GetMol()
    out.UpdatePropertyCache(strict=False)
    if out.GetNumAtoms() == 0:
        return None
    return Fragment(mol=out, attach=attach, anchor=anchor, label=label)


def parse_condensed_formula(text: str) -> str | None:
    """Turn a linear condensed formula into SMILES with ``*`` at the start.

    Handles what chemists usually type as a substituent label: ``CH2CH2OH``,
    ``OCH2CH3``, ``CH2Cl``, ``N(CH3)2``, ``C(CH3)3``, ``COCH3``, ``CH2COOH``,
    ``CH2CO2Me``, ``CH2CN``, ``CH2NO2``, ``SO2CH3``, ``CF2CF3``.  Returns
    ``None`` when the text is not a formula this parser understands.
    """
    text = (text or "").strip()
    if not text or not re.fullmatch(r"[A-Za-z0-9()]+", text):
        return None
    try:
        body, rest = _parse_sequence(text, 0)
    except ValueError:
        return None
    if rest != len(text) or not body:
        return None
    return "*" + body


_ELEMENT_RE = re.compile(r"Cl|Br|Si|Na|Li|Mg|[BCNOPSFIK]")
# Abbreviations allowed *inside* a condensed formula (longest first).
_INNER_ABBREVIATIONS = (
    "Boc",
    "Cbz",
    "Bn",
    "Ph",
    "Ac",
    "Bz",
    "Ts",
    "Ms",
    "Tf",
    "tBu",
    "iPr",
    "Et",
    "Me",
)
_MONOVALENT = frozenset({"F", "Cl", "Br", "I", "Na", "Li", "K"})


def _abbrev_smiles(label: str) -> str:
    return ABBREVIATIONS[label][1:]  # drop the leading "*"


def _parse_sequence(text: str, pos: int) -> tuple[str, int]:
    """Parse a chain; returns (SMILES of the chain, new position).

    The chain SMILES starts with the first backbone atom; substituents are
    emitted as branches.  Unsaturation comes from the usual conventions:
    ``C(O)`` / ``CO`` with no H on that carbon = carbonyl, ``CHO`` = aldehyde,
    terminal ``CN`` = nitrile, ``NO2`` = nitro, ``SO2``/``SO3H`` = sulfonyl.
    """
    out = ""
    while pos < len(text):
        ch = text[pos]
        if ch == ")":
            break
        if ch == "(":
            inner, pos = _parse_sequence(text, pos + 1)
            if pos >= len(text) or text[pos] != ")":
                raise ValueError("unbalanced")
            pos += 1
            count, pos = _read_count(text, pos)
            if not out:
                raise ValueError("branch without backbone")
            out += f"({inner})" * count
            continue
        abbreviation = next((a for a in _INNER_ABBREVIATIONS if text.startswith(a, pos)), None)
        if abbreviation is not None:
            pos += len(abbreviation)
            count, pos = _read_count(text, pos)
            if out:
                out += f"({_abbrev_smiles(abbreviation)})" * count
            else:
                if count != 1:
                    raise ValueError("count on leading group")
                out = _abbrev_smiles(abbreviation)
            continue
        match = _ELEMENT_RE.match(text, pos)
        if match is None:
            raise ValueError("unknown token")
        symbol = match.group(0)
        pos = match.end()
        count, pos = _read_count(text, pos)
        hydrogens = 0
        if pos < len(text) and text[pos] == "H":
            pos += 1
            hydrogens, pos = _read_count(text, pos)
        # Special groups recognised by their spelling.
        if symbol == "N" and text.startswith("O2", pos) and hydrogens == 0:
            pos += 2
            out += "[N+](=O)[O-]"
            continue
        if symbol == "S" and hydrogens == 0 and text.startswith("O", pos):
            n_oxygen, after = _read_count(text, pos + 1)
            if n_oxygen in (2, 3):
                pos = after
                tail = ""
                if n_oxygen == 3:
                    tail = "O"
                    if pos < len(text) and text[pos] == "H":
                        pos += 1
                out += "S(=O)(=O)" + tail
                continue
        if symbol == "C" and hydrogens == 0 and count == 1 and text.startswith("O", pos):
            # Carbonyl: CO2R / COOR / COR / COCl / CONH2
            if text.startswith("O2", pos) or text.startswith("OO", pos):
                pos += 2
                if pos < len(text) and text[pos] == "H":
                    pos += 1
                out += "C(=O)O"
                continue
            pos += 1
            out += "C(=O)"
            continue
        if symbol == "C" and hydrogens == 1 and count == 1 and text.startswith("O", pos):
            nxt = pos + 1
            if nxt == len(text) or text[nxt] == ")":
                pos = nxt
                out += "C=O"
                continue
        if symbol == "C" and hydrogens == 0 and count == 1 and text.startswith("N", pos):
            nxt = pos + 1
            if nxt == len(text) or text[nxt] == ")":
                pos = nxt
                out += "C#N"
                continue
        atom = f"[{symbol}]" if symbol in ("Na", "Li", "K", "Mg") else symbol
        if symbol in _MONOVALENT:
            if not out:
                if count != 1:
                    raise ValueError("leading halogen count")
                out = atom
            else:
                out += f"({atom})" * count
            continue
        out += atom * count
    return out, pos


def _read_count(text: str, pos: int) -> tuple[int, int]:
    match = re.match(r"\d+", text[pos:])
    if match is None:
        return 1, pos
    value = int(match.group(0))
    if value <= 0 or value > 20:
        raise ValueError("bad count")
    return value, pos + len(match.group(0))


def parse_group(text: str, custom_groups: dict[str, str] | None = None) -> Fragment | None:
    """Interpret what the user typed as a substituent.

    Order: user-defined groups, abbreviations (``OMe``, ``CO2Et``, ``NHBoc`` …,
    with or without a leading ``-``), SMILES (``*`` = attachment, otherwise
    the first atom), then condensed formulas (``CH2CH2OH``).
    """
    raw = (text or "").strip()
    if not raw:
        return None
    key = raw.lstrip("-–—").strip()
    if not key:
        return None
    if custom_groups:
        for name, smiles in custom_groups.items():
            if name == key or name.lstrip("-") == key:
                fragment = fragment_from_smiles(smiles, label=name)
                if fragment is not None:
                    return fragment
    if key in ABBREVIATIONS:
        return fragment_from_smiles(ABBREVIATIONS[key], label=key)
    lowered = {k.lower(): k for k in ABBREVIATIONS}
    if key.lower() in lowered and len(key) > 2:
        name = lowered[key.lower()]
        return fragment_from_smiles(ABBREVIATIONS[name], label=name)
    fragment = fragment_from_smiles(key, label=key)
    if fragment is not None:
        return fragment
    condensed = parse_condensed_formula(key)
    if condensed is not None:
        fragment = fragment_from_smiles(condensed, label=key)
        if fragment is not None and not _has_valence_problem(fragment.mol):
            return fragment
    return None


def _has_valence_problem(mol: Chem.Mol) -> bool:
    blocker = rdBase.BlockLogs()
    try:
        problems = Chem.DetectChemistryProblems(Chem.Mol(mol))
    finally:
        del blocker
    return any(p.GetType() == "AtomValenceException" for p in problems)


def is_valid_group_smiles(smiles: str) -> bool:
    """True when *smiles* can be stored as a custom group."""
    return fragment_from_smiles(smiles) is not None


def fragment_to_group_smiles(fragment: Fragment) -> str:
    """SMILES with ``*`` on the attachment atom, as stored for custom groups."""
    rw = Chem.RWMol(fragment.mol)
    if fragment.attach is not None:
        dummy = rw.AddAtom(Chem.Atom(0))
        rw.AddBond(fragment.attach, dummy, Chem.BondType.SINGLE)
    mol = rw.GetMol()
    blocker = rdBase.BlockLogs()
    try:
        try:
            Chem.SanitizeMol(mol)
        except Exception:  # noqa: BLE001
            mol.UpdatePropertyCache(strict=False)
        return str(Chem.MolToSmiles(mol))
    finally:
        del blocker
