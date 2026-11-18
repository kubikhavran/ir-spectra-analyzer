"""Layout quality of the native structure editor and of exported images.

Builds structures the way a user would (groups, rings, labels, salts, pasted
parts, sugars) and checks that nothing is drawn on top of anything else:
atoms, bonds, atom labels, H counts and charges.  Also checks that exported
images have no empty border and are not distorted.
"""

from __future__ import annotations

import itertools
import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("rdkit")

from PySide6.QtCore import QPointF  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402

from chemistry.mol_editor_model import (  # noqa: E402
    BOND_LENGTH,
    FUNCTIONAL_GROUPS,
    RING_TEMPLATES,
    MolEditorModel,
)
from chemistry.mol_fragments import SALTS_AND_SOLVENTS, fragment_from_smiles  # noqa: E402

L = BOND_LENGTH


def _segments_cross(p1, p2, p3, p4) -> bool:
    def ccw(a, b, c):
        return (c[1] - a[1]) * (b[0] - a[0]) - (b[1] - a[1]) * (c[0] - a[0])

    d1, d2 = ccw(p3, p4, p1), ccw(p3, p4, p2)
    d3, d4 = ccw(p1, p2, p3), ccw(p1, p2, p4)
    return bool(d1 * d2 < -1e-9 and d3 * d4 < -1e-9)


def _point_segment(p, a, b) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    t = (
        0.0
        if not length2
        else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2))
    )
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def geometry_problems(model: MolEditorModel) -> list[str]:
    """Atoms too close, bonds crossing, atoms sitting on bonds."""
    problems = []
    pos = [model.atom_position(i) for i in range(model.atom_count)]
    for i, j in itertools.combinations(range(model.atom_count), 2):
        if math.dist(pos[i], pos[j]) < 0.6 * L:
            problems.append(f"atoms {i} and {j} overlap")
    bonds = [model.bond_atoms(b) for b in range(model.bond_count)]
    for (a, b), (c, d) in itertools.combinations(bonds, 2):
        if len({a, b, c, d}) == 4 and _segments_cross(pos[a], pos[b], pos[c], pos[d]):
            problems.append(f"bonds {a}-{b} and {c}-{d} cross")
    for a, b in bonds:
        for i in range(model.atom_count):
            if i not in (a, b) and _point_segment(pos[i], pos[a], pos[b]) < 0.3 * L:
                problems.append(f"atom {i} lies on bond {a}-{b}")
    return problems


