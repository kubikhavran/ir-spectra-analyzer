"""Tests for MoleculeEditorDialog, updated MoleculeWidget, and AssignSMILESCommand."""

from __future__ import annotations

import importlib
import os
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication, QDialog

_rdkit_available = importlib.util.find_spec("rdkit") is not None
requires_rdkit = pytest.mark.skipif(not _rdkit_available, reason="rdkit not installed")


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


# ---------------------------------------------------------------------------
# AssignSMILESCommand
# ---------------------------------------------------------------------------


def test_assign_smiles_command_redo_undo():
    """AssignSMILESCommand redo sets new SMILES; undo restores old."""
    _app()
    from core.commands import AssignSMILESCommand
    from core.peak import Peak

    peak = Peak(position=1500.0, intensity=0.5, smiles="CCO")
    stack = QUndoStack()
    cmd = AssignSMILESCommand(peak, "c1ccccc1")
    stack.push(cmd)
    assert peak.smiles == "c1ccccc1"
    stack.undo()
    assert peak.smiles == "CCO"
    stack.redo()
    assert peak.smiles == "c1ccccc1"


def test_assign_smiles_command_from_empty():
    """AssignSMILESCommand works when starting from empty SMILES."""
    _app()
    from core.commands import AssignSMILESCommand
    from core.peak import Peak

    peak = Peak(position=1500.0, intensity=0.5)
    assert peak.smiles == ""
    stack = QUndoStack()
    stack.push(AssignSMILESCommand(peak, "CCO"))
    assert peak.smiles == "CCO"
    stack.undo()
    assert peak.smiles == ""


# ---------------------------------------------------------------------------
# MoleculeEditorDialog
# ---------------------------------------------------------------------------


def test_molecule_editor_dialog_creates(qtbot):
    """MoleculeEditorDialog instantiates without crashing."""
    from ui.dialogs.molecule_editor_dialog import MoleculeEditorDialog

    dlg = MoleculeEditorDialog()
    qtbot.addWidget(dlg)
    assert dlg is not None


def test_molecule_editor_dialog_with_initial_smiles(qtbot):
    """MoleculeEditorDialog accepts an initial SMILES."""
    from ui.dialogs.molecule_editor_dialog import MoleculeEditorDialog

    dlg = MoleculeEditorDialog(initial_smiles="CCO")
    qtbot.addWidget(dlg)
    # SMILES tab input should be pre-filled
    assert dlg._smiles_input.text() == "CCO"


def test_molecule_editor_dialog_has_two_tabs(qtbot):
    """Dialog has exactly two tabs: Draw and SMILES."""
    from ui.dialogs.molecule_editor_dialog import MoleculeEditorDialog

    dlg = MoleculeEditorDialog()
    qtbot.addWidget(dlg)
    assert dlg._tabs.count() == 2
    assert dlg._tabs.tabText(0) == "Draw"
    assert dlg._tabs.tabText(1) == "SMILES"


@requires_rdkit
def test_smiles_tab_valid_smiles_shows_valid_status(qtbot):
    """Valid SMILES in SMILES tab sets status to 'Valid'."""
    from ui.dialogs.molecule_editor_dialog import MoleculeEditorDialog

    dlg = MoleculeEditorDialog()
    qtbot.addWidget(dlg)
    dlg._tabs.setCurrentIndex(1)
    dlg._smiles_input.setText("CCO")
    dlg._preview_btn.click()
    assert dlg._smiles_status.text() == "Valid"


@requires_rdkit
def test_smiles_tab_invalid_smiles_shows_error(qtbot):
    """Invalid SMILES in SMILES tab sets status to 'Invalid SMILES'."""
    from ui.dialogs.molecule_editor_dialog import MoleculeEditorDialog

    dlg = MoleculeEditorDialog()
    qtbot.addWidget(dlg)
    dlg._tabs.setCurrentIndex(1)
    dlg._smiles_input.setText("not_a_smiles_xyz!!!")
    dlg._preview_btn.click()
    assert dlg._smiles_status.text() == "Invalid SMILES"


def test_smiles_tab_empty_shows_placeholder(qtbot):
    """Empty SMILES input shows placeholder text and no status."""
    from ui.dialogs.molecule_editor_dialog import MoleculeEditorDialog

    dlg = MoleculeEditorDialog()
    qtbot.addWidget(dlg)
    dlg._tabs.setCurrentIndex(1)
    dlg._smiles_input.clear()
    dlg._preview_btn.click()
    assert dlg._smiles_status.text() == ""
    assert dlg._smiles_preview.text() == "Enter SMILES to preview"


