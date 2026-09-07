"""Tests for chemistry.structure_renderer.render_smiles_to_png."""

from __future__ import annotations

import pytest

pytest.importorskip("rdkit")

from chemistry.structure_renderer import render_smiles_to_png  # noqa: E402


def test_valid_smiles_returns_png_bytes():
    result = render_smiles_to_png("C")
    assert result is not None
    assert isinstance(result, bytes)
    assert result[:4] == b"\x89PNG"


def test_empty_string_returns_none():
    assert render_smiles_to_png("") is None


def test_whitespace_only_returns_none():
    assert render_smiles_to_png("   ") is None


def test_invalid_smiles_returns_none():
    assert render_smiles_to_png("not_a_smiles_xyz") is None


def test_size_parameter_respected():
    import struct

    size = (150, 150)
    result = render_smiles_to_png("CCO", size=size)
    assert result is not None
    # PNG IHDR chunk: bytes 16-24 contain width (4 bytes) and height (4 bytes)
    width = struct.unpack(">I", result[16:20])[0]
    height = struct.unpack(">I", result[20:24])[0]
    assert (width, height) == size


def test_render_to_svg_valid_smiles():
    from chemistry.structure_renderer import render_to_svg

    result = render_to_svg(smiles="CCO")
    assert result is not None
    assert "<svg" in result


def test_render_to_svg_empty_returns_none():
    from chemistry.structure_renderer import render_to_svg

    assert render_to_svg(smiles="") is None


def test_render_to_svg_invalid_smiles_returns_none():
    from chemistry.structure_renderer import render_to_svg

    assert render_to_svg(smiles="not_a_smiles_xyz") is None


def test_render_to_svg_with_mol_block():
    """MolBlock path should also produce SVG."""
    from rdkit.Chem import AllChem, MolToMolBlock

    from chemistry.structure_renderer import _load_mol, render_to_svg

    mol = _load_mol(smiles="c1ccccc1")
    AllChem.Compute2DCoords(mol)
    mol_block = MolToMolBlock(mol)
    result = render_to_svg(mol_block=mol_block)
    assert result is not None
    assert "<svg" in result


# ── Canvas follows the molecule ──────────────────────────────────────────────


def _wide_salt() -> str:
    """A lipid drawn with its six HCl counter-ions — much wider than it is tall."""
    return (
        "CCCCCCCCCCCCCC(=O)N(CCN(CCCN)CCCN)COCCCCOCCN(C(=O)CCCCCCCCCCCC)"
        "CCN(CCCN)CCCN.Cl.Cl.Cl.Cl.Cl.Cl"
    )


def test_render_structure_canvas_follows_a_wide_molecule(qapp):
    """A wide salt must not be drawn into a square, which is what shrank it."""
    from chemistry.structure_renderer import render_structure

    rendered = render_structure(smiles=_wide_salt())
    assert rendered is not None
    assert rendered.width_px > rendered.height_px
    assert rendered.aspect < 0.9


def test_render_structure_fills_its_canvas(qapp):
    """The drawing reaches the edges: no wasted pixels to scale down later."""
    from io import BytesIO

    from PIL import Image

    from chemistry.structure_renderer import render_structure

    rendered = render_structure(smiles=_wide_salt())
    assert rendered is not None
    with Image.open(BytesIO(rendered.png)) as image:
        bbox = image.convert("RGBA").getchannel("A").getbbox()
    assert bbox is not None
    ink_w = bbox[2] - bbox[0]
    ink_h = bbox[3] - bbox[1]
    assert ink_w / rendered.width_px > 0.9
    assert ink_h / rendered.height_px > 0.9


def test_render_structure_reports_the_room_a_molecule_wants(qapp):
    """The measured extent is what lets the report give a big salt more page."""
    from chemistry.structure_renderer import render_structure

    salt = render_structure(smiles=_wide_salt())
    small = render_structure(smiles="CCO")
    assert salt is not None
    assert small is not None
    assert salt.width_units > 5 * small.width_units


def test_render_to_svg_canvas_fits_inside_the_requested_box():
    from chemistry.structure_renderer import render_to_svg, svg_size

    svg = render_to_svg(smiles=_wide_salt(), size=(400, 300))
    assert svg is not None
    size = svg_size(svg)
    assert size is not None
    assert size[0] <= 400
    assert size[1] <= 300
    assert size[1] < size[0]  # the canvas took the molecule's shape


# ── Wedge and hash bonds stay on the bond they were drawn on ─────────────────

# Serine-like fragment with the hash deliberately on the C–N bond (atoms 2-3 in
# MOL numbering). Left to itself RDKit re-derives the wedging from the stereo
# centre and moves the hash onto the C–CH3 bond instead.
_MB_HASHED_CN = """
  test

  6  5  0  0  1  0            999 V2000
   -1.0000    0.0000    0.0000 C   0  0
    0.0000    0.5000    0.0000 C   0  0
    0.0000    1.5000    0.0000 N   0  0
    1.0000    0.0000    0.0000 C   0  0
    1.0000   -1.0000    0.0000 O   0  0
    2.0000    0.5000    0.0000 O   0  0
  2  1  1  0
  2  3  1  6
  2  4  1  0
  4  5  2  0
  4  6  1  0
M  END
"""


def _hashed_bond_atoms(svg: str) -> set[int]:
    """Atom indices of the bond drawn with the most segments — the hashed one."""
    import re
    from collections import Counter

    classes = re.findall(r"class='bond-(\d+) atom-(\d+) atom-(\d+)", svg)
    counts = Counter(bond for bond, _, _ in classes)
    busiest = counts.most_common(1)[0][0]
    return next({int(begin), int(end)} for bond, begin, end in classes if bond == busiest)


def test_hash_bond_stays_on_the_bond_it_was_drawn_on():
    """Re-rendering a structure must not move a wedge onto a different bond."""
    from chemistry.structure_renderer import render_to_svg

    svg = render_to_svg(mol_block=_MB_HASHED_CN)
    assert svg is not None
    # 0-based: the C–N bond the mol block hashes, not the C–CH3 bond next to it.
    assert _hashed_bond_atoms(svg) == {1, 2}
