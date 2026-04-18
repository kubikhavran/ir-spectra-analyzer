"""
StructureRenderer — Renderování chemické struktury z SMILES nebo MolBlock.

Zodpovědnost:
- SVG rendering via RDKit (vector, scalable, transparent background)
- PNG rasterisation via Qt QSvgRenderer (for PDF export at any DPI)
- Graceful fallback pokud RDKit není nainstalován
"""

from __future__ import annotations


def render_to_svg(
    smiles: str = "",
    mol_block: str = "",
    size: tuple[int, int] = (400, 300),
) -> str | None:
    """Render a molecule to SVG using RDKit.

    Prefers mol_block (preserves user-drawn 2D coordinates) over generating
    coords from SMILES. The SVG has a transparent background.

    Args:
        smiles: SMILES string (fallback if mol_block is empty/invalid).
        mol_block: MOL V2000 string with 2D coordinates.
        size: Canvas (width, height) in pixels. SVG is vector so this sets
              aspect ratio and proportions only, not final display size.

    Returns:
        SVG string, or None if RDKit unavailable or molecule invalid.
    """
    mol = _load_mol(smiles=smiles, mol_block=mol_block)
    if mol is None:
        return None

    try:
        from rdkit.Chem.Draw import rdMolDraw2D

        w, h = size
        drawer = rdMolDraw2D.MolDraw2DSVG(w, h)
        opts = drawer.drawOptions()
        opts.clearBackground = False  # transparent background
        opts.bondLineWidth = 2.0
        opts.padding = 0.05
        drawer.DrawMolecule(mol)
        drawer.FinishDrawing()
        return drawer.GetDrawingText()
    except Exception:  # noqa: BLE001
        return None


def svg_to_png_bytes(svg_str: str, width: int, height: int) -> bytes | None:
    """Rasterise an SVG string to a transparent-background PNG via Qt.

    Uses QSvgRenderer (PySide6.QtSvg) which is available whenever Qt is
    initialised. Returns None if Qt is not available or rendering fails.

    Args:
        svg_str: SVG markup as a string.
        width: Output PNG width in pixels.
        height: Output PNG height in pixels.

    Returns:
        PNG bytes, or None on failure.
    """
    try:
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice
        from PySide6.QtGui import QImage, QPainter
        from PySide6.QtSvg import QSvgRenderer

        renderer = QSvgRenderer(QByteArray(svg_str.encode()))
        if not renderer.isValid():
            return None

        img = QImage(width, height, QImage.Format.Format_ARGB32)
        img.fill(0)  # fully transparent
        painter = QPainter(img)
        renderer.render(painter)
        painter.end()

        buf = QBuffer()
        buf.open(QIODevice.OpenMode.WriteOnly)
        img.save(buf, "PNG")
        buf.close()
        return bytes(buf.data())
    except Exception:  # noqa: BLE001
        return None


def render_smiles_to_png(
    smiles: str,
    size: tuple[int, int] = (300, 300),
    *,
    transparent: bool = False,
) -> bytes | None:
    """Render SMILES to PNG (backward-compatible convenience wrapper).

    For UI display (transparent=False): uses RDKit MolToImage with white
    background. Exact pixel dimensions are preserved.
    For PDF export (transparent=True): renders to SVG then rasterises via Qt.

    Args:
        smiles: SMILES string.
        size: (width, height) in pixels.
        transparent: If True, output has transparent background.

    Returns:
        PNG bytes, or None on failure.
    """
    if not smiles or not smiles.strip():
        return None

    if transparent:
        svg = render_to_svg(smiles=smiles, size=(size[0] * 2, size[1] * 2))
        if svg:
            return svg_to_png_bytes(svg, size[0] * 2, size[1] * 2)
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


def smiles_to_mol_block(smiles: str) -> str | None:
    """Convert a SMILES string to a V2000 MOL block with 2D coordinates.

    Used to hand structures to JSME, whose `readMolecule(SMILES)` entry point
    is broken in the packaged build: it silently drops the molecule (even for
    trivial inputs like "CCO") and never renders. `readMolFile(MOL)` works
    correctly — including for custom elements like Na or Fe — so we go through
    MOL instead.

    Returns None if RDKit is unavailable or the SMILES cannot be parsed.
    """
    if not smiles or not smiles.strip():
        return None
    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem
    except ImportError:
        return None
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None
    if not mol.GetNumConformers():
        AllChem.Compute2DCoords(mol)
    try:
        return Chem.MolToMolBlock(mol)
    except Exception:  # noqa: BLE001
        return None


def _load_mol(smiles: str = "", mol_block: str = ""):  # type: ignore[return]
    """Load a molecule from mol_block (preferred) or SMILES.

    Returns an RDKit Mol object, or None if loading fails or RDKit is missing.
    """
    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem
    except ImportError:
        return None

    mol = None

    if mol_block and mol_block.strip():
        try:
            mol = Chem.MolFromMolBlock(mol_block, removeHs=False, sanitize=True)
        except Exception:  # noqa: BLE001
            mol = None

    if mol is None and smiles and smiles.strip():
        mol = Chem.MolFromSmiles(smiles)
        if mol is not None and not mol.GetNumConformers():
            AllChem.Compute2DCoords(mol)

    return mol
