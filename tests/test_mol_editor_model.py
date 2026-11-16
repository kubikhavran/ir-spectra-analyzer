"""Tests for the native molecule editor model (chemistry.mol_editor_model)."""

from __future__ import annotations

import math

import pytest

pytest.importorskip("rdkit")

from chemistry.mol_editor_model import (  # noqa: E402
    BOND_LENGTH,
    FUNCTIONAL_GROUPS,
    RING_TEMPLATES,
    UNDO_LIMIT,
    MolEditorModel,
    format_formula,
)


def _canon(smiles: str) -> str:
    from rdkit import Chem

    return Chem.MolToSmiles(Chem.MolFromSmiles(smiles))


def _bond_length(model: MolEditorModel, a: int, b: int) -> float:
    ax, ay = model.atom_position(a)
    bx, by = model.atom_position(b)
    return math.hypot(ax - bx, ay - by)


# ---------------------------------------------------------------------------
# IO round trips
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "smiles",
    [
        "CCO",
        "c1ccccc1O",
        "C[C@H](N)O",
        "C/C=C/C",
        "[NH4+]",
        "CC(=O)[O-]",
        "c1ccc2ccccc2c1",
        "c1cc[nH]c1",
        "[Na+].[Cl-]",
    ],
)
def test_smiles_round_trip_through_smiles_and_mol_block(smiles):
    model = MolEditorModel.from_smiles(smiles)
    assert model.to_smiles() == _canon(smiles)
    reloaded = MolEditorModel.from_mol_block(model.to_mol_block())
    assert reloaded.to_smiles() == _canon(smiles)


def test_model_is_kept_in_kekule_form():
    model = MolEditorModel.from_smiles("c1ccccc1")
    orders = sorted(model.bond_order(i) for i in range(model.bond_count))
    assert orders == [1, 1, 1, 2, 2, 2]


def test_from_smiles_rejects_invalid_input():
    with pytest.raises(ValueError, match="Invalid SMILES"):
        MolEditorModel.from_smiles("not_a_smiles_xyz!!!")
    model = MolEditorModel()
    assert model.load_smiles("C1CC") is False


def test_mol_block_preserves_drawn_coordinates():
    model = MolEditorModel()
    a = model.add_free_atom(3.0, -2.0)
    model.sprout_atom(a, "O", preferred_angle=90.0)
    reloaded = MolEditorModel.from_mol_block(model.to_mol_block())
    assert reloaded.atom_position(0) == pytest.approx((3.0, -2.0), abs=1e-3)
    assert reloaded.atom_position(1) == pytest.approx((3.0, -2.0 + BOND_LENGTH), abs=1e-3)


def test_empty_model_exports_empty_strings():
    model = MolEditorModel()
    assert model.to_smiles() == ""
    assert model.to_mol_block() == ""
    assert model.molecular_formula() == ""
    assert model.molecular_weight() == 0.0
    assert model.bounds() is None


def test_invalid_mol_block_is_rejected():
    with pytest.raises(ValueError, match="Invalid MOL block"):
        MolEditorModel.from_mol_block("FAKE MOL")


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


def test_formula_weight_and_hydrogens():
    model = MolEditorModel.from_smiles("CCO")
    assert model.molecular_formula() == "C₂H₆O"
    assert model.molecular_weight() == pytest.approx(46.07, abs=0.01)
    hydrogens = sorted(model.implicit_hydrogens(i) for i in range(model.atom_count))
    assert hydrogens == [1, 2, 3]


def test_format_formula_uses_unicode_sub_and_superscripts():
    assert format_formula("C2H3O2-") == "C₂H₃O₂⁻"
    assert format_formula("O-2") == "O²⁻"
    assert format_formula("H4N+") == "H₄N⁺"


def test_invalid_valence_is_reported():
    model = MolEditorModel.from_smiles("C")
    for _ in range(5):
        model.sprout_atom(0)
    assert model.invalid_atom_indices() == {0}


def test_metal_atoms_get_no_implicit_hydrogens():
    model = MolEditorModel()
    idx = model.add_free_atom(0.0, 0.0, "Na")
    assert model.implicit_hydrogens(idx) == 0
    assert model.to_smiles() == "[Na]"


# ---------------------------------------------------------------------------
# Editing
# ---------------------------------------------------------------------------


