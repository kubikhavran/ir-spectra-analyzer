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
