"""Recognising groups in a drawn structure, and the vibrations they bring."""

from __future__ import annotations

import pytest

from chemistry.structure_motifs import ALL_MOTIFS, perceive_smiles, vibration_names
from storage.database import Database


def _ids(smiles: str) -> set[str]:
    return {found.id for found in perceive_smiles(smiles)}


def test_every_motif_vibration_is_in_the_builtin_library() -> None:
    library = {entry[0] for entry in Database._builtin_vibration_catalog()}
    missing = {(m.id, v) for m in ALL_MOTIFS for v in m.vibrations if v not in library}
    assert not missing


def test_motif_ids_are_unique() -> None:
    ids = [m.id for m in ALL_MOTIFS]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize(
    ("smiles", "expected", "absent"),
    [
        # An ether oxygen bonded to C=O is an ester — not an ether plus a ketone.
        ("COC(C)=O", {"ester", "acetyl"}, {"dialkyl_ether", "ketone", "methoxy"}),
        ("CCOC(=O)CCC(C)=O", {"ester", "ketone"}, {"dialkyl_ether"}),
        ("CCOC(=O)/C=C/c1ccccc1", {"conjugated_ester", "trans_alkene"}, {"ester"}),
        (
            "CC(=O)Oc1ccccc1C(=O)O",
            {"aryl_vinyl_ester", "carboxylic_acid", "ortho_benzene"},
            {"aryl_ether"},
        ),
        ("O=C1CCCO1", {"gamma_lactone"}, {"ester", "cyclic_ether"}),
        ("C=O", {"aldehyde"}, set()),
        ("O=C1CCCC1", {"cyclopentanone"}, {"ketone"}),
        # N–C(=O)–O is a carbamate; the Boc tert-butyl is reported too.
        (
            "CC(C)(C)OC(=O)NCCO",
            {"carbamate", "tert_butyl", "primary_alcohol"},
            {"ester", "secondary_amide"},
        ),
        (
            "NC(=O)Nc1ccccc1",
            {"urea", "monosubstituted_benzene"},
            {"secondary_amide", "aromatic_secondary_amine"},
        ),
        ("O=C1CCC(=O)N1", {"imide"}, {"secondary_amide", "ketone"}),
        ("CC(=O)OC(C)=O", {"anhydride"}, {"ester"}),
        ("COC(=O)Oc1ccccc1", {"carbonate"}, {"ester", "aryl_ether"}),
        ("CC(N)=O", {"primary_amide"}, {"primary_amine"}),
        ("CNC(C)=O", {"secondary_amide", "n_methyl"}, {"secondary_amine"}),
        ("CN(C)C(C)=O", {"tertiary_amide"}, {"tertiary_amine"}),
        ("O=C1CCN1", {"beta_lactam"}, {"secondary_amide"}),
        ("CC(=O)Nc1ccc(O)cc1", {"secondary_amide", "phenol", "para_benzene"}, set()),
        (
            "Cn1cnc2n(C)c(=O)n(C)c(=O)c12",
            {"urea", "tertiary_amide", "imidazole", "n_methyl"},
            set(),
        ),
        ("CC(N)=S", {"thioamide"}, set()),
        # Nitrogen groups.
        ("CCCN=[N+]=[N-]", {"azide"}, {"imine"}),
        ("O=[N+]([O-])c1ccccc1", {"nitro"}, set()),
        ("CO[N+](=O)[O-]", {"nitrate"}, {"nitro"}),
        ("CC#N", {"nitrile"}, set()),
        ("CN=C=O", {"isocyanate"}, set()),
        ("CN=C=S", {"isothiocyanate"}, set()),
        ("CC(C)=NO", {"oxime"}, {"imine"}),
        ("NC(N)=N", {"guanidine_amidine"}, {"primary_amine"}),
        ("CCN", {"primary_amine"}, set()),
        ("CCNCC", {"secondary_amine"}, set()),
        ("CCN(CC)CC", {"tertiary_amine"}, set()),
        ("Nc1ccccc1", {"aromatic_primary_amine"}, {"primary_amine"}),
        ("CC[NH3+]", {"ammonium"}, {"primary_amine"}),
        # Heteroaromatic rings.
        ("c1ccc(cc1)-c1nnn[nH]1", {"tetrazole", "monosubstituted_benzene"}, set()),
        ("Cn1cc(CO)nn1", {"triazole_123", "primary_alcohol"}, set()),
        ("c1nc[nH]n1", {"triazole_124"}, {"imidazole"}),
        ("c1c[nH]cn1", {"imidazole"}, {"pyrazole"}),
        ("c1cc[nH]n1", {"pyrazole"}, set()),
        ("c1ccc2[nH]ccc2c1", {"pyrrole"}, set()),
        ("c1ccncc1", {"pyridine"}, set()),
        ("c1cncnc1", {"diazine"}, {"pyridine"}),
        ("c1ccoc1", {"furan"}, set()),
        ("c1ccsc1", {"thiophene"}, set()),
        ("c1cocn1", {"oxazole"}, set()),
        ("c1cscn1", {"thiazole"}, set()),
        ("c1nnco1", {"oxadiazole"}, {"oxazole"}),
        # Oxygen groups.
        ("CO", {"primary_alcohol", "methyl"}, set()),
        ("CC(C)O", {"secondary_alcohol", "gem_dimethyl"}, set()),
        ("CC(C)(C)O", {"tertiary_alcohol", "tert_butyl"}, set()),
        ("Oc1ccccc1", {"phenol"}, set()),
        ("CCOCC", {"dialkyl_ether"}, set()),
        ("C1CCOC1", {"cyclic_ether"}, {"dialkyl_ether", "long_chain"}),
        ("COc1ccccc1", {"aryl_ether", "methoxy"}, set()),
        ("COC(C)OC", {"acetal"}, {"dialkyl_ether"}),
        ("C1CO1", {"epoxide"}, {"cyclic_ether"}),
        ("C=COC", {"vinyl_ether"}, {"dialkyl_ether"}),
        # Sulfur, phosphorus, boron, silicon, halogens.
        ("Cc1ccc(cc1)S(N)(=O)=O", {"sulfonamide", "para_benzene"}, {"sulfone"}),
        ("CS(=O)(=O)C", {"sulfone"}, set()),
        ("CS(C)=O", {"sulfoxide"}, set()),
        ("CS(=O)(=O)Cl", {"sulfonyl_chloride"}, set()),
        ("CS(=O)(=O)OC", {"sulfonate"}, set()),
        ("CCS", {"thiol"}, set()),
        ("CSC", {"sulfide"}, set()),
        ("CCOP(=O)(OCC)OCC", {"phosphate"}, set()),
        ("CC1(C)OB(c2ccccc2)OC1(C)C", {"boronate_pinacol", "gem_dimethyl"}, {"boronic_acid"}),
        ("OB(O)c1ccccc1", {"boronic_acid"}, set()),
        ("CC(C)(C)[Si](C)(C)OCC", {"tbs"}, {"tms"}),
        ("C[Si](C)(C)OC", {"tms", "silyl_ether"}, set()),
        ("FC(F)(F)c1ccccc1", {"trifluoromethyl"}, set()),
        ("Clc1ccccc1", {"aryl_chloride"}, {"alkyl_chloride"}),
        ("CCCl", {"alkyl_chloride"}, set()),
        ("CCBr", {"bromide"}, set()),
        # Unsaturation.
        ("C#CC", {"terminal_alkyne"}, set()),
        ("CC#CC", {"internal_alkyne"}, set()),
        ("C=CC", {"vinyl"}, set()),
        ("C=C(C)C", {"vinylidene"}, set()),
        (r"C/C=C\C", {"cis_alkene"}, {"trans_alkene", "disubstituted_alkene"}),
        ("CC=CC", {"disubstituted_alkene"}, {"cis_alkene", "trans_alkene"}),
        ("C=CC=C", {"conjugated_diene"}, set()),
        ("CCCCCCCC", {"long_chain", "methylene", "methyl"}, set()),
        ("C1CC1C", {"cyclopropyl"}, set()),
    ],
)
def test_structures_are_read_the_way_a_chemist_names_them(
    smiles: str, expected: set[str], absent: set[str]
) -> None:
    ids = _ids(smiles)
    assert expected <= ids, expected - ids
    assert not (absent & ids), absent & ids


