"""SetProjectSMILESCommand — undoable assignment of a SMILES string to the whole project."""

from __future__ import annotations

from PySide6.QtGui import QUndoCommand

from core.project import Project


class SetProjectSMILESCommand(QUndoCommand):
    """Assigns (or re-assigns) a SMILES string + MOL block at project level (undoable)."""

    def __init__(self, project: Project, new_smiles: str, new_mol_block: str = "") -> None:
        super().__init__("Set molecule structure")
        self._project = project
        self._new_smiles = new_smiles
        self._new_mol_block = new_mol_block
        self._old_smiles = project.smiles
        self._old_mol_block = project.mol_block

    def redo(self) -> None:
        self._project.smiles = self._new_smiles
        self._project.mol_block = self._new_mol_block

    def undo(self) -> None:
        self._project.smiles = self._old_smiles
        self._project.mol_block = self._old_mol_block