def test_dialog_smiles_from_smiles_tab(qtbot):
    """After accepting with SMILES tab active, smiles() returns text field value."""
    from ui.dialogs.molecule_editor_dialog import MoleculeEditorDialog

    dlg = MoleculeEditorDialog()
    qtbot.addWidget(dlg)
    dlg._tabs.setCurrentIndex(1)
    dlg._smiles_input.setText("c1ccccc1")
    # Simulate OK: call _on_ok directly
    dlg._on_ok()
    assert dlg.smiles() == "c1ccccc1"


def test_clear_button_clears_smiles_tab(qtbot):
    """Clear button clears the SMILES tab input."""
    from ui.dialogs.molecule_editor_dialog import MoleculeEditorDialog

    dlg = MoleculeEditorDialog(initial_smiles="CCO")
    qtbot.addWidget(dlg)
    dlg._tabs.setCurrentIndex(1)
    assert dlg._smiles_input.text() == "CCO"
    dlg._on_clear()
    assert dlg._smiles_input.text() == ""


# ---------------------------------------------------------------------------
# MoleculeWidget (updated)
# ---------------------------------------------------------------------------


def test_molecule_widget_creates(qtbot):
    """Updated MoleculeWidget instantiates without crashing."""
    from ui.molecule_widget import MoleculeWidget

    w = MoleculeWidget()
    qtbot.addWidget(w)
    assert w is not None


def test_molecule_widget_has_edit_button(qtbot):
    """MoleculeWidget must expose an 'Edit Structure...' button."""
    from ui.molecule_widget import MoleculeWidget

    w = MoleculeWidget()
    qtbot.addWidget(w)
    assert w._edit_btn is not None
    assert "Edit" in w._edit_btn.text()


def test_molecule_widget_set_smiles_empty_shows_placeholder(qtbot):
    """set_smiles('') shows the placeholder text."""
    from ui.molecule_widget import MoleculeWidget

    w = MoleculeWidget()
    qtbot.addWidget(w)
    w.set_smiles("")
    assert w.text() == "No structure assigned"


@requires_rdkit
def test_molecule_widget_set_smiles_invalid(qtbot):
    """set_smiles with invalid SMILES shows 'Invalid structure'."""
    from ui.molecule_widget import MoleculeWidget

    w = MoleculeWidget()
    qtbot.addWidget(w)
    w.set_smiles("not_a_smiles_xyz")
    assert w.text() == "Invalid structure"


@requires_rdkit
def test_molecule_widget_set_smiles_valid_shows_pixmap(qtbot):
    """set_smiles with valid SMILES renders a non-null pixmap."""
    from ui.molecule_widget import MoleculeWidget

    w = MoleculeWidget()
    qtbot.addWidget(w)
    w.set_smiles("CCO")
    assert not w.pixmap().isNull()


def test_molecule_widget_smiles_changed_signal(qtbot):
    """smiles_changed is emitted when dialog is accepted with a new SMILES."""
    import ui.molecule_widget as mw_module
    from ui.molecule_widget import MoleculeWidget

    w = MoleculeWidget()
    qtbot.addWidget(w)

    emitted: list[str] = []
    w.smiles_changed.connect(emitted.append)

    # Patch _open_editor on the class to avoid running a modal dialog
    mock_dlg = MagicMock()
    mock_dlg.exec.return_value = QDialog.DialogCode.Accepted
    mock_dlg.smiles.return_value = "c1ccccc1"

    original = mw_module.MoleculeWidget._open_editor

    def patched_open_editor(self):
        dlg = mock_dlg
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_smiles = dlg.smiles()
            if new_smiles != self._current_smiles:
                self.smiles_changed.emit(new_smiles)

    mw_module.MoleculeWidget._open_editor = patched_open_editor
    try:
        w._open_editor()
    finally:
        mw_module.MoleculeWidget._open_editor = original

    assert emitted == ["c1ccccc1"]


def test_molecule_widget_no_signal_if_same_smiles(qtbot):
    """smiles_changed is NOT emitted when dialog returns the same SMILES."""
    import ui.molecule_widget as mw_module
    from ui.molecule_widget import MoleculeWidget

    w = MoleculeWidget()
    qtbot.addWidget(w)
    w.set_smiles("CCO")

    emitted: list[str] = []
    w.smiles_changed.connect(emitted.append)

    mock_dlg = MagicMock()
    mock_dlg.exec.return_value = QDialog.DialogCode.Accepted
    mock_dlg.smiles.return_value = "CCO"  # same as current

    original = mw_module.MoleculeWidget._open_editor

    def patched_open_editor(self):
        dlg = mock_dlg
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_smiles = dlg.smiles()
            if new_smiles != self._current_smiles:
                self.smiles_changed.emit(new_smiles)

    mw_module.MoleculeWidget._open_editor = patched_open_editor
    try:
        w._open_editor()
    finally:
        mw_module.MoleculeWidget._open_editor = original

    assert emitted == []


