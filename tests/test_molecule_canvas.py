"""Tests for the native QPainter molecule canvas (ui.widgets.molecule_canvas)."""

from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("rdkit")

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from chemistry.mol_editor_model import BOND_LENGTH  # noqa: E402
from ui.widgets.molecule_canvas import (  # noqa: E402
    MAX_ZOOM,
    MIN_ZOOM,
    MoleculeCanvas,
    PeriodicTableDialog,
    element_category,
    periodic_table_positions,
)


@pytest.fixture
def canvas(qtbot):
    widget = MoleculeCanvas()
    qtbot.addWidget(widget)
    widget.resize(640, 480)
    widget.show()
    qtbot.waitExposed(widget)
    return widget


def _pt(canvas: MoleculeCanvas, atom: int) -> QPoint:
    return canvas._atom_screen(atom).toPoint()


def _bond_mid(canvas: MoleculeCanvas, bond: int) -> QPoint:
    a, b = canvas.model().bond_atoms(bond)
    pa, pb = canvas._atom_screen(a), canvas._atom_screen(b)
    return ((pa + pb) / 2).toPoint()


def _hover(canvas: MoleculeCanvas, point: QPoint) -> None:
    canvas._cursor = QPointF(point)
    canvas._update_hover(QPointF(point))


def _drag(canvas: MoleculeCanvas, start: QPoint, end: QPoint) -> None:
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    mid = QPoint((start.x() + end.x()) // 2, (start.y() + end.y()) // 2)
    QTest.mouseMove(canvas, mid)
    QTest.mouseMove(canvas, end)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)


# ---------------------------------------------------------------------------
# Drawing with the mouse
# ---------------------------------------------------------------------------


def test_click_on_empty_canvas_draws_a_bond(canvas, qtbot):
    with qtbot.waitSignal(canvas.structure_changed):
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=QPoint(200, 240))
    assert canvas.to_smiles() == "CC"
    # One click = one undo step.
    assert canvas.undo()
    assert canvas.model().is_empty()


def test_click_atom_sprouts_and_click_bond_cycles_order(canvas):
    canvas.load_smiles("CC")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=_pt(canvas, 1))
    assert canvas.to_smiles() == "CCC"
    bond = canvas.model().find_bond(0, 1)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=_bond_mid(canvas, bond))
    assert canvas.to_smiles() == "C=CC"
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=_bond_mid(canvas, bond))
    assert canvas.to_smiles() == "C#CC"


def test_double_bond_tool_on_atom(canvas):
    canvas.load_smiles("C")
    canvas.set_tool("bond_double")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=_pt(canvas, 0))
    assert canvas.to_smiles() == "C=C"


def test_drag_from_atom_snaps_to_30_degree_steps(canvas):
    canvas.load_smiles("C")
    start = _pt(canvas, 0)
    # 8° below the horizontal on screen → snapped to exactly 0°.
    end = QPoint(start.x() + 90, start.y() + 12)
    _drag(canvas, start, end)
    model = canvas.model()
    assert model.atom_count == 2
    x0, y0 = model.atom_position(0)
    x1, y1 = model.atom_position(1)
    assert math.hypot(x1 - x0, y1 - y0) == pytest.approx(BOND_LENGTH)
    assert math.degrees(math.atan2(y1 - y0, x1 - x0)) == pytest.approx(0.0, abs=1e-6)


def test_drag_onto_another_atom_closes_a_bond(canvas):
    canvas.load_smiles("C.C")
    _drag(canvas, _pt(canvas, 0), _pt(canvas, 1))
    assert canvas.model().atom_count == 2
    assert canvas.to_smiles() == "CC"


def test_wedge_tool_creates_stereo_bond(canvas):
    canvas.load_smiles("CCC(N)O")
    canvas.set_tool("bond_wedge")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=_pt(canvas, 2))
    assert "@" in canvas.to_smiles()


def test_chain_tool_drag_creates_zigzag_chain(canvas):
    canvas.set_tool("chain")
    scale = canvas._scale()
    step_px = BOND_LENGTH * math.cos(math.radians(30)) * scale
    start = QPoint(150, 240)
    end = QPoint(int(150 + 4 * step_px), 240)
    _drag(canvas, start, end)
    assert canvas.to_smiles() == "CCCCC"