def _scenarios() -> dict[str, MolEditorModel]:
    scenarios: dict[str, MolEditorModel] = {}
    model = MolEditorModel.from_smiles("CCCCCC")
    for i in range(6):
        model.attach_functional_group(i, "-OH")
    scenarios["hexane with OH everywhere"] = model
    model = MolEditorModel()
    centre = model.add_free_atom(0.0, 0.0)
    for _ in range(4):
        model.sprout_atom(centre)
    scenarios["four sprouts"] = model
    for group in FUNCTIONAL_GROUPS:
        model = MolEditorModel.from_smiles("c1ccccc1")
        for atom in (0, 1, 2):
            model.attach_functional_group(atom, group)
        scenarios[f"benzene 1,2,3-tri {group}"] = model
        model = MolEditorModel.from_smiles("CC(C)C")
        model.attach_functional_group(1, group)
        scenarios[f"isobutane {group}"] = model
    for ring in RING_TEMPLATES:
        model = MolEditorModel.from_smiles("c1ccccc1")
        model.add_ring_template(ring, target_bond_idx=0)
        model.add_ring_template(ring, target_bond_idx=2)
        scenarios[f"benzene fused twice {ring}"] = model
        model = MolEditorModel.from_smiles("c1ccccc1")
        model.add_ring_template(ring, target_atom_idx=0)
        model.add_ring_template(ring, target_atom_idx=1)
        scenarios[f"benzene ortho {ring}"] = model
    for label in ("OMe", "CO2Et", "NHBoc", "tBu", "Ts", "CH2CH2OH", "N(CH3)2", "OTBS", "Fmoc"):
        model = MolEditorModel.from_smiles("CC(C)(C)C")
        assert model.apply_label(0, label)
        scenarios[f"label {label}"] = model
    model = MolEditorModel.from_smiles("CCCCN")
    for _label, smiles in SALTS_AND_SOLVENTS[:8]:
        fragment = fragment_from_smiles(smiles)
        assert fragment is not None
        fragment.attach = None
        model.insert_fragment(fragment)
    scenarios["amine with salts"] = model
    source = MolEditorModel.from_smiles("CCCC(=O)O")
    part = source.extract_fragment([3, 4, 5])
    model = MolEditorModel.from_smiles("CC(C)(C)CC")
    model.insert_fragment(part, target_atom_idx=5)
    model.insert_fragment(part, target_atom_idx=0)
    scenarios["pasted COOH twice"] = model
    for smiles in (
        "C[NH3+].[Cl-].[Na+].[O-]C(=O)C",
        "OC[C@H]1O[C@@H](O)[C@H](O)[C@@H](O)[C@@H]1O",
        "C[N+](C)(C)C",
        "CC(C)(C)OC(=O)N[C@@H](Cc1ccccc1)C(=O)O",
        "[13CH3][CH2]C(=O)[O-].[NH4+]",
        "NC(N)=[NH2+]",
    ):
        scenarios[smiles] = MolEditorModel.from_smiles(smiles)
    sugar = MolEditorModel()
    atoms = sugar.add_ring_template("beta_glucopyranose", center=(0.0, 0.0))
    hydroxyl = next(i for i in atoms if sugar.atom_symbol(i) == "O" and sugar.atom_degree(i) == 1)
    sugar.add_ring_template("beta_glucopyranose", target_atom_idx=hydroxyl)
    scenarios["disaccharide"] = sugar
    return scenarios


SCENARIOS = _scenarios()


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_editor_operations_do_not_overlap_atoms_or_bonds(name):
    assert geometry_problems(SCENARIOS[name]) == []


def _rect_hits_segment(rect, a, b) -> bool:
    from ui.widgets.molecule_canvas import _rect_hits_segment as hits

    return bool(hits(rect, a, b))


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_atom_labels_do_not_collide(qtbot, name):
    from ui.widgets.molecule_canvas import MoleculeCanvas

    canvas = MoleculeCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(900, 700)
    canvas.set_model(SCENARIOS[name])
    canvas.fit_to_view()
    model = canvas.model()
    boxes = canvas._label_boxes()
    positions = [canvas._atom_screen(i) for i in range(model.atom_count)]
    clear = 0.62 * canvas._font_px(canvas.zoom())
    flat = [(atom, box) for atom, atom_boxes in boxes.items() for box in atom_boxes]
    for (a1, b1), (a2, b2) in itertools.combinations(flat, 2):
        assert a1 == a2 or not b1.intersects(b2), f"labels of atoms {a1} and {a2} overlap"
    for bond in range(model.bond_count):
        a, b = model.bond_atoms(bond)
        for atom, atom_boxes in boxes.items():
            for part, box in enumerate(atom_boxes):
                if atom in (a, b) and part == 0:
                    continue  # the bond is shortened around its own atom symbol
                start, end = positions[a], positions[b]
                if atom in (a, b):
                    centre = positions[atom]
                    other = end if atom == a else start
                    distance = math.dist((centre.x(), centre.y()), (other.x(), other.y()))
                    start, end = centre + (other - centre) * (clear / distance), other
                shrunk = box.adjusted(0.5, 0.5, -0.5, -0.5)
                assert not _rect_hits_segment(shrunk, start, end), (
                    f"bond {a}-{b} runs through the label of atom {atom}"
                )


