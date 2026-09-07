"""
StructureRenderer — Renderování chemické struktury z SMILES nebo MolBlock.

Zodpovědnost:
- SVG rendering via RDKit (vector, scalable, transparent background)
- PNG rasterisation via Qt QSvgRenderer (for PDF export at any DPI)
- Graceful fallback pokud RDKit není nainstalován

The canvas always takes the shape of the molecule rather than the other way
round, so a wide structure — a lipid, a salt drawn with its counter-ions
alongside — fills whatever box it is placed in instead of sitting in a thin
strip inside a square.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, cast

# Pixels per drawing unit used when measuring how much room a molecule wants.
# The value is arbitrary; it only has to be the same for every measurement.
_PROBE_SCALE = 20.0
# How far the canvas is allowed to follow an extreme shape. Past this a
# straight alkyl chain would render as a hairline, so it gets letterboxed.
_MAX_ASPECT = 5.0
# Longest side, in pixels, of the raster :func:`render_structure` produces.
_DEFAULT_MAX_PX = 1600
# Canvas the line weights and font sizes below were chosen against. Every
# canvas is scaled from it, so the pixel count is only a resolution knob and
# never changes how heavy the drawing looks.
_REFERENCE_CANVAS = 380.0
_REF_MIN_FONT = 6.0
_REF_MAX_FONT = 40.0
# Bond line width as a fraction of the bond length, which is what keeps a
# 60-atom salt from turning into a blob of ink and a two-atom molecule from
# being drawn with hairlines. RDKit lays a single bond out 1.5 units long.
_BOND_WIDTH_RATIO = 0.028
_BOND_UNITS = 1.5

_SVG_SIZE_RE = re.compile(
    r"<svg[^>]*?width=['\"]([\d.]+)(?:px)?['\"][^>]*?height=['\"]([\d.]+)(?:px)?['\"]",
    re.DOTALL,
)


@dataclass(frozen=True)
class StructureImage:
    """A rendered molecule together with the size its drawing asks for.

    ``width_units``/``height_units`` are the drawing's extent in RDKit 2D
    coordinates (a single bond is 1.5 units), atom labels included. They let a
    caller decide how much space to give the structure on a page: a small
    molecule needs little, a 60-atom salt needs the full width.
    """

    png: bytes
    width_px: int
    height_px: int
    width_units: float
    height_units: float

    @property
    def aspect(self) -> float:
        """Height divided by width of the rendered image."""
        return (self.height_px / self.width_px) if self.width_px else 1.0


def svg_size(svg_str: str) -> tuple[float, float] | None:
    """Read the declared pixel size off an SVG root element."""
    match = _SVG_SIZE_RE.search(svg_str)
    if match is None:
        return None
    try:
        return (float(match.group(1)), float(match.group(2)))
    except ValueError:
        return None


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
        size: Maximum canvas (width, height) in pixels. The canvas returned is
              the largest box with the molecule's own aspect ratio that fits
              inside it, so the drawing fills the canvas edge to edge.

    Returns:
        SVG string, or None if RDKit unavailable or molecule invalid.
    """
    mol = _load_mol(smiles=smiles, mol_block=mol_block)
    if mol is None:
        return None
    natural = _natural_size(mol)
    return _draw_svg(mol, _canvas_size(natural, size), natural[0])


def render_structure(
    smiles: str = "",
    mol_block: str = "",
    *,
    max_px: int = _DEFAULT_MAX_PX,
) -> StructureImage | None:
    """Render a molecule to a PNG shaped like the molecule itself.

    The raster has no margin to speak of and its longest side is ``max_px``,
    so whoever places it can scale it to any size on the page without the
    drawing shrinking into a corner.

    Returns None if RDKit is unavailable, the molecule is invalid, or Qt
    cannot rasterise the SVG.
    """
    mol = _load_mol(smiles=smiles, mol_block=mol_block)
    if mol is None:
        return None

    natural_w, natural_h = _natural_size(mol)
    width, height = _canvas_size((natural_w, natural_h), (max_px, max_px))
    svg = _draw_svg(mol, (width, height), natural_w)
    if not svg:
        return None
    png = svg_to_png_bytes(svg, width, height)
    if not png:
        return None
    return StructureImage(
        png=png,
        width_px=width,
        height_px=height,
        width_units=natural_w,
        height_units=natural_h,
    )