def test_sprout_from_lone_atom_grows_at_30_degrees():
    model = MolEditorModel()
    a = model.add_free_atom(0.0, 0.0)
    b = model.sprout_atom(a)
    x, y = model.atom_position(b)
    assert math.degrees(math.atan2(y, x)) == pytest.approx(30.0)
    assert _bond_length(model, a, b) == pytest.approx(BOND_LENGTH)


def test_sprout_builds_a_trans_zigzag_chain():
    model = MolEditorModel()
    atoms = [model.add_free_atom(0.0, 0.0)]
    for _ in range(4):
        atoms.append(model.sprout_atom(atoms[-1]))
    ys = [model.atom_position(i)[1] for i in atoms]
    # Alternating up/down: a zig-zag, not a curl.
    assert ys[0] == pytest.approx(ys[2]) == pytest.approx(ys[4])
    assert ys[1] == pytest.approx(ys[3])
    xs = [model.atom_position(i)[0] for i in atoms]
    assert xs == sorted(xs)
    assert model.to_smiles() == "CCCCC"


def test_sprout_on_two_substituted_atom_uses_outer_bisector():
    model = MolEditorModel.from_smiles("CCC")
    branch = model.sprout_atom(1)
    cx, cy = model.atom_position(1)
    bx, by = model.atom_position(branch)
    for n in (0, 2):
        nx, ny = model.atom_position(n)
        # The new bond points away from both existing neighbours.
        assert (bx - cx) * (nx - cx) + (by - cy) * (ny - cy) < 0
    assert model.to_smiles() == "CC(C)C"


def test_sprout_into_largest_gap_for_crowded_atom():
    model = MolEditorModel.from_smiles("CC(C)C")
    center = next(i for i in range(model.atom_count) if model.atom_degree(i) == 3)
    new = model.sprout_atom(center)
    assert model.to_smiles() == "CC(C)(C)C"
    nx, ny = model.atom_position(new)
    for other in range(model.atom_count):
        if other not in (new, center):
            ox, oy = model.atom_position(other)
            assert math.hypot(nx - ox, ny - oy) > 0.8 * BOND_LENGTH


def test_triple_bond_continues_linearly():
    model = MolEditorModel()
    a = model.add_free_atom(0.0, 0.0)
    b = model.sprout_atom(a, preferred_angle=0.0)
    c = model.sprout_atom(b, "N", bond_order=3)
    assert model.atom_position(c) == pytest.approx((2 * BOND_LENGTH, 0.0))
    assert model.to_smiles() == "CC#N"


def test_set_atom_symbol_and_charge():
    model = MolEditorModel.from_smiles("CC")
    model.set_atom_symbol(1, "N")
    assert model.to_smiles() == "CN"
    model.set_atom_charge(1, 1)
    assert model.to_smiles() == "C[NH3+]"
    model.set_atom_charge(1, 0, relative=False)
    assert model.to_smiles() == "CN"
    with pytest.raises(ValueError, match="Unknown element"):
        model.set_atom_symbol(0, "Xx")


def test_bond_cycles_single_double_triple():
    model = MolEditorModel.from_smiles("CC")
    seen = []
    for _ in range(3):
        model.add_or_update_bond(0, 1, 1)
        seen.append(model.to_smiles())
    assert seen == ["C=C", "C#C", "CC"]


def test_new_bond_between_atoms_and_explicit_order():
    model = MolEditorModel()
    a = model.add_free_atom(0.0, 0.0)
    b = model.add_free_atom(BOND_LENGTH, 0.0, "O")
    model.add_or_update_bond(a, b, 2)
    assert model.to_smiles() == "C=O"
    model.add_or_update_bond(a, b, 2, cycle_on_existing=False)
    assert model.to_smiles() == "C=O"


def test_wedge_bond_defines_stereocentre_and_flips():
    model = MolEditorModel.from_smiles("CC(N)O")
    center = 1
    methyl = 0
    model.add_or_update_bond(center, methyl, 1, "wedge")
    first = model.to_smiles()
    assert "@" in first
    bond = model.find_bond(center, methyl)
    assert bond is not None
    assert model.bond_stereo(bond) == "wedge"
    model.add_or_update_bond(center, methyl, 1, "hash")
    second = model.to_smiles()
    assert "@" in second
    assert second != first