def test_ring_tool_on_empty_space_and_on_bond(canvas):
    canvas.set_ring_type("benzene")
    assert canvas.tool() == "ring"
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=QPoint(320, 240))
    assert canvas.to_smiles() == "c1ccccc1"
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=_bond_mid(canvas, 0))
    assert canvas.to_smiles() == "c1ccc2ccccc2c1"


def test_ring_tool_on_atom_attaches_ring(canvas):
    canvas.load_smiles("CC")
    canvas.set_ring_type("cyclopropane")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=_pt(canvas, 1))
    assert canvas.to_smiles() == "CCC1CC1"


def test_group_tool_attaches_functional_group(canvas):
    canvas.load_smiles("c1ccccc1")
    canvas.set_group("-COOH")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=_pt(canvas, 0))
    assert canvas.to_smiles() == "O=C(O)c1ccccc1"


def test_atom_tool_replaces_and_places_atoms(canvas):
    canvas.load_smiles("CC")
    canvas.set_atom_symbol("N")
    assert canvas.tool() == "atom"
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=_pt(canvas, 1))
    assert canvas.to_smiles() == "CN"
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=QPoint(40, 40))
    assert canvas.to_smiles() == "CN.N"


def test_erase_tool_deletes_atoms_and_bonds(canvas):
    canvas.load_smiles("CCO")
    canvas.set_tool("erase")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=_pt(canvas, 2))
    assert canvas.to_smiles() == "CC"
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=_bond_mid(canvas, 0))
    assert canvas.to_smiles() == "C.C"


def test_select_tool_drag_moves_atom_with_single_undo(canvas):
    canvas.load_smiles("CC")
    canvas.set_tool("select")
    before = canvas.model().atom_position(1)
    start = _pt(canvas, 1)
    _drag(canvas, start, QPoint(start.x() + 40, start.y() - 30))
    after = canvas.model().atom_position(1)
    assert after[0] > before[0]
    assert after[1] > before[1]
    assert canvas.undo()
    assert canvas.model().atom_position(1) == pytest.approx(before)


def test_rubber_band_selection_and_delete(canvas):
    canvas.load_smiles("CCO")
    canvas.set_tool("select")
    _drag(canvas, QPoint(1, 1), QPoint(638, 478))
    assert canvas.selected_atoms() == {0, 1, 2}
    QTest.keyClick(canvas, Qt.Key.Key_Delete)
    assert canvas.model().is_empty()


# ---------------------------------------------------------------------------
# Keyboard
# ---------------------------------------------------------------------------


def test_hover_keys_change_atoms(canvas):
    canvas.load_smiles("CC")
    _hover(canvas, _pt(canvas, 1))
    QTest.keyClick(canvas, Qt.Key.Key_O)
    assert canvas.to_smiles() == "CO"
    _hover(canvas, _pt(canvas, 1))
    QTest.keyClick(canvas, Qt.Key.Key_L)
    assert canvas.to_smiles() == "CCl"
    _hover(canvas, _pt(canvas, 1))
    QTest.keyClick(canvas, Qt.Key.Key_R)
    assert canvas.to_smiles() == "CBr"
    _hover(canvas, _pt(canvas, 1))
    QTest.keyClick(canvas, Qt.Key.Key_N)
    QTest.keyClick(canvas, Qt.Key.Key_Plus, Qt.KeyboardModifier.NoModifier)
    assert canvas.to_smiles() == "C[NH3+]"
    QTest.keyClick(canvas, Qt.Key.Key_Minus)
    assert canvas.to_smiles() == "CN"
    QTest.keyClick(canvas, Qt.Key.Key_Delete)
    assert canvas.to_smiles() == "C"


