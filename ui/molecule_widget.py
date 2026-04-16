"""
MoleculeWidget — Widget pro zobrazení a editaci 2D struktury molekuly.

Zodpovědnost:
- Zobrazení molekulové struktury pomocí _AspectSvgWidget (vector, scalable, aspect-preserved)
- Rendering přes RDKit SVG (z SMILES nebo MolBlock s koordináty)
- Graceful fallback pro prázdnou/neplatnou strukturu
- Emituje smiles_changed a mol_block_changed při změně struktury přes dialog
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, Qt, Signal
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from chemistry.structure_renderer import render_to_svg


class _AspectSvgWidget(QWidget):
    """SVG viewer that preserves aspect ratio when scaling."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._renderer = QSvgRenderer()

    def load(self, data: QByteArray) -> bool:
        ok = self._renderer.load(data)
        self.update()
        return ok

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self._renderer.isValid():
            return
        default_size = self._renderer.defaultSize()
        if default_size.isEmpty():
            return
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.white)
        w = self.width()
        h = self.height()
        ds_w = default_size.width()
        ds_h = default_size.height()
        scale = min(w / ds_w, h / ds_h)
        target_w = ds_w * scale
        target_h = ds_h * scale
        target_x = (w - target_w) / 2.0
        target_y = (h - target_h) / 2.0
        self._renderer.render(painter, QRectF(target_x, target_y, target_w, target_h))


class MoleculeWidget(QWidget):
    """Displays a 2D molecular structure as crisp SVG rendered from SMILES/MolBlock."""

    smiles_changed = Signal(str)
    mol_block_changed = Signal(str)
    structure_image_changed = Signal(bytes)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._current_smiles: str = ""
        self._current_mol_block: str = ""
        self._current_svg: str = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # SVG viewer — aspect-ratio-preserving, renders molecule as crisp vector
        self._svg_widget = _AspectSvgWidget()
        self._svg_widget.setMinimumSize(200, 160)
        self._svg_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._svg_widget.setStyleSheet("background: white; border: 1px solid #ccc;")
        self._svg_widget.mouseDoubleClickEvent = lambda _e: self._open_editor()  # type: ignore[method-assign]
        layout.addWidget(self._svg_widget)

        # Placeholder — shown when no structure is set or structure is invalid
        self._placeholder = QLabel("No structure assigned")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setMinimumSize(200, 160)
        self._placeholder.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._placeholder.setStyleSheet("background: white; border: 1px solid #ccc; color: #888;")
        layout.addWidget(self._placeholder)

        # Edit button
        self._edit_btn = QPushButton("Edit Structure...")
        self._edit_btn.clicked.connect(self._open_editor)
        layout.addWidget(self._edit_btn)

        self._show_placeholder("No structure assigned")

    def set_smiles(self, smiles: str) -> None:
        self._current_smiles = smiles
        self._current_mol_block = ""
        if not smiles:
            self._show_placeholder("No structure assigned")
            return
        svg = render_to_svg(smiles=smiles)
        if svg:
            self._display_svg(svg)
        else:
            self._show_placeholder("Invalid structure")

    def set_structure(self, smiles: str, mol_block: str = "", image_bytes: bytes = b"") -> None:
        self._current_smiles = smiles
        self._current_mol_block = mol_block
        if not smiles and not mol_block:
            self._show_placeholder("No structure assigned")
            return
        svg = render_to_svg(smiles=smiles, mol_block=mol_block)
        if svg:
            self._display_svg(svg)
        else:
            self._show_placeholder("No structure assigned")

    def text(self) -> str:
        if not self._current_svg:
            return self._placeholder.text()
        return ""

    def pixmap(self) -> QPixmap:
        if not self._current_svg:
            return QPixmap()
        renderer = QSvgRenderer(QByteArray(self._current_svg.encode()))
        if not renderer.isValid():
            return QPixmap()
        default_size = renderer.defaultSize()
        img = QImage(default_size, QImage.Format.Format_ARGB32)
        img.fill(0)
        painter = QPainter(img)
        renderer.render(painter)
        painter.end()
        return QPixmap.fromImage(img)

    def _display_svg(self, svg_str: str) -> None:
        self._current_svg = svg_str
        self._svg_widget.load(QByteArray(svg_str.encode()))
        self._svg_widget.setVisible(True)
        self._placeholder.setVisible(False)

    def _show_placeholder(self, text: str) -> None:
        self._current_svg = ""
        self._placeholder.setText(text)
        self._svg_widget.setVisible(False)
        self._placeholder.setVisible(True)

    def _open_editor(self) -> None:
        from ui.dialogs.molecule_editor_dialog import MoleculeEditorDialog  # noqa: PLC0415

        dlg = MoleculeEditorDialog(initial_smiles=self._current_smiles, parent=self)
        if dlg.exec() == MoleculeEditorDialog.DialogCode.Accepted:
            new_smiles = dlg.smiles()
            new_mol_block = dlg.mol_block()
            changed = (
                new_smiles != self._current_smiles or new_mol_block != self._current_mol_block
            )
            if changed:
                self._current_smiles = new_smiles
                self._current_mol_block = new_mol_block
                if new_smiles or new_mol_block:
                    svg = render_to_svg(smiles=new_smiles, mol_block=new_mol_block)
                    if svg:
                        self._display_svg(svg)
                    else:
                        self._show_placeholder("No structure assigned")
                else:
                    self._show_placeholder("No structure assigned")
                self.smiles_changed.emit(new_smiles)
                self.mol_block_changed.emit(new_mol_block)
                self.structure_image_changed.emit(b"")
