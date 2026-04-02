"""
MoleculeWidget — Widget pro zobrazení 2D struktury molekuly.

Zodpovědnost:
- Zobrazení molekulové struktury z SMILES pomocí RDKit
- Graceful fallback pro prázdný SMILES nebo neplatnou strukturu
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QLabel

from chemistry.structure_renderer import render_smiles_to_png


class MoleculeWidget(QLabel):
    """Displays a 2D molecular structure rendered from a SMILES string.

    Shows the molecule image when a valid SMILES is provided, or a
    placeholder text when SMILES is empty or chemically invalid.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(200, 200)
        self.setText("No structure assigned")

    def set_smiles(self, smiles: str) -> None:
        """Update the displayed molecule from a SMILES string.

        Args:
            smiles: SMILES string for the molecule. Empty string clears the display.
        """
        if not smiles:
            self.setText("No structure assigned")
            return

        png_bytes = render_smiles_to_png(smiles, (280, 280))
        if png_bytes is None:
            self.setText("Invalid structure")
            return

        image = QImage.fromData(png_bytes)
        pixmap = QPixmap.fromImage(image)
        self.setPixmap(pixmap)