def test_hover_keys_change_bonds(canvas):
    canvas.load_smiles("CC(N)O")
    bond = canvas.model().find_bond(0, 1)
    _hover(canvas, _bond_mid(canvas, bond))
    QTest.keyClick(canvas, Qt.Key.Key_2)
    assert canvas.to_smiles() == "C=C(N)O"
    _hover(canvas, _bond_mid(canvas, bond))
    QTest.keyClick(canvas, Qt.Key.Key_1)
    QTest.keyClick(canvas, Qt.Key.Key_W)
    bond = canvas.model().find_bond(0, 1)
    assert canvas.model().bond_stereo(bond) == "wedge"
    _hover(canvas, _bond_mid(canvas, bond))
    QTest.keyClick(canvas, Qt.Key.Key_H)
    bond = canvas.model().find_bond(0, 1)
    assert canvas.model().bond_stereo(bond) == "hash"
    _hover(canvas, _bond_mid(canvas, bond))
    QTest.keyClick(canvas, Qt.Key.Key_Delete)
    assert canvas.to_smiles() == "C.NCO"


def test_tool_keys_when_nothing_is_hovered(canvas, qtbot):
    canvas._cursor = None
    with qtbot.waitSignal(canvas.tool_changed) as blocker:
        QTest.keyClick(canvas, Qt.Key.Key_V)
    assert blocker.args == ["select"]
    for key, tool in (
        (Qt.Key.Key_2, "bond_double"),
        (Qt.Key.Key_3, "bond_triple"),
        (Qt.Key.Key_W, "bond_wedge"),
        (Qt.Key.Key_H, "bond_hash"),
        (Qt.Key.Key_C, "chain"),
        (Qt.Key.Key_1, "bond_single"),
        (Qt.Key.Key_Delete, "erase"),
    ):
        QTest.keyClick(canvas, key)
        assert canvas.tool() == tool


