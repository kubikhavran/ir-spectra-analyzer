"""Tests for editor fragments, abbreviations and condensed formulas."""

from __future__ import annotations

import pytest

pytest.importorskip("rdkit")

from rdkit import Chem  # noqa: E402

from chemistry.mol_fragments import (  # noqa: E402
    ABBREVIATIONS,
    SALTS_AND_SOLVENTS,
    Fragment,
    fragment_from_smiles,
    is_valid_group_smiles,
    parse_condensed_formula,
    parse_group,
    pretty_label,
)


def _canon(smiles: str) -> str:
    return Chem.MolToSmiles(Chem.MolFromSmiles(smiles))


def _attached(fragment: Fragment) -> str:
    """SMILES of the fragment bonded to a methyl through its attach atom."""
    rw = Chem.RWMol(fragment.mol)
    idx = rw.AddAtom(Chem.Atom("C"))
    assert fragment.attach is not None
    rw.AddBond(fragment.attach, idx, Chem.BondType.SINGLE)
    mol = rw.GetMol()
    for atom in mol.GetAtoms():
        if atom.GetSymbol() in ("C", "N", "O", "S", "P", "Si") and not atom.GetNumExplicitHs():
            atom.SetNoImplicit(False)
    Chem.SanitizeMol(mol)
    return Chem.MolToSmiles(mol)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("OMe", "COC"),
        ("-OMe", "COC"),
        ("CO2Et", "CCOC(C)=O"),
        ("NHBoc", "CNC(=O)OC(C)(C)C"),
        ("tBu", "CC(C)(C)C"),
        ("Ph", "Cc1ccccc1"),
        ("Ts", "Cc1ccc(S(C)(=O)=O)cc1"),
        ("NO2", "C[N+](=O)[O-]"),
        ("CN", "CC#N"),
        ("*OCC(C)C", "COCC(C)C"),
        ("OCC", "CCOC"),
        ("CH2CH2OH", "CCCO"),
        ("OCH2CH3", "CCOC"),
        ("N(CH3)2", "CN(C)C"),
        ("C(CH3)3", "CC(C)(C)C"),
        ("COCH3", "CC(C)=O"),
        ("CH2COOH", "CCC(=O)O"),
        ("CH2CO2Me", "CCC(=O)OC"),
        ("CH2CN", "CCC#N"),
        ("CH2NO2", "CC[N+](=O)[O-]"),
        ("SO2CH3", "CS(C)(=O)=O"),
        ("CF2CF3", "CC(F)(F)C(F)(F)F"),
        ("CHO", "CC=O"),
        ("C6H5", "Cc1ccccc1"),
    ],
)
def test_parse_group_variants(text, expected):
    fragment = parse_group(text)
    assert fragment is not None
    assert _attached(fragment) == _canon(expected)


def test_parse_group_rejects_nonsense():
    assert parse_group("") is None
    assert parse_group("xyz!") is None
    assert parse_group("**C") is None


def test_custom_groups_take_priority():
    custom = {"Pin": "*B1OC(C)(C)C(C)(C)O1", "CN": "*NC"}
    fragment = parse_group("Pin", custom)
    assert fragment is not None
    assert fragment.label == "Pin"
    assert _attached(fragment) == _canon("CB1OC(C)(C)C(C)(C)O1")
    # A custom definition overrides the built-in abbreviation of the same name.
    override = parse_group("CN", custom)
    assert override is not None
    assert _attached(override) == _canon("CNC")


def test_condensed_formula_parser_output():
    assert parse_condensed_formula("CH2CH2OH") == "*CCO"
    assert parse_condensed_formula("N(CH3)2") == "*N(C)(C)"
    assert parse_condensed_formula("CH2(") is None
    assert parse_condensed_formula("Q") is None


def test_fragment_from_smiles_attach_and_anchor():
    fragment = fragment_from_smiles("*C(=O)O")
    assert fragment is not None
    assert fragment.atom_count == 3
    assert fragment.attach is not None
    assert fragment.mol.GetAtomWithIdx(fragment.attach).GetSymbol() == "C"
    assert fragment.anchor is not None
    plain = fragment_from_smiles("OCC")
    assert plain is not None
    assert plain.attach == 0
    assert plain.anchor is None
    assert fragment_from_smiles("*C*") is None
    assert is_valid_group_smiles("*OC")
    assert not is_valid_group_smiles("not smiles")


def test_fragment_json_round_trip():
    fragment = fragment_from_smiles("*OCC", label="OEt")
    assert fragment is not None
    restored = Fragment.from_json(fragment.to_json())
    assert restored is not None
    assert restored.attach == fragment.attach
    assert restored.anchor == pytest.approx(fragment.anchor)
    assert restored.label == "OEt"
    assert restored.smiles() == fragment.smiles()
    assert Fragment.from_json({"mol_block": "junk"}) is None


def test_abbreviation_and_salt_tables_parse():
    for label, smiles in ABBREVIATIONS.items():
        assert fragment_from_smiles(smiles) is not None, label
    for label, smiles in SALTS_AND_SOLVENTS:
        assert Chem.MolFromSmiles(smiles) is not None, label
    assert pretty_label("CO2Et") == "CO₂Et"
    assert pretty_label("SO3H") == "SO₃H"


def test_fragment_to_group_smiles_round_trip():
    from chemistry.mol_fragments import fragment_to_group_smiles

    fragment = parse_group("CO2Et")
    assert fragment is not None
    smiles = fragment_to_group_smiles(fragment)
    assert smiles.count("*") == 1
    again = fragment_from_smiles(smiles)
    assert again is not None
    assert _attached(again) == _canon("CCOC(C)=O")


def test_custom_group_store(tmp_path):
    from app.custom_groups import CustomGroupStore
    from storage.settings import Settings

    store = CustomGroupStore(Settings(tmp_path / "settings.json"))
    assert store.groups() == {}
    store.save("Pin", "*B1OC(C)(C)C(C)(C)O1")
    reopened = CustomGroupStore(Settings(tmp_path / "settings.json"))
    assert reopened.groups() == {"Pin": "*B1OC(C)(C)C(C)(C)O1"}
    with pytest.raises(ValueError, match="name"):
        reopened.save("  ", "*C")
    assert reopened.remove("Pin")
    assert not reopened.remove("Pin")
    assert reopened.groups() == {}


def test_custom_groups_export_and_import(tmp_path):
    import json

    from app.custom_groups import FILE_FORMAT, CustomGroupStore
    from storage.settings import Settings

    source = CustomGroupStore(Settings(tmp_path / "a.json"))
    source.save("Pin", "*B1OC(C)(C)C(C)(C)O1")
    source.save("Core", "O=C1CCCN1")
    file = tmp_path / "groups.json"
    assert source.export_to(file) == 2
    assert json.loads(file.read_text(encoding="utf-8"))["format"] == FILE_FORMAT

    target = CustomGroupStore(Settings(tmp_path / "b.json"))
    target.save("Pin", "*C")  # replaced by the imported one
    assert target.import_from(file) == (2, [])
    assert target.groups() == {"Pin": "*B1OC(C)(C)C(C)(C)O1", "Core": "O=C1CCCN1"}

    file.write_text(json.dumps({"groups": {"Bad": "not smiles(", "Ok": "*CCO"}}), "utf-8")
    assert target.import_from(file) == (1, ["Bad"])
    file.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ValueError, match="custom-group file"):
        target.import_from(file)