def test_delete_atom_and_bond():
    model = MolEditorModel.from_smiles("CCO")
    bond = model.find_bond(1, 2)
    assert bond is not None
    model.delete_bond(bond)
    assert model.to_smiles() == "CC.O"
    model.delete_atom(2)
    assert model.to_smiles() == "CC"


def test_move_atom_and_fragment():
    model = MolEditorModel.from_smiles("CC.O")
    before = [model.atom_position(i) for i in range(3)]
    model.move_fragment(0, 1.0, 2.0, record_undo=True)
    after = [model.atom_position(i) for i in range(3)]
    assert after[0] == pytest.approx((before[0][0] + 1, before[0][1] + 2))
    assert after[1] == pytest.approx((before[1][0] + 1, before[1][1] + 2))
    assert after[2] == pytest.approx(before[2])
    model.move_atom(2, 9.0, 9.0)
    assert model.atom_position(2) == pytest.approx((9.0, 9.0))
    assert model.undo()
    assert model.atom_position(0) == pytest.approx(before[0])


# ---------------------------------------------------------------------------
# Undo / redo
# ---------------------------------------------------------------------------


def test_undo_redo_and_clear():
    model = MolEditorModel()
    assert not model.can_undo()
    a = model.add_free_atom(0.0, 0.0)
    model.sprout_atom(a, "O")
    assert model.to_smiles() == "CO"
    assert model.undo()
    assert model.to_smiles() == "C"
    assert model.can_redo()
    assert model.redo()
    assert model.to_smiles() == "CO"
    model.clear()
    assert model.is_empty()
    assert model.undo()
    assert model.to_smiles() == "CO"
    # A new edit drops the redo history.
    model.undo()
    model.sprout_atom(0, "N")
    assert not model.can_redo()


def test_undo_history_is_capped():
    model = MolEditorModel()
    model.add_free_atom(0.0, 0.0)
    for _ in range(UNDO_LIMIT + 20):
        model.move_atom(0, 1.0, 1.0, record_undo=True)
    count = 0
    while model.undo():
        count += 1
    assert count == UNDO_LIMIT


# ---------------------------------------------------------------------------
# Chain, rings, groups, layout
# ---------------------------------------------------------------------------


def test_add_chain_bond_count_follows_drag_length():
    model = MolEditorModel()
    step = BOND_LENGTH * math.cos(math.radians(30))
    atoms = model.add_chain(0.0, 0.0, 5 * step, 0.0)
    assert len(atoms) == 6  # new start atom + 5 bonds
    assert model.to_smiles() == "CCCCCC"
    assert MolEditorModel.chain_length(0, 0, 0.1, 0) == 1
    for a, b in zip(atoms, atoms[1:], strict=False):
        assert _bond_length(model, a, b) == pytest.approx(BOND_LENGTH)


def test_add_chain_from_existing_atom():
    model = MolEditorModel.from_smiles("O")
    x, y = model.atom_position(0)
    created = model.add_chain(x, y, x + 4.0, y, start_atom_idx=0)
    assert len(created) == 3
    assert model.to_smiles() == "CCCO"


@pytest.mark.parametrize("ring_type", sorted(RING_TEMPLATES))
def test_every_ring_template_can_be_placed(ring_type):
    model = MolEditorModel()
    atoms = model.add_ring_template(ring_type, center=(0.0, 0.0))
    assert len(atoms) == model.atom_count
    assert not model.invalid_atom_indices()
    from rdkit import Chem

    assert Chem.MolFromSmiles(model.to_smiles()) is not None


def test_ring_bond_lengths_are_standard():
    model = MolEditorModel()
    model.add_ring_template("cyclohexane", center=(0.0, 0.0))
    for bond in range(model.bond_count):
        a, b = model.bond_atoms(bond)
        assert _bond_length(model, a, b) == pytest.approx(BOND_LENGTH, abs=1e-3)


@pytest.mark.parametrize("bond_idx", range(6))
def test_benzene_fusion_gives_naphthalene_on_any_bond(bond_idx):
    model = MolEditorModel.from_smiles("c1ccccc1")
    model.add_ring_template("benzene", target_bond_idx=bond_idx)
    assert model.to_smiles() == _canon("c1ccc2ccccc2c1")
    assert not model.invalid_atom_indices()