def svg_to_png_bytes(svg_str: str, width: int, height: int) -> bytes | None:
    """Rasterise an SVG string to a transparent-background PNG via Qt.

    Uses QSvgRenderer (PySide6.QtSvg) which is available whenever Qt is
    initialised. The drawing keeps its aspect ratio inside the requested box,
    so asking for a square never squashes a wide molecule.

    Args:
        svg_str: SVG markup as a string.
        width: Output PNG width in pixels.
        height: Output PNG height in pixels.

    Returns:
        PNG bytes, or None if Qt is not available or rendering fails.
    """
    try:
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF
        from PySide6.QtGui import QImage, QPainter
        from PySide6.QtSvg import QSvgRenderer

        renderer = QSvgRenderer(QByteArray(svg_str.encode()))
        if not renderer.isValid():
            return None

        img = QImage(width, height, QImage.Format.Format_ARGB32)
        img.fill(0)  # fully transparent
        painter = QPainter(img)
        renderer.render(painter, _fit_rect(QRectF, renderer.defaultSize(), width, height))
        painter.end()

        buf = QBuffer()
        buf.open(QIODevice.OpenMode.WriteOnly)
        img.save(buf, "PNG")
        buf.close()
        return bytes(buf.data())
    except Exception:  # noqa: BLE001
        return None


def _fit_rect(rect_cls: Any, default_size: Any, width: int, height: int) -> Any:
    """Centred target rectangle that keeps the SVG's aspect ratio."""
    src_w = float(default_size.width())
    src_h = float(default_size.height())
    if src_w <= 0 or src_h <= 0:
        return rect_cls(0.0, 0.0, float(width), float(height))
    scale = min(width / src_w, height / src_h)
    draw_w = src_w * scale
    draw_h = src_h * scale
    return rect_cls((width - draw_w) / 2.0, (height - draw_h) / 2.0, draw_w, draw_h)


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
        rendered = render_structure(smiles=smiles, max_px=max(size) * 2)
        return rendered.png if rendered else None

    try:
        from rdkit.Chem import Draw
    except ImportError:
        return None

    mol = _mol_from_smiles_relaxed(smiles)
    if mol is None:
        return None

    from io import BytesIO

    img = Draw.MolToImage(mol, size=size)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Drawing internals
# ---------------------------------------------------------------------------


def _apply_draw_options(opts: Any) -> None:
    """The one place the look of every rendered structure is decided."""
    opts.clearBackground = False  # transparent background
    opts.bondLineWidth = 2.0
    opts.padding = 0.05
    # Draw the wedge and hash bonds exactly where the analyst drew them.
    # Without this RDKit re-derives wedging from the stereo centres on every
    # render and happily moves a hash onto a neighbouring bond, so the
    # structure that comes back from the editor is not the one that went in.
    if hasattr(opts, "useMolBlockWedging"):
        opts.useMolBlockWedging = True


def _scale_draw_options(opts: Any, canvas: tuple[int, int], natural_width: float) -> None:
    """Match line weight and label size to the canvas and to the molecule.

    Fonts follow the canvas, so raising the pixel count only buys resolution.
    The bond line follows the bond length instead: at a fixed pixel width a
    molecule with sixty bonds across the page is drawn in strokes as thick as
    the bonds are long.
    """
    longest = float(max(canvas))
    resolution = longest / _REFERENCE_CANVAS
    opts.minFontSize = max(int(round(_REF_MIN_FONT * resolution)), 1)
    opts.maxFontSize = max(int(round(_REF_MAX_FONT * resolution)), 2)

    bonds_across = max(natural_width, _BOND_UNITS) / _BOND_UNITS
    opts.bondLineWidth = max(longest / bonds_across * _BOND_WIDTH_RATIO, 1.0)


def _draw_svg(mol: Any, canvas: tuple[int, int], natural_width: float) -> str | None:
    """Draw ``mol`` into a canvas of exactly ``canvas`` pixels."""
    try:
        from rdkit.Chem.Draw import rdMolDraw2D

        drawer = rdMolDraw2D.MolDraw2DSVG(canvas[0], canvas[1])
        opts = drawer.drawOptions()
        _apply_draw_options(opts)
        _scale_draw_options(opts, canvas, natural_width)
        drawer.DrawMolecule(mol)
        drawer.FinishDrawing()
        return cast(str, drawer.GetDrawingText())
    except Exception:  # noqa: BLE001
        return None