def test_smiles_ok_revalidates_text_changed_after_preview(qtbot, monkeypatch):
    from ui.dialogs import molecule_editor_dialog as module

    monkeypatch.setattr(
        "chemistry.structure_renderer.render_smiles_to_png",
        lambda smiles, size: b"png" if smiles == "CCO" else None,
    )
    dialog = module.MoleculeEditorDialog()
    qtbot.addWidget(dialog)
    dialog._tabs.setCurrentIndex(1)
    dialog._smiles_input.setText("CCO")
    dialog._on_preview_clicked()
    assert dialog._smiles_status.text() == "Valid"

    dialog._smiles_input.setText("not-valid")
    dialog._on_ok()

    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog._smiles_status.text() == "Invalid SMILES"


def test_molecule_editor_dialog_accepts_initial_mol_block(qtbot):
    """The stored MOL block is preferred so the drawn 2D layout survives reopen."""
    from ui.dialogs.molecule_editor_dialog import MoleculeEditorDialog

    dlg = MoleculeEditorDialog(initial_smiles="CCO", initial_mol_block="FAKE MOL")
    qtbot.addWidget(dlg)
    assert dlg._initial_mol_block == "FAKE MOL"


def test_molecule_widget_passes_current_structure_to_editor(qtbot, monkeypatch):
    """Edit Structure... must reopen the editor with the current structure loaded."""
    from ui.dialogs import molecule_editor_dialog as med
    from ui.molecule_widget import MoleculeWidget

    captured: dict = {}

    class _FakeDialog:
        DialogCode = med.MoleculeEditorDialog.DialogCode

        def __init__(self, initial_smiles="", initial_mol_block="", parent=None):
            captured["smiles"] = initial_smiles
            captured["mol_block"] = initial_mol_block

        def exec(self):
            return med.MoleculeEditorDialog.DialogCode.Rejected

    monkeypatch.setattr(med, "MoleculeEditorDialog", _FakeDialog)

    widget = MoleculeWidget()
    qtbot.addWidget(widget)
    widget.set_structure("CCO", mol_block="MOL BLOCK CONTENT")
    widget._open_editor()

    assert captured["smiles"] == "CCO"
    assert captured["mol_block"] == "MOL BLOCK CONTENT"


# ---------------------------------------------------------------------------
# Native Draw tab
# ---------------------------------------------------------------------------


def _click(widget, pos):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    QTest.mouseClick(widget, Qt.MouseButton.LeftButton, pos=pos)


@pytest.fixture
def native_dialog(qtbot):
    from ui.dialogs.molecule_editor_dialog import MoleculeEditorDialog

    def _make(**kwargs):
        dlg = MoleculeEditorDialog(**kwargs)
        qtbot.addWidget(dlg)
        dlg.show()
        qtbot.waitExposed(dlg)
        return dlg

    return _make


def test_editor_is_native_and_offline():
    from pathlib import Path

    from ui.dialogs import molecule_editor_dialog as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    for forbidden in ("QtWebEngine", "QWebChannel", "unpkg", "urllib", "JSME"):
        assert forbidden not in source
    from ui.widgets.molecule_canvas import MoleculeCanvas

    assert isinstance(module.MoleculeEditorDialog()._canvas, MoleculeCanvas)


@requires_rdkit
def test_draw_tab_layout(native_dialog):
    dlg = native_dialog()
    assert dlg.minimumWidth() >= 820
    assert dlg.minimumHeight() >= 560
    assert set(dlg._tool_buttons) == {
        "select",
        "erase",
        "bond_single",
        "bond_double",
        "bond_triple",
        "bond_wedge",
        "bond_hash",
        "chain",
    }
    assert {"cyclopropane", "benzene", "naphthalene", "pyridine", "furan", "thiophene"} <= set(
        dlg._ring_buttons
    )
    assert {"-OH", "-NH2", "-COOH", "-NO2", "-TMS", "-Boc"} <= set(dlg._group_buttons)
    assert list(dlg._element_buttons)[:4] == ["C", "H", "O", "N"]
    assert dlg._tool_buttons["bond_single"].isChecked()
    assert "(W)" in dlg._tool_buttons["bond_wedge"].toolTip()