@pytest.mark.parametrize(
    ("ring_type", "expected"),
    [
        ("furan", "c1ccc2occc2c1"),
        ("thiophene", "c1ccc2sccc2c1"),
        ("pyrrole", "c1ccc2[nH]ccc2c1"),
        ("cyclopentane", "c1ccc2c(c1)CCC2"),
    ],
)
def test_heteroaromatic_fusion(ring_type, expected):
    model = MolEditorModel.from_smiles("c1ccccc1")
    model.add_ring_template(ring_type, target_bond_idx=0)
    assert model.to_smiles() == _canon(expected)


def test_fusion_goes_to_less_crowded_side():
    model = MolEditorModel.from_smiles("c1ccccc1")
    ring_center = model.bond_ring_center(0)
    assert ring_center is not None
    model.add_ring_template("cyclohexane", target_bond_idx=0)
    assert model.atom_count == 10
    new_atoms = range(6, 10)
    for idx in new_atoms:
        x, y = model.atom_position(idx)
        assert math.hypot(x - ring_center[0], y - ring_center[1]) > BOND_LENGTH


@pytest.mark.parametrize(
    ("ring_type", "expected"),
    [
        ("benzene", "CCc1ccccc1"),
        ("pyridine", "CCc1ccncc1"),
        ("cyclopropane", "CCC1CC1"),
        ("naphthalene", "CCc1cccc2ccccc12"),
    ],
)
def test_ring_attached_to_atom(ring_type, expected):
    model = MolEditorModel.from_smiles("CC")
    model.add_ring_template(ring_type, target_atom_idx=1)
    assert model.to_smiles() == _canon(expected)


def test_ring_through_lone_atom_reuses_it():
    model = MolEditorModel()
    a = model.add_free_atom(0.0, 0.0)
    atoms = model.add_ring_template("cyclohexane", target_atom_idx=a)
    assert a in atoms
    assert model.atom_count == 6


def test_ring_template_preview_does_not_modify_model():
    model = MolEditorModel.from_smiles("CC")
    coords = model.ring_template_coordinates("benzene", target_atom_idx=1)
    assert len(coords) == 6
    assert model.to_smiles() == "CC"
    assert not model.can_undo()


@pytest.mark.parametrize(
    ("group", "expected"),
    [
        ("-OH", "Oc1ccccc1"),
        ("-NH2", "Nc1ccccc1"),
        ("-COOH", "O=C(O)c1ccccc1"),
        ("-COOMe", "COC(=O)c1ccccc1"),
        ("-CHO", "O=Cc1ccccc1"),
        ("-CN", "N#Cc1ccccc1"),
        ("-NO2", "O=[N+]([O-])c1ccccc1"),
        ("-SO3H", "O=S(=O)(O)c1ccccc1"),
        ("-CF3", "FC(F)(F)c1ccccc1"),
        ("-SiMe3", "C[Si](C)(C)c1ccccc1"),
        ("-TMS", "C[Si](C)(C)c1ccccc1"),
        ("-Ph", "c1ccc(-c2ccccc2)cc1"),
        ("-Ac", "CC(=O)c1ccccc1"),
        ("-Boc", "CC(C)(C)OC(=O)c1ccccc1"),
    ],
)
def test_functional_groups(group, expected):
    model = MolEditorModel.from_smiles("c1ccccc1")
    model.attach_functional_group(0, group)
    assert model.to_smiles() == _canon(expected)
    assert not model.invalid_atom_indices()
    # Every group is placed without atoms landing on top of each other.
    for i in range(model.atom_count):
        for j in range(i + 1, model.atom_count):
            assert _bond_length(model, i, j) > 0.5


def test_functional_group_table_is_complete():
    assert set(FUNCTIONAL_GROUPS) >= {
        "-OH",
        "-NH2",
        "-COOH",
        "-COOMe",
        "-CHO",
        "-CN",
        "-NO2",
        "-SO3H",
        "-CF3",
        "-SiMe3",
        "-TMS",
        "-Ph",
        "-Ac",
        "-Boc",
    }