def test_undo_redo_shortcuts(canvas):
    canvas.load_smiles("CC")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=_pt(canvas, 1))
    assert canvas.to_smiles() == "CCC"
    QTest.keyClick(canvas, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert canvas.to_smiles() == "CC"
    QTest.keyClick(canvas, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
    assert canvas.to_smiles() == "CCC"
    QTest.keyClick(canvas, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClick(
        canvas,
        Qt.Key.Key_Z,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
    )
    assert canvas.to_smiles() == "CCC"


def test_copy_and_paste_smiles(canvas):
    canvas.load_smiles("CCO")
    QTest.keyClick(canvas, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert QGuiApplication.clipboard().text() == "CCO"
    QGuiApplication.clipboard().setText("c1ccccc1")
    QTest.keyClick(canvas, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    # The pasted structure follows the cursor until the user clicks.
    assert canvas.placement() is not None
    assert canvas.to_smiles() == "CCO"
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=QPoint(600, 60))
    assert canvas.placement() is None
    assert canvas.to_smiles() == "CCO.c1ccccc1"
    QGuiApplication.clipboard().setText(canvas.to_mol_block())
    canvas.clear()
    assert canvas.paste_from_clipboard()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=QPoint(320, 240))
    assert canvas.to_smiles() == "CCO.c1ccccc1"


def test_paste_text_inserts_immediately(canvas):
    canvas.load_smiles("CCO")
    assert canvas.paste_text("Cl")
    assert canvas.to_smiles() == "CCO.Cl"


def test_adjust_charge_uses_last_edited_atom(canvas):
    canvas.load_smiles("C")
    canvas.set_atom_symbol("O")
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=_pt(canvas, 0))
    assert canvas.adjust_charge(-1)
    assert canvas.to_smiles() == "[OH-]"


# ---------------------------------------------------------------------------
# View & rendering
# ---------------------------------------------------------------------------


def test_fit_to_view_centres_structure_and_zoom_is_clamped(canvas):
    canvas.load_smiles("CCCCCCCCCCCCCCCCCCCC")
    canvas.fit_to_view()
    bounds = canvas.model().bounds()
    center = canvas._to_screen((bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2)
    assert center.x() == pytest.approx(canvas.width() / 2, abs=1)
    assert center.y() == pytest.approx(canvas.height() / 2, abs=1)
    for idx in range(canvas.model().atom_count):
        p = canvas._atom_screen(idx)
        assert 0 <= p.x() <= canvas.width()
    canvas.set_zoom(100)
    assert canvas.zoom() == MAX_ZOOM
    canvas.set_zoom(0.001)
    assert canvas.zoom() == MIN_ZOOM


def test_space_key_fits_view(canvas):
    canvas.load_smiles("CCO")
    canvas.set_zoom(2.5)
    QTest.keyClick(canvas, Qt.Key.Key_Space)
    assert canvas.zoom() <= 1.5


def test_render_to_png_bytes(canvas):
    assert canvas.render_to_png_bytes() == b""
    canvas.load_smiles("CC(=O)Oc1ccccc1C(=O)O")
    png = canvas.render_to_png_bytes(320, 200)
    assert png.startswith(b"\x89PNG")
    from PySide6.QtGui import QImage

    image = QImage.fromData(png)
    assert (image.width(), image.height()) == (320, 200)


def test_paint_handles_hover_invalid_atoms_and_ghosts(canvas):
    canvas.load_smiles("C(C)(C)(C)C")
    canvas.model().sprout_atom(0)  # pentavalent carbon → red marker
    assert canvas.model().invalid_atom_indices() == {0}
    _hover(canvas, _pt(canvas, 0))
    canvas.set_ring_type("benzene")
    canvas.grab()
    canvas.set_tool("chain")
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(40, 40))
    QTest.mouseMove(canvas, QPoint(200, 60))
    canvas.grab()
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(200, 60))


def test_load_invalid_input_is_rejected(canvas):
    assert not canvas.load_smiles("not_a_smiles_xyz!!!")
    assert not canvas.load_mol_block("FAKE MOL")
    assert canvas.model().is_empty()


# ---------------------------------------------------------------------------
# Periodic table
# ---------------------------------------------------------------------------


def test_periodic_table_layout():
    positions = periodic_table_positions()
    assert len(positions) == 118
    assert positions["H"] == (0, 0)
    assert positions["He"] == (0, 17)
    assert positions["Fe"] == (3, 7)
    assert positions["Og"] == (6, 17)
    assert positions["La"] == (7, 2)
    assert positions["Lr"] == (8, 16)
    assert len(set(positions.values())) == 118
    assert element_category("Na") == "alkali"
    assert element_category("Cl") == "halogen"
    assert element_category("Fe") == "transition"


def test_periodic_table_dialog_returns_symbol(qtbot):
    dialog = PeriodicTableDialog()
    qtbot.addWidget(dialog)
    dialog.button_for("Fe").click()
    assert dialog.result() == PeriodicTableDialog.DialogCode.Accepted
    assert dialog.selected_symbol() == "Fe"


# ---------------------------------------------------------------------------
# Selection clipboard, placement, labels and context menu
# ---------------------------------------------------------------------------


def test_copy_part_of_molecule_and_attach_it_to_chain(canvas):
    canvas.load_smiles("CCCC(=O)O")
    canvas.select_atoms({3, 4, 5})  # the COOH group
    assert canvas.copy_selection()
    assert (
        QGuiApplication.clipboard().mimeData().hasFormat("application/x-ir-spectra-fragment+json")
    )
    canvas.load_smiles("CCCCC")
    QTest.keyClick(canvas, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert canvas.placement() is not None
    end_atom = next(i for i in range(5) if canvas.model().atom_degree(i) == 1)
    _hover(canvas, _pt(canvas, end_atom))
    canvas.grab()  # ghost preview attached to the hovered atom
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=_pt(canvas, end_atom))
    assert canvas.to_smiles() == "CCCCCC(=O)O"
    assert not canvas.model().invalid_atom_indices()


def test_cut_and_duplicate_selection(canvas):
    canvas.load_smiles("CC.O")
    canvas.select_atoms({2})
    QTest.keyClick(canvas, Qt.Key.Key_X, Qt.KeyboardModifier.ControlModifier)
    assert canvas.to_smiles() == "CC"
    canvas.select_atoms({0, 1})
    QTest.keyClick(canvas, Qt.Key.Key_D, Qt.KeyboardModifier.ControlModifier)
    assert canvas.to_smiles() == "CC.CC"
    assert canvas.selected_atoms() == {2, 3}


def test_place_salt_next_to_structure(canvas):
    from chemistry.mol_fragments import fragment_from_smiles

    canvas.load_smiles("CCN")
    fragment = fragment_from_smiles("Cl")
    assert fragment is not None
    fragment.attach = None
    canvas.begin_placement(fragment, "HCl")
    assert "HCl" in canvas.hint()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=QPoint(560, 80))
    assert canvas.to_smiles() == "CCN.Cl"
    assert canvas.model().display_formula() == "C₂H₇N · HCl"


