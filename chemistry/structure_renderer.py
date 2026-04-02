"""
StructureRenderer — Renderování chemické struktury z SMILES.

Zodpovědnost:
- Generování 2D obrázku molekuly z SMILES pomocí RDKit
- Graceful fallback pokud RDKit není nainstalován
"""

from __future__ import annotations


def render_smiles_to_png(smiles: str, size: tuple[int, int] = (300, 300)) -> bytes | None:
    """Render a SMILES string to a PNG image using RDKit.

    Args:
        smiles: SMILES string representing the molecule.
        size: Desired image dimensions as (width, height) in pixels.

    Returns:
        PNG image bytes if rendering succeeds, or None if RDKit is not available,
        the SMILES string is empty/whitespace, or the SMILES is chemically invalid.
    """
    if not smiles or not smiles.strip():
        return None

    try:
        from rdkit import Chem
        from rdkit.Chem import Draw
    except ImportError:
        return None

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None

    from io import BytesIO

    img = Draw.MolToImage(mol, size=size)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