def test_counts_and_atoms_are_reported() -> None:
    found = {f.id: f for f in perceive_smiles("CCOC(=O)CC(=O)OCC")}
    assert found["ester"].count == 2
    assert all(len(atoms) >= 3 for atoms in found["ester"].matches)


def test_salt_drawing_reports_both_parts() -> None:
    ids = _ids("CC[NH3+].[Cl-].OC(=O)c1ccccc1")
    assert {"ammonium", "carboxylic_acid"} <= ids


def test_vibration_names_cover_the_found_motifs() -> None:
    names = vibration_names(perceive_smiles("CCOC(C)=O"))
    assert "ν(C=O) –CO–O– sat. ester" in names
    assert "νas(CH₃) –CH₃" in names
    assert not any("amide" in name for name in names)


def test_empty_or_invalid_structure() -> None:
    assert perceive_smiles("") == []
    assert perceive_smiles("not a smiles") == []


@pytest.mark.parametrize(
    ("smiles", "expected", "absent"),
    [
        # Groups added from the laboratory's evaluated spectra.
        ("Cn1ccccc1=O", {"pyridone"}, {"tertiary_amide", "pyridine"}),
        ("O=C1CCCN1", {"gamma_lactam"}, set()),
        ("c1ccc2ncccc2c1", {"quinoline"}, {"pyridine"}),
        ("c1ccc2cnccc2c1", {"pyridine"}, {"quinoline"}),
        ("Cc1cc(C)on1", {"isoxazole"}, {"oxazole"}),
        ("c1cocn1", {"oxazole"}, {"isoxazole"}),
        ("c1cnccn1", {"pyrazine"}, {"diazine"}),
        ("c1cncnc1", {"diazine"}, {"pyrazine"}),
        ("CC1(C)Cc2ccccc2C1", {"indane"}, set()),
        ("c1ccc(cc1)-c1ccccc1", {"biphenyl"}, set()),
        ("CC(=O)OCC", {"ester", "acetate"}, set()),
        ("CC(C)(C)OC(=O)NC", {"carbamate", "tert_butoxy", "tert_butyl"}, set()),
        # Salts drawn neutral with their acid as a separate part.
        ("NCCN.Cl", {"ammonium", "primary_amine"}, set()),
        ("CCN(CC)CC.CCOS(=O)(=O)O", {"ammonium", "sulfate"}, set()),
        ("NCCN", {"primary_amine"}, {"ammonium"}),
        ("c1ccccc1N.Cl", {"aromatic_primary_amine"}, {"ammonium"}),
    ],
)
def test_groups_from_the_laboratory_spectra(
    smiles: str, expected: set[str], absent: set[str]
) -> None:
    ids = _ids(smiles)
    assert expected <= ids, expected - ids
    assert not (absent & ids), absent & ids