def test_clean_2d_keeps_structure_stereo_and_centroid():
    model = MolEditorModel.from_smiles("C[C@H](N)O")
    for i in range(model.atom_count):
        x, y = model.atom_position(i)
        model.move_atom(i, x * 1.7 + 10, y * 0.3 - 5)
    centroid = (
        sum(model.atom_position(i)[0] for i in range(model.atom_count)) / model.atom_count,
        sum(model.atom_position(i)[1] for i in range(model.atom_count)) / model.atom_count,
    )
    smiles = model.to_smiles()
    assert model.clean_2d()
    assert model.to_smiles() == smiles == "C[C@H](N)O"
    new_centroid = (
        sum(model.atom_position(i)[0] for i in range(model.atom_count)) / model.atom_count,
        sum(model.atom_position(i)[1] for i in range(model.atom_count)) / model.atom_count,
    )
    assert new_centroid == pytest.approx(centroid)
    for bond in range(model.bond_count):
        a, b = model.bond_atoms(bond)
        assert _bond_length(model, a, b) == pytest.approx(BOND_LENGTH, abs=0.05)
    assert model.undo()


def test_bond_ring_center_for_ring_and_chain_bonds():
    model = MolEditorModel.from_smiles("Cc1ccccc1")
    chain_bond = model.find_bond(0, 1)
    ring_bond = model.find_bond(1, 2)
    assert chain_bond is not None
    assert ring_bond is not None
    assert model.bond_ring_center(chain_bond) is None
    assert model.bond_ring_center(ring_bond) is not None


def test_compound_groups_edits_into_one_undo_step():
    model = MolEditorModel()
    with model.compound():
        a = model.add_free_atom(0.0, 0.0)
        model.sprout_atom(a, "O")
        model.sprout_atom(a, "N")
    assert model.to_smiles() == "NCO"
    assert model.undo()
    assert model.is_empty()
    assert not model.can_undo()


def test_chain_coordinates_match_add_chain():
    model = MolEditorModel()
    preview = model.chain_coordinates(0.0, 0.0, 6.0, 1.0)
    atoms = model.add_chain(0.0, 0.0, 6.0, 1.0)
    placed = [c for i in atoms for c in model.atom_position(i)]
    assert placed == pytest.approx([c for point in preview for c in point])


def test_ring_template_bonds_match_coordinates():
    bonds = MolEditorModel.ring_template_bonds("benzene")
    assert len(bonds) == 6
    assert sorted(order for _a, _b, order in bonds) == [1, 1, 1, 2, 2, 2]
    assert MolEditorModel.ring_template_symbols("pyridine").count("N") == 1
    assert MolEditorModel.ring_template_symbols("furan").count("O") == 1


def test_paste_text_inserts_next_to_existing_drawing():
    model = MolEditorModel.from_smiles("CCO")
    assert model.paste_text("c1ccccc1")
    assert model.to_smiles() == _canon("CCO.c1ccccc1")
    bounds_left = max(model.atom_position(i)[0] for i in range(3))
    assert min(model.atom_position(i)[0] for i in range(3, 9)) > bounds_left
    assert model.undo()
    assert model.to_smiles() == "CCO"
    mol_block = MolEditorModel.from_smiles("O").to_mol_block()
    assert model.paste_text(mol_block)
    assert model.to_smiles() == _canon("CCO.O")
    assert not model.paste_text("not a smiles !!")


# ---------------------------------------------------------------------------
# Charges, atom properties and calculated values
# ---------------------------------------------------------------------------


def test_salt_components_formula_and_charge():
    model = MolEditorModel.from_smiles("C[NH3+].[Cl-]")
    assert model.display_formula() == "CH₆N⁺ · Cl⁻"
    assert model.net_charge() == 0
    neutral = MolEditorModel.from_smiles("CCN.Cl")
    assert neutral.display_formula() == "C₂H₇N · HCl"
    assert len(neutral.components()) == 2
    cation = MolEditorModel.from_smiles("[NH4+]")
    assert cation.net_charge() == 1


def test_exact_mass_and_unsaturation():
    model = MolEditorModel.from_smiles("c1ccccc1C(=O)O")
    assert model.exact_mass() == pytest.approx(122.0368, abs=1e-3)
    assert model.unsaturation() == 5
    assert MolEditorModel.from_smiles("CCO").unsaturation() == 0
    assert MolEditorModel().unsaturation() == 0


@pytest.mark.parametrize(
    ("charge", "expected"),
    [(-1, "C[O-]"), (1, "C[OH2+]"), (0, "CO")],
)
def test_charge_adjusts_hydrogens(charge, expected):
    model = MolEditorModel.from_smiles("CO")
    model.set_atom_properties(1, charge=charge)
    assert model.to_smiles() == expected