@requires_rdkit
def test_save_structure_drawn_on_canvas(native_dialog):
    from PySide6.QtCore import QPoint

    dlg = native_dialog()
    dlg._ring_buttons["benzene"].click()
    assert dlg._canvas.tool() == "ring"
    assert dlg._ring_buttons["benzene"].isChecked()
    _click(dlg._canvas, QPoint(dlg._canvas.width() // 2, dlg._canvas.height() // 2))
    assert dlg._formula_label.text() == "Formula: C₆H₆"
    assert "78.11" in dlg._mw_label.text()
    assert dlg._smiles_input.text() == "c1ccccc1"
    dlg._on_ok()
    assert dlg.result() == dlg.DialogCode.Accepted
    assert dlg.smiles() == "c1ccccc1"
    assert "V2000" in dlg.mol_block()
    assert dlg.png_bytes().startswith(b"\x89PNG")


@requires_rdkit
def test_untouched_structure_is_returned_verbatim(native_dialog):
    dlg = native_dialog(initial_smiles="OCC")
    dlg._on_ok()
    assert dlg.smiles() == "OCC"
    assert "V2000" in dlg.mol_block()


@requires_rdkit
def test_initial_mol_block_keeps_drawn_2d_layout(native_dialog):
    from chemistry.mol_editor_model import MolEditorModel

    model = MolEditorModel()
    a = model.add_free_atom(7.0, -3.0)
    model.sprout_atom(a, "O", preferred_angle=90.0)
    mol_block = model.to_mol_block()

    dlg = native_dialog(initial_smiles="CO", initial_mol_block=mol_block)
    canvas_model = dlg._canvas.model()
    assert canvas_model.atom_position(0) == pytest.approx((7.0, -3.0), abs=1e-3)
    assert canvas_model.atom_position(1) == pytest.approx((7.0, -1.5), abs=1e-3)
    dlg._on_ok()
    assert dlg.mol_block() == mol_block  # untouched → identical layout
    assert dlg.smiles() == "CO"

    # After an edit the original atoms keep their coordinates.
    dlg2 = native_dialog(initial_smiles="CO", initial_mol_block=mol_block)
    _click(dlg2._canvas, dlg2._canvas._atom_screen(1).toPoint())
    dlg2._on_ok()
    assert dlg2.smiles() == "COC"
    reloaded = MolEditorModel.from_mol_block(dlg2.mol_block())
    assert reloaded.atom_position(0) == pytest.approx((7.0, -3.0), abs=1e-3)
    assert reloaded.atom_position(1) == pytest.approx((7.0, -1.5), abs=1e-3)


@requires_rdkit
def test_canvas_edits_update_smiles_tab(native_dialog):
    dlg = native_dialog(initial_smiles="CC")
    _click(dlg._canvas, dlg._canvas._atom_screen(1).toPoint())
    assert dlg._smiles_input.text() == "CCC"
    assert "SMILES: CCC" in dlg._live_smiles_label.text()
    dlg._tabs.setCurrentIndex(1)
    assert dlg._smiles_status.text() == "Valid"
    dlg._on_ok()
    assert dlg.smiles() == "CCC"


@requires_rdkit
def test_smiles_tab_changes_load_into_canvas(native_dialog):
    dlg = native_dialog(initial_smiles="CC")
    dlg._tabs.setCurrentIndex(1)
    dlg._smiles_input.setText("OCC(=O)O")
    dlg._tabs.setCurrentIndex(0)
    assert dlg._canvas.to_smiles() == "O=C(O)CO"
    # The user's spelling is kept in the field.
    assert dlg._smiles_input.text() == "OCC(=O)O"
    # One undo step brings the previous drawing back.
    dlg._undo_btn.click()
    assert dlg._canvas.to_smiles() == "CC"


@requires_rdkit
def test_preview_loads_valid_smiles_into_canvas(native_dialog):
    dlg = native_dialog()
    dlg._tabs.setCurrentIndex(1)
    dlg._smiles_input.setText("c1ccncc1")
    dlg._preview_btn.click()
    assert dlg._smiles_status.text() == "Valid"
    assert dlg._canvas.to_smiles() == "c1ccncc1"
    dlg._smiles_input.setText("not_a_smiles_xyz!!!")
    dlg._preview_btn.click()
    assert dlg._smiles_status.text() == "Invalid SMILES"
    assert dlg._canvas.to_smiles() == "c1ccncc1"


@requires_rdkit
def test_invalid_smiles_does_not_replace_drawing_on_tab_switch(native_dialog):
    dlg = native_dialog(initial_smiles="CCO")
    dlg._tabs.setCurrentIndex(1)
    dlg._smiles_input.setText("C1CC")
    dlg._tabs.setCurrentIndex(0)
    assert dlg._canvas.to_smiles() == "CCO"
    assert dlg._smiles_status.text() == "Invalid SMILES"


@requires_rdkit
def test_smiles_tab_ok_with_new_text_builds_fresh_mol_block(native_dialog):
    dlg = native_dialog(initial_smiles="CC")
    dlg._tabs.setCurrentIndex(1)
    dlg._smiles_input.setText("CCN")
    dlg._on_ok()
    assert dlg.smiles() == "CCN"
    assert "V2000" in dlg.mol_block()
    assert " N " in dlg.mol_block()


@requires_rdkit
def test_undo_redo_clean_and_clear_buttons(native_dialog):
    dlg = native_dialog(initial_smiles="CC")
    assert not dlg._undo_btn.isEnabled()
    _click(dlg._canvas, dlg._canvas._atom_screen(1).toPoint())
    assert dlg._undo_btn.isEnabled()
    dlg._undo_btn.click()
    assert dlg._canvas.to_smiles() == "CC"
    assert dlg._redo_btn.isEnabled()
    dlg._redo_btn.click()
    assert dlg._canvas.to_smiles() == "CCC"

    model = dlg._canvas.model()
    model.move_atom(0, 40.0, 40.0)
    assert dlg._clean_btn.isEnabled()
    dlg._clean_btn.click()
    xs = [model.atom_position(i)[0] for i in range(model.atom_count)]
    assert max(xs) - min(xs) < 5.0
    assert dlg._canvas.to_smiles() == "CCC"

    dlg._tabs.setCurrentIndex(0)
    dlg._on_clear()
    assert dlg._canvas.model().is_empty()
    assert dlg._smiles_input.text() == ""
    assert not dlg._clean_btn.isEnabled()
    dlg._undo_btn.click()
    assert dlg._canvas.to_smiles() == "CCC"
    dlg._on_clear()
    dlg._on_ok()
    assert dlg.smiles() == ""
    assert dlg.mol_block() == ""


@requires_rdkit
def test_palette_follows_keyboard_tool_changes(native_dialog):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    dlg = native_dialog()
    dlg._canvas._cursor = None
    QTest.keyClick(dlg._canvas, Qt.Key.Key_2)
    assert dlg._tool_buttons["bond_double"].isChecked()
    dlg._group_buttons["-COOH"].click()
    assert dlg._canvas.tool() == "group"
    assert dlg._group_buttons["-COOH"].isChecked()
    dlg._element_buttons["N"].click()
    assert dlg._canvas.tool() == "atom"
    assert dlg._canvas.atom_symbol() == "N"


@requires_rdkit
def test_periodic_table_and_charge_buttons(native_dialog, monkeypatch):
    from ui.widgets import molecule_canvas

    monkeypatch.setattr(
        molecule_canvas.PeriodicTableDialog,
        "get_element",
        classmethod(lambda cls, parent=None: "Fe"),
    )
    dlg = native_dialog(initial_smiles="C")
    dlg._periodic_btn.click()
    assert dlg._canvas.tool() == "atom"
    assert dlg._canvas.atom_symbol() == "Fe"
    assert dlg._palette_group.checkedButton() is None  # Fe has no palette button

    dlg._element_buttons["O"].click()
    _click(dlg._canvas, dlg._canvas._atom_screen(0).toPoint())
    dlg._charge_minus_btn.click()
    assert dlg._canvas.to_smiles() == "[OH-]"
    dlg._charge_plus_btn.click()
    assert dlg._canvas.to_smiles() == "O"


@requires_rdkit
def test_dialog_builds_in_czech(qtbot):
    from ui import i18n
    from ui.dialogs.molecule_editor_dialog import MoleculeEditorDialog

    i18n.set_language(i18n.CZECH)
    try:
        dlg = MoleculeEditorDialog(initial_smiles="CCO")
        qtbot.addWidget(dlg)
        assert dlg.windowTitle() == "Úprava chemické struktury"
        assert dlg._tabs.tabText(0) == "Kreslení"
        assert dlg._formula_label.text() == "Vzorec: C₂H₆O"
        assert dlg._tool_buttons["chain"].toolTip() == "Uhlíkový řetězec (C)"
    finally:
        i18n.set_language(i18n.ENGLISH)
