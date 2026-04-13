"""
MoleculeWidget — Widget pro zobrazení a editaci 2D struktury molekuly.

Zodpovědnost:
- Zobrazení molekulové struktury z SMILES pomocí RDKit
- Graceful fallback pro prázdný SMILES nebo neplatnou strukturu
- Tlačítko "Edit Structure..." pro otevření MoleculeEditorDialog
- Emituje smiles_changed při změně struktury přes dialog
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QMouseEvent, QPixmap
from PySide6.QtWidgets import (
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from chemistry.structure_renderer import render_smiles_to_png


class _ClickableLabel(QLabel):
    """QLabel that emits a signal on double-click."""

    double_clicked = Signal()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self.double_clicked.emit()
        super().mouseDoubleClickEvent(event)


class MoleculeWidget(QWidget):
    """Displays a 2D molecular structure rendered from a SMILES string.

    Shows the molecule image when a valid SMILES is provided, or a
    placeholder text when SMILES is empty or chemically invalid.

    The "Edit Structure..." button (and double-clicking the image) opens
    MoleculeEditorDialog.  When the user accepts the dialog, smiles_changed
    is emitted with the new SMILES string.
    """

    smiles_changed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._current_smiles: str = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Image label
        self._image_label = _ClickableLabel("No structure assigned")
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setMinimumSize(200, 200)
        self._image_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._image_label.double_clicked.connect(self._open_editor)
        layout.addWidget(self._image_label)

        # Edit button
        self._edit_btn = QPushButton("Edit Structure...")
        self._edit_btn.clicked.connect(self._open_editor)
        layout.addWidget(self._edit_btn)

    # ------------------------------------------------------------------
    # Public API (backward-compatible)
    # ------------------------------------------------------------------

    def set_smiles(self, smiles: str) -> None:
        """Update the displayed molecule from a SMILES string.

        Args:
            smiles: SMILES string for the molecule. Empty string clears the display.
        """
        self._current_smiles = smiles

        if not smiles:
            self._image_label.setPixmap(QPixmap())
            self._image_label.setText("No structure assigned")
            return

        png_bytes = render_smiles_to_png(smiles, (280, 280))
        if png_bytes is None:
            self._image_label.setPixmap(QPixmap())
            self._image_label.setText("Invalid structure")
            return

        image = QImage.fromData(png_bytes)
        pixmap = QPixmap.fromImage(image)
        self._image_label.setPixmap(pixmap)
        self._image_label.setText("")

    # Expose text() for backward-compat with existing tests that call widget.text()
    def text(self) -> str:
        """Return the current text label (for compatibility with old tests)."""
        return self._image_label.text()

    # Expose pixmap() for backward-compat with existing tests
    def pixmap(self) -> QPixmap:
        """Return the current pixmap (for compatibility with old tests)."""
        return self._image_label.pixmap() or QPixmap()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _open_editor(self) -> None:
        """Open MoleculeEditorDialog and emit smiles_changed if accepted."""
        from ui.dialogs.molecule_editor_dialog import MoleculeEditorDialog  # noqa: PLC0415

        dlg = MoleculeEditorDialog(initial_smiles=self._current_smiles, parent=self)
        if dlg.exec() == MoleculeEditorDialog.DialogCode.Accepted:
            new_smiles = dlg.smiles()
            if new_smiles != self._current_smiles:
                self.smiles_changed.emit(new_smiles)
