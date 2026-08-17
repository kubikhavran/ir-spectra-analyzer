"""Measure the scorer against analysed projects whose structures are known.

Synthetic patterns cannot decide whether this scorer is any good: a signature
spectrum is a few bands on a flat baseline, so anything that finds them looks
convincing, and a rework that passed every synthetic check turned out to be
clearly worse on real data. These tests read the structures the analyst drew,
derive the groups actually present with RDKit, and hold the scorer to what it
manages on them.

The projects carry unpublished structures and customer names, so they live
outside the repository (tests/fixtures/irproj test/, git-ignored). The tests skip
when the folder is not there.
"""

import json
from pathlib import Path

import numpy as np
import pytest

from core.spectrum import SpectralUnit, Spectrum
from processing.functional_group_scoring import score_functional_groups

PROJECT_DIR = Path(__file__).resolve().parent / "fixtures" / "irproj test"

pytestmark = pytest.mark.skipif(
    not PROJECT_DIR.is_dir(), reason="analysed reference projects are not present"
)

_SHORTHAND = {
    "[OAc]": "OC(C)=O",
    "[OEt]": "OCC",
    "[OMe]": "OC",
    "[OBn]": "OCc1ccccc1",
    "[TIPS]": "[Si](C(C)C)(C(C)C)C(C)C",
    "[TBS]": "[Si](C)(C)C(C)(C)C",
}

# Groups whose presence a structure can settle. Written so a pattern does not
# also fire on its neighbours.
_SMARTS = {
    "ester": "[CX3](=O)[OX2H0][#6]",
    "carboxylic_acid": "[CX3](=O)[OX2H1]",
    "ketone": "[#6][CX3](=O)[#6]",
    "amide": "[NX3][CX3](=[OX1])",
    "alcohol": "[#6][OX2H]",
    "phenol": "c[OX2H]",
    "aliphatic_ether": "[CX4][OX2H0][CX4]",
    "aryl_ether": "c[OX2H0][#6]",
    "epoxide": "C1OC1",
    "nitrile": "[NX1]#[CX2]",
    "nitro": "[NX3](=O)=O",
    "aromatic_ring": "c1ccccc1",
    "alkene": "[CX3]=[CX3]",
    "sulfone": "[SX4](=O)(=O)",
    "siloxane_silicone": "[Si][OX2][Si]",
}


def _mol(smiles):
    from rdkit import Chem, RDLogger

    RDLogger.DisableLog("rdApp.*")
    expanded = smiles
    for token, full in _SHORTHAND.items():
        expanded = expanded.replace(token, full)
    return Chem.MolFromSmiles(expanded)


def _groups_present(smiles):
    from rdkit import Chem

    mol = _mol(smiles)
    if mol is None:
        return set()
    present = set()
    for group_id, smarts in _SMARTS.items():
        pattern = Chem.MolFromSmarts(smarts)
        if pattern is not None and mol.HasSubstructMatch(pattern):
            present.add(group_id)
    return present


def _spectrum(payload):
    if not payload:
        return None
    wavenumbers = np.asarray(payload["wavenumbers"], dtype=float)
    intensities = np.asarray(
        [np.nan if value is None else value for value in payload["intensities"]], dtype=float
    )
    try:
        y_unit = SpectralUnit(payload.get("y_unit") or "Absorbance")
    except ValueError:
        y_unit = SpectralUnit.ABSORBANCE
    return Spectrum(wavenumbers=wavenumbers, intensities=intensities, y_unit=y_unit)


def _load():
    samples = []
    for path in sorted(PROJECT_DIR.glob("*.irproj")):
        payload = json.loads(path.read_text(encoding="utf-8"))["project"]
        raw = _spectrum(payload.get("spectrum"))
        if raw is None:
            continue
        samples.append(
            {
                "name": path.stem,
                "truth": _groups_present((payload.get("smiles") or "").strip()),
                "raw": raw,
                "corrected": _spectrum(payload.get("corrected_spectrum")),
            }
        )
    return samples


def _measure(top_k=10):
    known = set(_SMARTS)
    found = expected = correct = shown = 0
    for sample in _load():
        analysis = score_functional_groups(sample["raw"], sample["corrected"])
        order = [r.group_id for r in analysis.results if r.group_id in known]
        for group_id in sample["truth"] & set(order):
            expected += 1
            if order.index(group_id) + 1 <= top_k:
                found += 1
        for group_id in order[:top_k]:
            shown += 1
            if group_id in sample["truth"]:
                correct += 1
    return found / max(expected, 1), correct / max(shown, 1)


def test_present_groups_are_visible_near_the_top():
    """Measured 0.75 on v0.26.0 and 0.93 after this rework; the floor sits under."""
    recall, _precision = _measure()

    assert recall >= 0.85, f"recall fell to {recall:.2f}"


def test_what_is_reported_is_mostly_really_there():
    """Measured 0.22 on v0.26.0 and 0.27 after this rework.

    Still the weaker half: two thirds of what the panel lists is not in the
    molecule, so the ranking is a shortlist to read, not an answer.
    """
    _recall, precision = _measure()

    assert precision >= 0.25, f"precision fell to {precision:.2f}"


def test_an_ether_beside_an_ester_is_not_discarded():
    """The defect that started this: exclusions vetoing a co-occurring group."""
    samples = [s for s in _load() if {"aliphatic_ether", "ester"} <= s["truth"]]
    if not samples:
        pytest.skip("no sample carries both an ether and an ester")

    reported = 0
    for sample in samples:
        analysis = score_functional_groups(sample["raw"], sample["corrected"])
        scores = {r.group_id: r.score for r in analysis.results}
        if scores.get("aliphatic_ether", 0.0) >= 25.0:
            reported += 1

    assert reported >= len(samples) * 0.6, (
        f"the ether was written off on {len(samples) - reported} of {len(samples)} samples"
    )