def test_lab_verified_bands_reach_their_groups() -> None:
    names = vibration_names(perceive_smiles("Cn1ccccc1=O"))
    assert "ν(C=O) 2-pyridone" in names
    assert "2-pyridone ring ~1236" in names
    salt = vibration_names(perceive_smiles("CC[NH3+].[Cl-]"))
    assert "comb. R–NH₃⁺ salt indicator ~2030" in salt
    assert "νas(NH₃⁺) R–NH₃⁺" in salt
    assert "δs(CH₃) –CH₃ umbrella" in vibration_names(perceive_smiles("CC"))


def test_abbreviated_smiles_from_older_projects_are_read() -> None:
    ids = _ids("CC1OC(C[OAc])C([OAc])C1[OAc]")
    assert {"ester", "acetate"} <= ids
    salt = _ids("NCCCN(CCCN)CC(=O)NC.[HCl].[HCl].[.6]")
    assert {"ammonium", "secondary_amide"} <= salt
    assert _ids("C[C@H]([OBn])CO") >= {"dialkyl_ether", "primary_alcohol"}


@pytest.mark.parametrize(
    ("ring_type", "motif"),
    [
        ("pyrazine", "pyrazine"),
        ("pyridone", "pyridone"),
        ("pyrazole", "pyrazole"),
        ("oxazole", "oxazole"),
        ("isoxazole", "isoxazole"),
        ("thiazole", "thiazole"),
        ("triazole_123", "triazole_123"),
        ("triazole_124", "triazole_124"),
        ("tetrazole", "tetrazole"),
        ("quinoline", "quinoline"),
        ("indane", "indane"),
        ("biphenyl", "biphenyl"),
        ("pyrrolidone", "gamma_lactam"),
    ],
)
def test_editor_ring_quick_picks_are_recognised(ring_type: str, motif: str) -> None:
    from chemistry.mol_editor_model import MolEditorModel

    model = MolEditorModel.from_smiles("CCCC")
    model.add_ring_template(ring_type, target_atom_idx=3)
    assert not model.invalid_atom_indices()
    assert motif in {f.id for f in perceive_smiles(model.to_smiles())}


@pytest.mark.parametrize(
    ("group", "motifs"),
    [
        ("-OMe", {"methoxy"}),
        ("-OAc", {"acetate"}),
        ("-tBu", {"tert_butyl"}),
        ("-OtBu", {"tert_butoxy"}),
        ("-NHAc", {"secondary_amide"}),
        ("-NHBoc", {"carbamate", "tert_butoxy"}),
        ("-N3", {"azide"}),
        ("-SO3-", {"sulfonate"}),
        ("-OTBS", {"tbs", "silyl_ether"}),
        ("-OTIPS", {"tips", "silyl_ether"}),
    ],
)
def test_editor_group_quick_picks_are_recognised(group: str, motifs: set[str]) -> None:
    from chemistry.mol_editor_model import MolEditorModel

    for start, atom in (("c1ccccc1", 0), ("CC(C)C", 1)):
        model = MolEditorModel.from_smiles(start)
        model.attach_functional_group(atom, group)
        assert not model.invalid_atom_indices()
        smiles = model.to_smiles()
        assert motifs <= {f.id for f in perceive_smiles(smiles)}, smiles
