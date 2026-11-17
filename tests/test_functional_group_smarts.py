"""Structure -> knowledge-base groups, the ground truth of the benchmark and structure check."""

from __future__ import annotations

import pytest

from chemistry.functional_group_smarts import KNOWN_GROUP_IDS, groups_in_smiles
from storage.functional_group_repository import FunctionalGroupRepository


def _present(smiles: str) -> set[str]:
    result = groups_in_smiles(smiles)
    assert result is not None
    return set(result.present)


def test_every_knowledge_base_group_has_a_definition() -> None:
    groups = {group.id for group in FunctionalGroupRepository().load().groups}
    assert groups == KNOWN_GROUP_IDS


@pytest.mark.parametrize(
    ("smiles", "expected", "absent"),
    [
        (
            "CCOC(C)=O",
            {"ester", "aliphatic_hydrocarbon"},
            {"carboxylic_acid", "ketone", "aliphatic_ether"},
        ),
        ("CC(=O)O", {"carboxylic_acid"}, {"ester", "alcohol"}),
        ("CCO", {"alcohol", "primary_alcohol"}, {"secondary_alcohol", "aliphatic_ether"}),
        ("CC(C)O", {"secondary_alcohol", "isopropyl_group"}, {"primary_alcohol"}),
        ("CC(C)(C)O", {"tertiary_alcohol", "tert_butyl_group"}, set()),
        ("Oc1ccccc1", {"phenol", "aromatic_ring", "monosubstituted_benzene"}, {"alcohol"}),
        ("CC(N)=O", {"amide", "primary_amide"}, {"amine", "primary_amine"}),
        ("CNC(C)=O", {"amide", "secondary_amide"}, {"amine"}),
        ("Nc1ccccc1", {"amine", "primary_amine", "aromatic_amine"}, {"amide"}),
        ("CCOCC", {"aliphatic_ether"}, {"ester", "aryl_ether"}),
        ("COc1ccccc1", {"aryl_ether", "monosubstituted_benzene"}, {"aliphatic_ether"}),
        ("CC#N", {"nitrile"}, set()),
        ("C[N+](=O)[O-]", {"nitro"}, set()),
        ("C1CO1", {"epoxide", "aliphatic_ether"}, set()),
        ("C=CC", {"alkene", "terminal_alkene"}, {"aromatic_ring"}),
        ("C=C(C)C", {"alkene", "vinylidene_alkene"}, {"terminal_alkene"}),
        ("CC(=O)C", {"ketone"}, {"aldehyde"}),
        ("CC=O", {"aldehyde"}, {"ketone"}),
        ("CS(C)=O", {"sulfoxide"}, {"sulfone"}),
        ("CS(=O)(=O)C", {"sulfone"}, {"sulfoxide"}),
        ("CS(N)(=O)=O", {"sulfonamide"}, set()),
        ("C[Si](C)(C)O[Si](C)(C)C", {"siloxane_silicone", "tms_group"}, set()),
        ("CCCCCCCC", {"long_chain_n_alkyl", "methylene_rich_alkyl", "methyl_rich_alkyl"}, set()),
        ("c1ccccc1", {"benzene", "aromatic_ring"}, {"monosubstituted_benzene"}),
    ],
)
def test_structures_map_to_their_groups(smiles: str, expected: set[str], absent: set[str]) -> None:
    present = _present(smiles)
    assert expected <= present, expected - present
    assert not (absent & present), absent & present


@pytest.mark.parametrize(
    ("smiles", "pattern"),
    [
        ("Cc1ccccc1C", "ortho_disubstituted_benzene"),
        ("Cc1cccc(C)c1", "meta_disubstituted_benzene"),
        ("Cc1ccc(C)cc1", "para_disubstituted_benzene"),
        ("Cc1ccc(C)c(C)c1", "trisubstituted_benzene_1_2_4"),
        ("Cc1cccc(C)c1C", "trisubstituted_benzene_1_2_3"),
        ("Cc1cc(C)cc(C)c1", "trisubstituted_benzene_1_3_5"),
    ],
)
def test_benzene_substitution_patterns(smiles: str, pattern: str) -> None:
    present = _present(smiles)
    assert pattern in present
    others = {
        "monosubstituted_benzene",
        "ortho_disubstituted_benzene",
        "meta_disubstituted_benzene",
        "para_disubstituted_benzene",
        "trisubstituted_benzene_1_2_4",
        "trisubstituted_benzene_1_2_3",
        "trisubstituted_benzene_1_3_5",
    } - {pattern}
    assert not (others & present)


def test_alkene_geometry_is_decided_only_when_drawn() -> None:
    trans = groups_in_smiles("C/C=C/C")
    cis = groups_in_smiles(r"C/C=C\C")
    unknown = groups_in_smiles("CC=CC")
    assert trans is not None
    assert cis is not None
    assert unknown is not None
    assert trans.has("trans_disubstituted_alkene")
    assert not trans.has("cis_disubstituted_alkene")
    assert cis.has("cis_disubstituted_alkene")
    assert not cis.has("trans_disubstituted_alkene")
    assert not unknown.is_known("cis_disubstituted_alkene")
    assert not unknown.is_known("trans_disubstituted_alkene")
    assert unknown.is_known("alkene")
    ring = groups_in_smiles("C1=CCCCC1")
    assert ring is not None
    assert ring.has("cis_disubstituted_alkene")


def test_unparsable_structure_gives_none() -> None:
    assert groups_in_smiles("") is None
    assert groups_in_smiles("not a smiles") is None