def test_charge_on_nitrogen_and_metals():
    model = MolEditorModel.from_smiles("CN")
    model.set_atom_charge(1, 1)
    assert model.to_smiles() == "C[NH3+]"
    metal = MolEditorModel()
    idx = metal.add_free_atom(0.0, 0.0, "Mg")
    metal.set_atom_charge(idx, 2, relative=False)
    assert metal.to_smiles() == "[Mg+2]"
    assert metal.display_formula() == "Mg²⁺"


def test_radicals_isotopes_and_fixed_hydrogens():
    model = MolEditorModel.from_smiles("CC")
    model.set_atom_radicals(1, 1)
    assert model.to_smiles() == "[CH2]C"
    assert model.atom_radicals(1) == 1
    assert ("radical", 1) in model.structure_problems()
    model.set_atom_radicals(1, 0)
    assert model.to_smiles() == "CC"
    model.set_atom_isotope(1, 13)
    assert model.to_smiles() == "C[13CH3]"
    assert model.atom_isotope(1) == 13
    amine = MolEditorModel.from_smiles("CN")
    amine.set_atom_hydrogens(1, 0)
    assert amine.atom_hydrogens_fixed(1)
    assert amine.implicit_hydrogens(1) == 0
    amine.set_atom_hydrogens(1, None)
    assert amine.to_smiles() == "CN"


def test_set_atom_properties_is_one_undo_step():
    model = MolEditorModel.from_smiles("CC")
    model.set_atom_properties(1, symbol="N", charge=1, isotope=15)
    assert model.to_smiles() == "C[15NH3+]"
    assert model.undo()
    assert model.to_smiles() == "CC"


def test_structure_problems_report_valence():
    model = MolEditorModel.from_smiles("C")
    for _ in range(5):
        model.sprout_atom(0)
    assert ("valence", 0) in model.structure_problems()


def test_stereo_labels_and_inchi():
    atoms, bonds = MolEditorModel.from_smiles("C[C@H](N)O").stereo_labels()
    assert atoms == {1: "R"}
    assert bonds == {}
    atoms, bonds = MolEditorModel.from_smiles("C/C=C/C").stereo_labels()
    assert list(bonds.values()) == ["E"]
    inchi, key = MolEditorModel.from_smiles("CC(=O)O").inchi()
    assert inchi.startswith("InChI=1S/C2H4O2")
    assert key == "QTBSBXVTEAMEQO-UHFFFAOYSA-N"
    assert MolEditorModel().inchi() == ("", "")


# ---------------------------------------------------------------------------
# Labels, fragments and transformations
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("OMe", "COc1ccccc1"),
        ("CO2Et", "CCOC(=O)c1ccccc1"),
        ("CH2CH2OH", "OCCc1ccccc1"),
        ("N+", "[NH3+]c1ccccc1"),
        ("O-", "[O-]c1ccccc1"),
        ("D", "[2H]c1ccccc1"),
        ("NHBoc", "CC(C)(C)OC(=O)Nc1ccccc1"),
        ("*OCC(C)C", "CC(C)COc1ccccc1"),
        ("Cl", "Clc1ccccc1"),
    ],
)
def test_apply_label_on_terminal_atom(label, expected):
    model = MolEditorModel.from_smiles("c1ccccc1C")
    assert model.apply_label(6, label)
    assert model.to_smiles() == _canon(expected)
    assert not model.invalid_atom_indices()
    assert model.undo()
    assert model.to_smiles() == "Cc1ccccc1"


def test_apply_label_rejects_unknown_text_and_inner_atoms():
    model = MolEditorModel.from_smiles("CCC")
    assert not model.apply_label(2, "xyz!")
    assert not model.apply_label(1, "OMe")  # not a terminal atom
    assert model.apply_label(1, "N")  # elements are always fine
    assert model.to_smiles() == "CNC"


def test_apply_label_uses_custom_groups():
    model = MolEditorModel.from_smiles("CC")
    assert model.apply_label(1, "Pin", {"Pin": "*B1OC(C)(C)C(C)(C)O1"})
    assert model.to_smiles() == _canon("CB1OC(C)(C)C(C)(C)O1")