def test_escape_and_right_click_cancel_placement(canvas):
    from chemistry.mol_fragments import fragment_from_smiles

    fragment = fragment_from_smiles("O")
    assert fragment is not None
    canvas.begin_placement(fragment)
    QTest.keyClick(canvas, Qt.Key.Key_Escape)
    assert canvas.placement() is None
    canvas.begin_placement(fragment)
    QTest.mouseClick(canvas, Qt.MouseButton.RightButton, pos=QPoint(100, 100))
    assert canvas.placement() is None
    assert canvas.model().is_empty()


def test_paste_abbreviation_text_attaches_group(canvas):
    canvas.load_smiles("c1ccccc1")
    QGuiApplication.clipboard().setText("CO2Et")
    assert canvas.paste_from_clipboard()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=_pt(canvas, 0))
    assert canvas.to_smiles() == "CCOC(=O)c1ccccc1"
    QGuiApplication.clipboard().setText("")
    assert not canvas.paste_from_clipboard()


def test_inline_label_editor_applies_groups(canvas):
    canvas.load_smiles("c1ccccc1C")
    canvas.edit_atom_label(6)
    editor = canvas._label_editor
    assert editor.isVisible()
    editor.setText("xyz!")
    QTest.keyClick(editor, Qt.Key.Key_Return)
    assert editor.isVisible()  # unknown text keeps the editor open
    assert "xyz!" in canvas.hint()
    editor.setText("OMe")
    QTest.keyClick(editor, Qt.Key.Key_Return)
    assert not editor.isVisible()
    assert canvas.to_smiles() == "COc1ccccc1"


def test_enter_on_hovered_atom_and_double_click_open_label_editor(canvas):
    canvas.load_smiles("CC")
    _hover(canvas, _pt(canvas, 1))
    QTest.keyClick(canvas, Qt.Key.Key_Return)
    assert canvas._label_editor.isVisible()
    QTest.keyClick(canvas._label_editor, Qt.Key.Key_Escape)
    assert not canvas._label_editor.isVisible()
    canvas.set_tool("select")
    QTest.mouseDClick(canvas, Qt.MouseButton.LeftButton, pos=_pt(canvas, 1))
    assert canvas._label_editor.isVisible()
    canvas._label_editor.setText("N+")
    QTest.keyClick(canvas._label_editor, Qt.Key.Key_Return)
    assert canvas.to_smiles() == "C[NH3+]"


def test_custom_groups_are_used_by_labels(canvas):
    canvas.load_smiles("CC")
    canvas.set_custom_groups({"Pin": "*B1OC(C)(C)C(C)(C)O1"})
    assert canvas.apply_label(1, "Pin")
    assert "B" in canvas.to_smiles()


def test_dragging_atom_onto_atom_merges_them(canvas):
    canvas.load_smiles("CC.CO")
    canvas.set_tool("select")
    model = canvas.model()
    # Put the second fragment's carbon close to the first chain's end.
    target = model.atom_position(1)
    model.move_fragment(
        [2, 3], target[0] - model.atom_position(2)[0] + 2.0, target[1] - model.atom_position(2)[1]
    )
    canvas.update()
    _drag(canvas, _pt(canvas, 2), _pt(canvas, 1))
    assert canvas.to_smiles() == "CCO"
    assert canvas.undo()
    assert canvas.to_smiles() == "CC.CO"


def test_alt_keys_rotate_and_flip(canvas):
    canvas.load_smiles("C[C@H](N)O")
    before = canvas.model().atom_position(0)
    QTest.keyClick(canvas, Qt.Key.Key_Left, Qt.KeyboardModifier.AltModifier)
    assert canvas.model().atom_position(0) != pytest.approx(before)
    QTest.keyClick(canvas, Qt.Key.Key_H, Qt.KeyboardModifier.AltModifier)
    QTest.keyClick(canvas, Qt.Key.Key_V, Qt.KeyboardModifier.AltModifier)
    assert canvas.to_smiles() == "C[C@H](N)O"