def _natural_size(mol: Any) -> tuple[float, float]:
    """Size in 2D coordinate units the drawing wants, atom labels included.

    Uses RDKit's auto-sizing canvas, which is the only thing that knows how
    much room the atom labels take — the conformer's bounding box alone puts a
    trailing ``H2N`` or a stray ``HCl`` outside the drawing.
    """
    fallback = _conformer_size(mol)
    try:
        from rdkit.Chem.Draw import rdMolDraw2D

        drawer = rdMolDraw2D.MolDraw2DSVG(-1, -1)
        opts = drawer.drawOptions()
        _apply_draw_options(opts)
        opts.scalingFactor = _PROBE_SCALE
        drawer.DrawMolecule(mol)
        drawer.FinishDrawing()
        measured = svg_size(drawer.GetDrawingText())
    except Exception:  # noqa: BLE001
        return fallback
    if measured is None or measured[0] <= 0 or measured[1] <= 0:
        return fallback
    return (measured[0] / _PROBE_SCALE, measured[1] / _PROBE_SCALE)


def _conformer_size(mol: Any) -> tuple[float, float]:
    """Bounding box of the atom coordinates — the fallback measurement."""
    try:
        conf = mol.GetConformer()
    except Exception:  # noqa: BLE001
        return (1.0, 1.0)
    xs = []
    ys = []
    for idx in range(mol.GetNumAtoms()):
        pos = conf.GetAtomPosition(idx)
        xs.append(pos.x)
        ys.append(pos.y)
    if not xs:
        return (1.0, 1.0)
    return (max(max(xs) - min(xs), 1.0), max(max(ys) - min(ys), 1.0))


def _canvas_size(natural: tuple[float, float], box: tuple[int, int]) -> tuple[int, int]:
    """Largest canvas with the molecule's aspect ratio that fits in ``box``."""
    natural_w, natural_h = natural
    aspect = (natural_h / natural_w) if natural_w > 0 else 1.0
    aspect = min(max(aspect, 1.0 / _MAX_ASPECT), _MAX_ASPECT)

    max_w, max_h = box
    width = float(max_w)
    height = width * aspect
    if height > max_h:
        height = float(max_h)
        width = height / aspect
    return (max(int(round(width)), 1), max(int(round(height)), 1))


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
    except ImportError:
        return None
    mol = _mol_from_smiles_relaxed(smiles)
    if mol is None:
        return None
    try:
        return cast(str, Chem.MolToMolBlock(mol))
    except Exception:  # noqa: BLE001
        try:
            return cast(str, Chem.MolToMolBlock(mol, kekulize=False))
        except Exception:  # noqa: BLE001
            return None


def _relaxed_sanitize(mol) -> bool:
    """Partially sanitize a molecule, skipping strict valence checks.

    JSME lets users draw atoms with unusual valences (typed via the "X"
    element picker); full RDKit sanitization rejects those and the structure
    would silently vanish from the app. Returns True when the molecule is
    usable for drawing.
    """
    try:
        from rdkit import Chem

        mol.UpdatePropertyCache(strict=False)
        Chem.SanitizeMol(
            mol,
            Chem.SanitizeFlags.SANITIZE_FINDRADICALS
            | Chem.SanitizeFlags.SANITIZE_SETAROMATICITY
            | Chem.SanitizeFlags.SANITIZE_SETCONJUGATION
            | Chem.SanitizeFlags.SANITIZE_SETHYBRIDIZATION
            | Chem.SanitizeFlags.SANITIZE_SYMMRINGS,
            catchErrors=True,
        )
    except Exception:  # noqa: BLE001
        return False
    return True


def _mol_from_smiles_relaxed(smiles: str) -> Any | None:
    """Parse SMILES with a relaxed-sanitization fallback for unusual valences."""
    from rdkit import Chem
    from rdkit.Chem import AllChem

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        mol = Chem.MolFromSmiles(smiles, sanitize=False)
        if mol is None or not _relaxed_sanitize(mol):
            return None
    if not mol.GetNumConformers():
        AllChem.Compute2DCoords(mol)
    return mol