def test_copy_part_of_molecule_and_attach_it_to_a_chain():
    source = MolEditorModel.from_smiles("CCCC(=O)O")
    fragment = source.extract_fragment([3, 4, 5])  # the COOH part
    assert fragment.attach == 0
    assert fragment.anchor is not None
    chain = MolEditorModel.from_smiles("CCCCC")
    new_atoms = chain.insert_fragment(fragment, target_atom_idx=4)
    assert chain.to_smiles() == "CCCCCC(=O)O"
    assert fragment.attach is not None
    assert _bond_length(chain, 4, new_atoms[fragment.attach]) == pytest.approx(BOND_LENGTH)
    assert not chain.invalid_atom_indices()
    assert chain.undo()
    assert chain.to_smiles() == "CCCCC"


def test_extract_fragment_resets_hydrogens_and_keeps_charges():
    source = MolEditorModel.from_smiles("CC[N+](=O)[O-]")
    fragment = source.extract_fragment([2, 3, 4])
    target = MolEditorModel.from_smiles("c1ccccc1")
    target.insert_fragment(fragment, target_atom_idx=0)
    assert target.to_smiles() == _canon("O=[N+]([O-])c1ccccc1")


def test_insert_fragment_as_separate_molecule():
    from chemistry.mol_fragments import fragment_from_smiles

    model = MolEditorModel.from_smiles("CCN")
    fragment = fragment_from_smiles("Cl")
    assert fragment is not None
    model.insert_fragment(fragment)
    assert model.to_smiles() == "CCN.Cl"
    bounds_main = max(model.atom_position(i)[0] for i in range(3))
    assert model.atom_position(3)[0] > bounds_main
    model.insert_fragment(fragment, position=(-20.0, 0.0))
    assert model.atom_position(4) == pytest.approx((-20.0, 0.0))


def test_fragment_coordinates_preview_matches_insert():
    from chemistry.mol_fragments import parse_group

    model = MolEditorModel.from_smiles("CCC")
    fragment = parse_group("CO2Me")
    assert fragment is not None
    preview = model.fragment_coordinates(fragment, target_atom_idx=2)
    atoms = model.insert_fragment(fragment, target_atom_idx=2)
    placed = [c for i in atoms for c in model.atom_position(i)]
    assert placed == pytest.approx([c for p in preview for c in p])


def test_rotate_and_flip_keep_structure_and_stereo():
    model = MolEditorModel.from_smiles("C[C@H](N)O")
    before = model.atom_position(0)
    model.rotate_atoms(None, 90.0)
    assert model.to_smiles() == "C[C@H](N)O"
    assert model.atom_position(0) != pytest.approx(before)
    model.flip_atoms(None, horizontal=True)
    assert model.to_smiles() == "C[C@H](N)O"
    model.flip_atoms(None, horizontal=False)
    assert model.to_smiles() == "C[C@H](N)O"
    assert model.undo()
    assert model.undo()
    assert model.undo()
    assert model.atom_position(0) == pytest.approx(before)


def test_rotate_selected_atoms_only():
    model = MolEditorModel.from_smiles("CC.O")
    water = model.atom_position(2)
    model.rotate_atoms([0, 1], 180.0)
    assert model.atom_position(2) == pytest.approx(water)


def test_merge_atoms_joins_fragments():
    model = MolEditorModel.from_smiles("CC.CO")
    keep = model.merge_atoms(1, 2)
    assert model.to_smiles() == "CCO"
    assert keep == 1
    assert model.undo()
    assert model.to_smiles() == "CC.CO"


def test_explicit_hydrogens_round_trip():
    model = MolEditorModel.from_smiles("CO")
    assert model.add_explicit_hydrogens() == 4
    assert model.atom_count == 6
    assert model.to_smiles() == "[H]OC([H])([H])[H]"
    assert model.remove_explicit_hydrogens() == 4
    assert model.to_smiles() == "CO"
    pyrrole = MolEditorModel.from_smiles("c1cc[nH]c1")
    pyrrole.add_explicit_hydrogens()
    pyrrole.remove_explicit_hydrogens()
    assert pyrrole.to_smiles() == "c1cc[nH]c1"
    selected = MolEditorModel.from_smiles("CO")
    assert selected.add_explicit_hydrogens([1]) == 1
    assert MolEditorModel().add_explicit_hydrogens() == 0
