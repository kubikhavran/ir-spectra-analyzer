"""Tests for ui.molecule_widget.MoleculeWidget."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import importlib

import pytest

from ui.molecule_widget import MoleculeWidget

_rdkit_available = importlib.util.find_spec("rdkit") is not None
requires_rdkit = pytest.mark.skipif(not _rdkit_available, reason="rdkit not installed")


def test_molecule_widget_creates(qtbot):
    widget = MoleculeWidget()
    qtbot.addWidget(widget)
    assert widget is not None


def test_set_smiles_empty_shows_placeholder(qtbot):
    widget = MoleculeWidget()
    qtbot.addWidget(widget)
    widget.set_smiles("")
    assert widget.text() == "No structure assigned"


@requires_rdkit
def test_set_smiles_invalid_shows_invalid_text(qtbot):
    widget = MoleculeWidget()
    qtbot.addWidget(widget)
    widget.set_smiles("not_a_smiles_xyz")
    assert widget.text() == "Invalid structure"


@requires_rdkit
def test_set_smiles_valid_shows_pixmap(qtbot):
    widget = MoleculeWidget()
    qtbot.addWidget(widget)
    widget.set_smiles("CCO")
    assert not widget.pixmap().isNull()