def test_charge_and_hydrogen_placement_examples(qtbot):
    from ui.widgets.molecule_canvas import MoleculeCanvas

    canvas = MoleculeCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(600, 400)
    canvas.load_smiles("CC(C)(C)NC(C)(C)C")  # N–H between two branches: H goes below
    nitrogen = next(
        i for i in range(canvas.model().atom_count) if canvas.model().atom_symbol(i) == "N"
    )
    symbol_box, h_box = canvas._label_boxes()[nitrogen][:2]
    assert h_box.top() > symbol_box.bottom() - 1 or h_box.bottom() < symbol_box.top() + 1
    canvas.load_smiles("[NH4+]")
    symbol_box, h_box, charge_box = canvas._label_boxes()[0]
    assert charge_box.left() >= h_box.right() - 0.5  # NH₄⁺, not ⁺NH₄


# ---------------------------------------------------------------------------
# Exported images: no border, no distortion
# ---------------------------------------------------------------------------


def _alpha_margins(png: bytes) -> tuple[tuple[int, int, int, int], QImage]:
    image = QImage.fromData(png).convertToFormat(QImage.Format.Format_ARGB32)
    width, height = image.width(), image.height()
    xs, ys = [], []
    for y in range(0, height, max(1, height // 200)):
        for x in range(0, width, max(1, width // 200)):
            if image.pixelColor(x, y).alpha() > 0:
                xs.append(x)
                ys.append(y)
    return (min(xs), min(ys), width - 1 - max(xs), height - 1 - max(ys)), image


@pytest.mark.parametrize(
    "smiles",
    [
        "CCO",
        "CC(=O)Oc1ccccc1C(=O)O",
        "CC[NH3+].[Cl-]",
        "OC[C@H]1O[C@@H](O)[C@H](O)[C@@H](O)[C@@H]1O",
        "CCCCCCCCCCCCCCCCCCCC",
        "C",
        "[Na+].[Cl-]",
    ],
)
def test_report_structure_image_has_no_border_and_keeps_shape(qtbot, smiles):
    from chemistry.structure_renderer import render_structure

    model = MolEditorModel.from_smiles(smiles)
    rendered = render_structure(mol_block=model.to_mol_block())
    assert rendered is not None
    margins, image = _alpha_margins(rendered.png)
    longest = max(image.width(), image.height())
    step = max(1, longest // 200)
    assert max(margins) <= 0.012 * longest + step, f"empty border {margins}"
    assert (rendered.width_px, rendered.height_px) == (image.width(), image.height())
    # Not distorted: the picture has the molecule's own proportions.
    expected = rendered.height_units / rendered.width_units
    assert rendered.aspect == pytest.approx(expected, rel=0.25, abs=0.03)


def test_canvas_image_export_is_tight_and_undistorted(qtbot):
    from ui.widgets.molecule_canvas import MoleculeCanvas

    canvas = MoleculeCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(640, 480)
    for smiles in ("CC(=O)Oc1ccccc1C(=O)O", "CCO", "CCCCCCCCCCCCCCCCCCCC", "[Na+].[Cl-]"):
        canvas.load_smiles(smiles)
        for size in ((320, 200), (800, 600)):
            image = QImage.fromData(canvas.render_to_png_bytes(*size))
            assert image.width() <= size[0]
            assert image.height() <= size[1]
            assert max(image.width() / size[0], image.height() / size[1]) > 0.95
            # Ink reaches every edge (2 px margin): no empty border.
            ink = [
                (x, y)
                for y in range(image.height())
                for x in range(0, image.width(), 2)
                if image.pixelColor(x, y).lightness() < 200
            ]
            assert min(x for x, _ in ink) <= 6
            assert min(y for _, y in ink) <= 6
            assert image.width() - 1 - max(x for x, _ in ink) <= 6
            assert image.height() - 1 - max(y for _, y in ink) <= 6
    # Same aspect ratio at different sizes = no stretching in either direction.
    canvas.load_smiles("CC(=O)Oc1ccccc1C(=O)O")
    small = QImage.fromData(canvas.render_to_png_bytes(320, 320))
    large = QImage.fromData(canvas.render_to_png_bytes(900, 900))
    assert small.height() / small.width() == pytest.approx(large.height() / large.width(), rel=0.05)


def test_editor_preview_point_check():
    # Sanity check for the geometry helper itself.
    assert _segments_cross((0, 0), (2, 2), (0, 2), (2, 0))
    assert not _segments_cross((0, 0), (1, 0), (0, 1), (1, 1))
    assert _point_segment((1, 1), (0, 0), (2, 0)) == pytest.approx(1.0)
    assert QPointF(1, 1).x() == 1


def test_pdf_report_places_structure_without_border_or_distortion(tmp_path, monkeypatch):
    import io

    import numpy as np

    from core.project import Project
    from core.spectrum import SpectralUnit, Spectrum
    from reporting import pdf_generator
    from reporting.pdf_generator import PDFGenerator, ReportOptions

    placed: list[tuple[bytes, float, float]] = []
    original_image = pdf_generator.Image

    def recording_image(source, width=None, height=None, *args, **kwargs):
        if isinstance(source, io.BytesIO):
            placed.append((source.getvalue(), float(width), float(height)))
        return original_image(source, width, height, *args, **kwargs)

    monkeypatch.setattr(pdf_generator, "Image", recording_image)
    model = MolEditorModel.from_smiles("CC[NH3+].[Cl-]")
    model.add_ring_template("beta_glucopyranose", target_atom_idx=0)
    spectrum = Spectrum(
        wavenumbers=np.linspace(650, 4000, 200),
        intensities=np.linspace(20, 90, 200),
        y_unit=SpectralUnit.TRANSMITTANCE,
    )
    project = Project(name="glycoside salt", spectrum=spectrum)
    project.smiles = model.to_smiles()
    project.mol_block = model.to_mol_block()
    out = tmp_path / "report.pdf"
    PDFGenerator().generate(project, out, options=ReportOptions(include_structures=True))
    assert out.exists()

    structures = [entry for entry in placed if entry[0].startswith(b"\x89PNG")]
    assert structures, "the structure image was not placed in the report"
    for png, width, height in structures:
        image = QImage.fromData(png)
        # Placed with the picture's own aspect ratio: nothing is stretched.
        assert height / width == pytest.approx(image.height() / image.width(), rel=0.01)
        margins, _ = _alpha_margins(png)
        assert max(margins) <= 0.02 * max(image.width(), image.height()) + 4


@pytest.mark.parametrize("turn", [0.7, 2.1])
@pytest.mark.parametrize("group", ["-OTIPS", "-TIPS", "-OTBS", "-Ts", "-NHTs", "-Piv", "-OPiv"])
def test_bulky_groups_do_not_depend_on_the_depiction(monkeypatch, group, turn):
    """Another RDKit version may hand back a group mirrored or turned (as CI did)."""
    from rdkit.Chem import rdDepictor
    from rdkit.Geometry import Point3D

    import chemistry.mol_fragments as fragments

    def turned(mol):
        rdDepictor.Compute2DCoords(mol)
        conf = mol.GetConformer()
        c, s = math.cos(turn), math.sin(turn)
        for i in range(mol.GetNumAtoms()):
            p = conf.GetAtomPosition(i)
            x, y = p.x, -p.y  # mirrored, then turned
            conf.SetAtomPosition(i, Point3D(x * c - y * s, x * s + y * c, 0.0))
        return mol

    monkeypatch.setattr(fragments, "_with_coordinates", turned)
    for start, atoms in (("c1ccccc1", (0, 1, 2)), ("CC(C)C", (1,))):
        model = MolEditorModel.from_smiles(start)
        for atom in atoms:
            model.attach_functional_group(atom, group)
        assert geometry_problems(model) == [], (group, start)
