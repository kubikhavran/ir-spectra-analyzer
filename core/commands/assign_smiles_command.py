"""AssignSMILESCommand — undoable SMILES assignment to a peak."""

from __future__ import annotations

from PySide6.QtGui import QUndoCommand

from core.peak import Peak


class AssignSMILESCommand(QUndoCommand):
    """Assigns (or re-assigns) a SMILES string to a peak (undoable)."""

    def __init__(self, peak: Peak, new_smiles: str) -> None:
        super().__init__(f"Assign structure to {peak.position:.1f} cm\u207b\u00b9")
        self._peak = peak
        self._new_smiles = new_smiles
        self._old_smiles = peak.smiles

    def redo(self) -> None:
        self._peak.smiles = self._new_smiles

    def undo(self) -> None:
        self._peak.smiles = self._old_smiles
