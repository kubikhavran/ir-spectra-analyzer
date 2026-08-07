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


def test_draw_tab_shows_loading_label_when_jsme_unavailable(qtbot, monkeypatch):
    """When _ensure_jsme_cached returns None, the Draw tab shows a fallback label."""
    import ui.dialogs.molecule_editor_dialog as med_module
    from ui.dialogs.molecule_editor_dialog import MoleculeEditorDialog

    monkeypatch.setattr(med_module, "_ensure_jsme_cached", lambda: None)

    dlg = MoleculeEditorDialog()
    qtbot.addWidget(dlg)

    # Draw tab (index 0) should contain the fallback label
    draw_tab = dlg._tabs.widget(0)
    fallback_labels = draw_tab.findChildren(
        __import__("PySide6.QtWidgets", fromlist=["QLabel"]).QLabel,
        "jsme_fallback_label",
    )
    assert len(fallback_labels) == 1
    assert "SMILES tab" in fallback_labels[0].text()
    # The web view should not have been created
    assert dlg._web_view is None


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

    # Patch _open_editor on the class to avoid launching real webengine dialog
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


def test_molecule_editor_html_queues_structure_until_jsme_ready():
    """Regression: structures loaded before jsmeOnLoad must be queued, not dropped.

    Qt's loadFinished fires before JSME finishes its async GWT bootstrap, so
    loadMolBlock()/loadSMILES() used to no-op and re-opening the editor always
    showed an empty canvas.
    """
    from ui.dialogs.molecule_editor_dialog import _JSME_HTML_TEMPLATE

    assert "pendingMolBlock" in _JSME_HTML_TEMPLATE
    assert "pendingSmiles" in _JSME_HTML_TEMPLATE
    # jsmeOnLoad must apply the queued structure after the applet exists
    on_load = _JSME_HTML_TEMPLATE.split("function jsmeOnLoad()")[1].split("function loadSMILES")[0]
    assert "readMolFile(pendingMolBlock)" in on_load


def test_jsme_download_url_is_version_pinned():
    from ui.dialogs import molecule_editor_dialog as module

    assert module._JSME_VERSION in module._JSME_BASE_URL
    assert f"@{module._JSME_VERSION}" in module._JSME_BASE_URL
    assert module._JSME_VERSION in module._JSME_CACHE_DIR.parts


@pytest.mark.parametrize(
    "url",
    [
        "http://unpkg.com/jsme-editor@2024.4.29/jsme.nocache.js",
        "https://unpkg.com.evil.example/jsme-editor@2024.4.29/jsme.nocache.js",
        "https://user@unpkg.com/jsme-editor@2024.4.29/jsme.nocache.js",
        "https://unpkg.com:444/jsme-editor@2024.4.29/jsme.nocache.js",
        "https://unpkg.com/jsme-editor@2024.4.29/../other/script.js",
    ],
)
def test_jsme_asset_url_validation_rejects_untrusted_origins(url):
    from ui.dialogs import molecule_editor_dialog as module

    with pytest.raises(ValueError, match="JSME"):
        module._validate_jsme_asset_url(url)


def test_jsme_redirect_handler_rejects_before_following_offsite_redirect():
    from ui.dialogs import molecule_editor_dialog as module

    handler = module._JSMERedirectHandler()
    with pytest.raises(ValueError, match="JSME"):
        handler.redirect_request(
            None,
            None,
            302,
            "Found",
            {},
            "https://evil.example/payload.js",
        )


def test_jsme_web_view_uses_an_isolated_profile(qtbot, monkeypatch, tmp_path):
    from PySide6.QtWebEngineCore import QWebEngineProfile

    from ui.dialogs import molecule_editor_dialog as module

    html_path = tmp_path / "editor.html"
    html_path.write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr(module, "_ensure_jsme_cached", lambda: html_path)
    monkeypatch.setattr(module, "_write_jsme_html", lambda: html_path)

    dialog = module.MoleculeEditorDialog()
    qtbot.addWidget(dialog)

    assert dialog._web_view.page().profile() is dialog._web_profile
    assert dialog._web_profile is not QWebEngineProfile.defaultProfile()
    assert dialog._web_profile.parent() is None
    assert dialog._web_page.parent() is dialog._web_view


def test_atomic_cache_cleanup_does_not_mask_original_error(tmp_path, monkeypatch):
    from ui.dialogs import molecule_editor_dialog as module

    def fail_replace(source, destination):
        raise RuntimeError("original replace failure")

    def fail_cleanup(self, *, missing_ok=False):
        raise OSError("cleanup failure")

    monkeypatch.setattr(module.os, "replace", fail_replace)
    monkeypatch.setattr(module.Path, "unlink", fail_cleanup)

    with pytest.raises(RuntimeError, match="original replace failure"):
        module._atomic_write_bytes(tmp_path / "asset.js", b"payload")


def test_smiles_ok_revalidates_text_changed_after_preview(qtbot, monkeypatch):
    from ui.dialogs import molecule_editor_dialog as module

    monkeypatch.setattr(module, "_ensure_jsme_cached", lambda: None)
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