def test_context_menu_for_atom_bond_selection_and_background(canvas):
    canvas.load_smiles("CCO")
    atom_menu = canvas.build_context_menu(QPointF(canvas._atom_screen(2)))
    texts = [a.text() for a in atom_menu.actions()]
    assert "Atom properties…" in texts
    assert "Edit label…" in texts
    charge = next(a for a in atom_menu.actions() if a.text() == "Increase charge (+)")
    charge.trigger()
    assert canvas.to_smiles() == "CC[OH2+]"

    bond = canvas.model().find_bond(0, 1)
    bond_menu = canvas.build_context_menu(QPointF(_bond_mid(canvas, bond)))
    double = next(a for a in bond_menu.actions() if a.text() == "Double Bond")
    double.trigger()
    assert canvas.to_smiles() == "C=C[OH2+]"

    canvas.select_atoms({0, 1})
    selection_menu = canvas.build_context_menu(QPointF(5, 5))
    texts = [a.text() for a in selection_menu.actions()]
    for expected in ("Copy", "Cut", "Duplicate", "Save as custom group…", "Flip horizontally"):
        assert expected in texts
    background = [a.text() for a in canvas.build_context_menu(QPointF(5, 5)).actions()]
    assert "Paste" in background
    assert "Show all hydrogens" in background


def test_right_click_without_drag_opens_context_menu(canvas, monkeypatch):
    shown: list[QPointF] = []
    monkeypatch.setattr(canvas, "show_context_menu", lambda point: shown.append(point))
    QTest.mouseClick(canvas, Qt.MouseButton.RightButton, pos=QPoint(50, 60))
    assert len(shown) == 1


def test_atom_properties_dialog_applies_values(canvas, monkeypatch):
    from ui.widgets import molecule_canvas

    canvas.load_smiles("CC")

    def fake_exec(dialog):
        dialog.symbol_edit.setText("N")
        dialog.charge_spin.setValue(1)
        dialog.isotope_spin.setValue(15)
        return molecule_canvas.QDialog.DialogCode.Accepted

    monkeypatch.setattr(molecule_canvas.AtomPropertiesDialog, "exec", fake_exec)
    assert canvas.open_atom_properties(1)
    assert canvas.to_smiles() == "C[15NH3+]"


def test_atom_properties_dialog_values(qtbot):
    from chemistry.mol_editor_model import MolEditorModel
    from ui.widgets.molecule_canvas import AtomPropertiesDialog

    model = MolEditorModel.from_smiles("C[13CH2]")
    model.set_atom_radicals(1, 1)
    dialog = AtomPropertiesDialog(model, 1)
    qtbot.addWidget(dialog)
    values = dialog.values()
    assert values == {
        "symbol": "C",
        "charge": 0,
        "isotope": 13,
        "hydrogens": None,
        "radicals": 1,
    }
    dialog.symbol_edit.setText("Qq")
    dialog._on_accept()
    assert dialog.result() != dialog.DialogCode.Accepted


def test_save_group_request_emits_fragment(canvas, qtbot):
    canvas.load_smiles("CCOC(C)=O")
    assert not canvas.request_save_group()
    canvas.select_atoms({2, 3, 4, 5})
    with qtbot.waitSignal(canvas.save_group_requested) as blocker:
        assert canvas.request_save_group()
    fragment = blocker.args[0]
    assert fragment.attach is not None
    assert fragment.atom_count == 4


def test_display_options_and_special_labels_paint(canvas):
    canvas.load_smiles("C[C@H](N)O.[13CH3][CH2]")  # [CH2] is a radical centre
    canvas.set_show_atom_numbers(True)
    canvas.set_show_stereo_labels(True)
    assert canvas.show_atom_numbers()
    assert canvas.show_stereo_labels()
    canvas.grab()
    assert canvas._stereo_atoms == {1: "R"}
    assert any(label.isotope == 13 for label in canvas._labels.values())
    assert any(label.radicals == 1 for label in canvas._labels.values())
    canvas.set_show_stereo_labels(False)
    canvas.grab()
    assert canvas._stereo_atoms == {}


def test_explicit_hydrogen_actions(canvas):
    canvas.load_smiles("CO")
    assert canvas.add_explicit_hydrogens() == 4
    assert canvas.remove_explicit_hydrogens() == 4
    assert canvas.to_smiles() == "CO"