def _is_real_element(symbol: str) -> bool:
    """Return True when ``symbol`` is a real periodic-table element."""
    try:
        from rdkit.Chem import GetPeriodicTable

        return bool(GetPeriodicTable().GetAtomicNumber(symbol) > 0)
    except Exception:  # noqa: BLE001
        return False


def _replace_pseudo_atoms(mol_block: str) -> tuple[str, dict[int, str]]:
    """Replace non-element atom symbols in a V2000 mol block with dummy atoms.

    JSME lets the user type an arbitrary label on an atom via the "X" button
    (e.g. ``Boc``, ``Ph``, ``PG``). Such labels land in the atom block as a
    non-element symbol, which RDKit refuses to parse, so the structure would
    vanish. Each unknown symbol is swapped for a ``*`` dummy atom and its
    original text is returned as ``{atom_index: label}`` so it can be shown.
    """
    lines = mol_block.splitlines()
    try:
        counts_idx = next(i for i, line in enumerate(lines) if line.rstrip().endswith("V2000"))
    except StopIteration:
        return mol_block, {}

    try:
        n_atoms = int(lines[counts_idx][0:3])
    except ValueError:
        return mol_block, {}

    labels: dict[int, str] = {}
    reserved = {"*", "R", "R#", "A", "Q", "L", "RX"}
    for atom in range(n_atoms):
        line_idx = counts_idx + 1 + atom
        if line_idx >= len(lines) or len(lines[line_idx]) < 34:
            continue
        line = lines[line_idx]
        symbol = line[31:34].strip()
        if symbol and symbol not in reserved and not _is_real_element(symbol):
            labels[atom] = symbol
            lines[line_idx] = line[:31] + "*  " + line[34:]
    return "\n".join(lines), labels


def _apply_atom_labels(mol: Any, labels: dict[int, str]) -> None:
    """Show custom labels on the molecule: recorded pseudo-atoms + MOL aliases."""
    for idx, text in labels.items():
        if 0 <= idx < mol.GetNumAtoms():
            mol.GetAtomWithIdx(idx).SetProp("atomLabel", text)
    # MOL "A" alias lines are parsed by RDKit into molFileAlias; surface them
    # as drawable atom labels too.
    for atom in mol.GetAtoms():
        if atom.HasProp("molFileAlias") and not atom.HasProp("atomLabel"):
            alias = atom.GetProp("molFileAlias").strip()
            if alias:
                atom.SetProp("atomLabel", alias)


def _load_mol(smiles: str = "", mol_block: str = "") -> Any | None:
    """Load a molecule from mol_block (preferred) or SMILES.

    Returns an RDKit Mol object, or None if loading fails or RDKit is missing.
    """
    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem  # noqa: F401
    except ImportError:
        return None

    mol = None

    if mol_block and mol_block.strip():
        try:
            mol = Chem.MolFromMolBlock(mol_block, removeHs=False, sanitize=True)
        except Exception:  # noqa: BLE001
            mol = None
        if mol is None:
            # Relaxed fallback — keep unusual-valence atoms drawable.
            try:
                mol = Chem.MolFromMolBlock(mol_block, removeHs=False, sanitize=False)
                if mol is not None and not _relaxed_sanitize(mol):
                    mol = None
            except Exception:  # noqa: BLE001
                mol = None
        if mol is None:
            # Custom text labels (e.g. "Boc" typed via JSME's "X") appear as
            # non-element atom symbols that RDKit cannot parse. Swap them for
            # dummy atoms and re-attach the text as a drawable label.
            cleaned, labels = _replace_pseudo_atoms(mol_block)
            if labels:
                try:
                    mol = Chem.MolFromMolBlock(cleaned, removeHs=False, sanitize=False)
                    if mol is not None and _relaxed_sanitize(mol):
                        _apply_atom_labels(mol, labels)
                    else:
                        mol = None
                except Exception:  # noqa: BLE001
                    mol = None
        if mol is not None:
            _apply_atom_labels(mol, {})  # promote any A-line aliases to labels

    if mol is None and smiles and smiles.strip():
        mol = _mol_from_smiles_relaxed(smiles)

    return mol
