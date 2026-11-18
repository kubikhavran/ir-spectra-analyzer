"""
MoleculeCanvas — native QPainter canvas for drawing 2D chemical structures.

The canvas is a thin interactive view over :class:`MolEditorModel`: every
click or key press becomes one undoable model operation, and the widget
repaints from the model.  No web engine, no network.

Interaction summary
-------------------
* Tools: ``select``, ``erase``, ``bond_single``/``double``/``triple``/
  ``wedge``/``hash``, ``chain``, ``atom``, ``ring``, ``group``.
* Bond tools: click an atom to grow a bond, click a bond to change it, drag
  from an atom (snapped to 30° and to nearby atoms) or click empty space.
* Hover shortcuts: over an atom ``C O N S P F I H B``, ``L`` = Cl,
  ``R`` = Br, ``+``/``-`` charge, Delete removes it; over a bond ``1 2 3``,
  ``W`` wedge, ``H`` hash, Delete.
* Over an atom, Enter (or a double-click with the select tool) opens an
  inline label editor: type an element (``Na``, ``N+``), an abbreviation
  (``OMe``, ``CO2Et``, ``NHBoc``), a condensed formula (``CH2CH2OH``), SMILES
  with ``*`` or a custom group name.
* Global: Ctrl+Z, Ctrl+Y / Ctrl+Shift+Z, Ctrl+C / Ctrl+X copy or cut the
  selection (or everything), Ctrl+V pastes — the pasted part follows the
  cursor, click an atom to attach it or empty space to drop it — Ctrl+D
  duplicates, Ctrl+A selects all, Alt+H / Alt+V flip, Alt+←/→ rotate 15°,
  Space / 0 fit view, mouse wheel zoom, middle or right drag pan, right
  click opens a context menu.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

from PySide6.QtCore import QBuffer, QIODevice, QMimeData, QPoint, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPolygonF,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from chemistry.mol_editor_model import (
    BOND_LENGTH,
    ELEMENT_SYMBOLS,
    STEREO_HASH,
    STEREO_NONE,
    STEREO_WAVY,
    STEREO_WEDGE,
    MolEditorModel,
    is_element_symbol,
)
from chemistry.mol_fragments import Fragment, parse_group
from ui import theme
from ui.i18n import tr

BASE_SCALE = 32.0  # pixels per Ångström at zoom 1.0
MIN_ZOOM = 0.4
MAX_ZOOM = 3.0
SNAP_PX = 16.0
ATOM_HIT_PX = 10.0
BOND_HIT_PX = 6.0
DRAG_THRESHOLD_PX = 4.0
FIT_MARGIN_PX = 28.0

BOND_COLOR = QColor("#0F172A")
HOVER_COLOR = QColor(37, 99, 235, 41)  # rgba(37, 99, 235, 0.16)
INVALID_FILL = QColor("#FEE2E2")
INVALID_STROKE = QColor("#DC2626")
ELEMENT_COLORS: dict[str, str] = {
    "C": "#0F172A",
    "O": "#DC2626",
    "N": "#2563EB",
    "S": "#D97706",
    "F": "#16A34A",
    "Cl": "#16A34A",
    "Br": "#9A3412",
    "I": "#7C3AED",
    "P": "#EA580C",
}
DEFAULT_ELEMENT_COLOR = "#334155"
STEREO_LABEL_COLOR = QColor("#7C3AED")
ATOM_NUMBER_COLOR = QColor("#64748B")

# Ink for the on-screen canvas in the dark theme. Exports (PNG for reports,
# clipboard images) are always drawn with the light ink on white paper.
DARK_BOND_COLOR = QColor("#E2E8F0")
DARK_ELEMENT_COLORS: dict[str, str] = {
    "C": "#E2E8F0",
    "O": "#F87171",
    "N": "#60A5FA",
    "S": "#FBBF24",
    "F": "#4ADE80",
    "Cl": "#4ADE80",
    "Br": "#FB923C",
    "I": "#C4B5FD",
    "P": "#FB923C",
}
DARK_DEFAULT_ELEMENT_COLOR = "#CBD5E1"
DARK_STEREO_LABEL_COLOR = QColor("#C4B5FD")
DARK_ATOM_NUMBER_COLOR = QColor("#94A3B8")
DARK_INVALID_FILL = QColor("#4C1D1D")
DARK_INVALID_STROKE = QColor("#F87171")

#: True while the structure is painted on screen in the dark theme.
_dark_ink = False


def _use_dark_ink(on_screen: bool) -> None:
    global _dark_ink
    _dark_ink = on_screen and theme.is_dark()


def _ink(light: QColor, dark: QColor) -> QColor:
    return dark if _dark_ink else light


def _paper() -> QColor:
    """Background the structure sits on: the canvas on screen, white in exports."""
    return QColor(theme.SURFACE) if _dark_ink else QColor("white")


#: Clipboard format carrying a copied part of a structure with its attachment point.
FRAGMENT_MIME = "application/x-ir-spectra-fragment+json"
MOLFILE_MIME = "chemical/x-mdl-molfile"

TOOLS: tuple[str, ...] = (
    "select",
    "erase",
    "bond_single",
    "bond_double",
    "bond_triple",
    "bond_wedge",
    "bond_hash",
    "bond_wavy",
    "bond_bold",
    "chain",
    "atom",
    "ring",
    "group",
    "attach",  # mark where a custom group attaches (a * atom)
)
_BOND_TOOLS: dict[str, tuple[int, str]] = {
    "bond_single": (1, STEREO_NONE),
    "bond_double": (2, STEREO_NONE),
    "bond_triple": (3, STEREO_NONE),
    "bond_wedge": (1, STEREO_WEDGE),
    "bond_hash": (1, STEREO_HASH),
    "bond_wavy": (1, STEREO_WAVY),
    "bond_bold": (1, STEREO_NONE),  # drawn thick: front edge of a chair / perspective
}
# Keys that switch tools when the pointer is not over an atom or bond.
_TOOL_KEYS: dict[int, str] = {
    Qt.Key.Key_V: "select",
    Qt.Key.Key_1: "bond_single",
    Qt.Key.Key_2: "bond_double",
    Qt.Key.Key_3: "bond_triple",
    Qt.Key.Key_W: "bond_wedge",
    Qt.Key.Key_H: "bond_hash",
    Qt.Key.Key_U: "bond_wavy",
    Qt.Key.Key_B: "bond_bold",
    Qt.Key.Key_C: "chain",
}
_HOVER_ELEMENT_KEYS: dict[str, str] = {
    "C": "C",
    "O": "O",
    "N": "N",
    "S": "S",
    "P": "P",
    "F": "F",
    "I": "I",
    "H": "H",
    "B": "B",
    "L": "Cl",
    "R": "Br",
}
_H_FIRST_ELEMENTS = frozenset({"O", "S", "Se", "F", "Cl", "Br", "I"})
_SUBSCRIPT_DIGITS = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")
_SUPERSCRIPT_DIGITS = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")


def element_color(symbol: str) -> QColor:
    if _dark_ink:
        return QColor(DARK_ELEMENT_COLORS.get(symbol, DARK_DEFAULT_ELEMENT_COLOR))
    return QColor(ELEMENT_COLORS.get(symbol, DEFAULT_ELEMENT_COLOR))


def screen_element_color(symbol: str) -> QColor:
    """Element colour for widgets on screen (palette buttons, template icons)."""
    if theme.is_dark():
        return QColor(DARK_ELEMENT_COLORS.get(symbol, DARK_DEFAULT_ELEMENT_COLOR))
    return QColor(ELEMENT_COLORS.get(symbol, DEFAULT_ELEMENT_COLOR))


def screen_bond_color() -> QColor:
    """Bond colour for widgets on screen in the active theme."""
    return QColor(DARK_BOND_COLOR if theme.is_dark() else BOND_COLOR)


def _charge_text(charge: int) -> str:
    if charge == 0:
        return ""
    sign = "+" if charge > 0 else "−"
    return sign if abs(charge) == 1 else f"{abs(charge)}{sign}"


@dataclass
class _AtomLabel:
    symbol: str
    hydrogens: int
    charge: int
    h_side: str  # preferred side for the H: "right", "left", "up" or "down"
    isotope: int = 0
    radicals: int = 0

    @property
    def h_left(self) -> bool:
        return self.h_side == "left"


@dataclass
class _LabelLayout:
    """Where every glyph of an atom label goes, and the boxes it covers."""

    texts: list[tuple[str, QPointF, bool]]  # (text, baseline origin, small font)
    boxes: list[QRectF]
    dots: list[QPointF]
    dot_radius: float


_H_SIDES = {"right": 0.0, "left": 180.0, "down": -90.0, "up": 90.0}


def _angle_gap(angle: float, others: list[float]) -> float:
    """Smallest angular distance (degrees) from *angle* to any of *others*."""
    if not others:
        return 180.0
    return min(abs((angle - o + 180.0) % 360.0 - 180.0) for o in others)


def _pick_side(options: dict[str, float], others: list[float], threshold: float) -> str:
    """First option (in order) whose direction is clear of bonds, else the clearest."""
    for name, angle in options.items():
        if _angle_gap(angle, others) >= threshold:
            return name
    return max(options, key=lambda name: _angle_gap(options[name], others))


@dataclass
class _Drag:
    button: Qt.MouseButton
    start: QPointF
    atom: int | None
    bond: int | None
    kind: str  # "pan", "move", "rubber", "draw"
    moved: bool = False
    last: QPointF = field(default_factory=QPointF)
    move_atoms: list[int] = field(default_factory=list)
    free_length: bool = False  # Shift held: the bond follows the cursor distance
    free_angle: bool = False  # Alt held: no angle snapping


class MoleculeCanvas(QWidget):
    """Interactive 2D structure editor canvas."""

    structure_changed = Signal()
    tool_changed = Signal(str)
    hint_changed = Signal(str)
    #: A :class:`Fragment` the user wants to keep as a custom group.
    save_group_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("molecule_canvas")
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(360, 280)
        self.setAutoFillBackground(False)

        self._model = MolEditorModel()
        self._tool = "bond_single"
        self._atom_symbol = "C"
        self._ring_type = "benzene"
        self._group_key = "-OH"

        self._zoom = 1.0
        self._origin = QPointF(0.0, 0.0)
        self._needs_fit = True

        self._hover_atom: int | None = None
        self._hover_bond: int | None = None
        self._cursor: QPointF | None = None
        self._selection: set[int] = set()
        self._last_atom: int | None = None
        self._drag: _Drag | None = None
        self._hint = ""

        self._placement: Fragment | None = None
        self._placement_sticky = False
        self._custom_groups: dict[str, str] = {}
        self._show_atom_numbers = False
        self._show_stereo_labels = False
        self._label_atom: int | None = None
        self._label_editor = QLineEdit(self)
        self._label_editor.setObjectName("molecule_label_editor")
        self._label_editor.hide()
        self._label_editor.setPlaceholderText("OMe, CO2Et, N+ …")
        self._label_editor.returnPressed.connect(self._commit_label_editor)
        self._label_editor.installEventFilter(self)

        self._cache_revision = -1
        self._invalid: set[int] = set()
        self._labels: dict[int, _AtomLabel] = {}
        self._stereo_atoms: dict[int, str] = {}
        self._stereo_bonds: dict[int, str] = {}
        self._update_hint()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def model(self) -> MolEditorModel:
        return self._model

    def set_model(self, model: MolEditorModel) -> None:
        self._model = model
        self._reset_interaction()
        self._needs_fit = True
        self.fit_to_view()
        self.structure_changed.emit()

    def load_smiles(self, smiles: str) -> bool:
        """Replace the drawing with *smiles* (fresh history). Returns success."""
        model = MolEditorModel()
        if not model.load_smiles(smiles, record_undo=False):
            return False
        self.set_model(model)
        return True

    def load_mol_block(self, mol_block: str) -> bool:
        """Replace the drawing with a MOL block (keeps its 2D layout)."""
        model = MolEditorModel()
        if not model.load_mol_block(mol_block, record_undo=False):
            return False
        self.set_model(model)
        return True

    def replace_smiles(self, smiles: str) -> bool:
        """Replace the drawing with *smiles* as one undoable step."""
        if not self._model.load_smiles(smiles, record_undo=True):
            return False
        self._needs_fit = True
        self._after_edit()
        self.fit_to_view()
        return True

    def replace_mol_block(self, mol_block: str) -> bool:
        """Replace the drawing with a MOL block as one undoable step."""
        if not self._model.load_mol_block(mol_block, record_undo=True):
            return False
        self._after_edit()
        self.fit_to_view()
        return True

    def to_smiles(self) -> str:
        return self._model.to_smiles()

    def to_mol_block(self) -> str:
        return self._model.to_mol_block()

    def tool(self) -> str:
        return self._tool

    def set_tool(self, tool: str) -> None:
        if tool not in TOOLS:
            raise ValueError(f"Unknown tool: {tool!r}")
        # Picking any tool ends repeated placing of a group or salt.
        self.cancel_placement()
        if tool == self._tool:
            return
        self._tool = tool
        self._drag = None
        self._update_hint()
        self.update()
        self.tool_changed.emit(tool)

    def atom_symbol(self) -> str:
        return self._atom_symbol

    def set_atom_symbol(self, symbol: str) -> None:
        """Pick the element for the atom tool; applies to selected atoms too."""
        self._atom_symbol = symbol
        if self._selection:
            with self._model.compound():
                for idx in sorted(self._selection):
                    self._model.set_atom_symbol(idx, symbol)
            self._after_edit(keep_selection=True)
        was_atom = self._tool == "atom"
        self.set_tool("atom")
        self._update_hint()
        if was_atom:
            self.update()
            self.tool_changed.emit("atom")

    def ring_type(self) -> str:
        return self._ring_type

    def set_ring_type(self, ring_type: str) -> None:
        self._ring_type = ring_type
        was_ring = self._tool == "ring"
        self.set_tool("ring")
        self._update_hint()
        if was_ring:
            self.update()
            self.tool_changed.emit("ring")

    def group_key(self) -> str:
        return self._group_key

    def set_group(self, group_key: str) -> None:
        self._group_key = group_key
        was_group = self._tool == "group"
        self.set_tool("group")
        self._update_hint()
        if was_group:
            self.update()
            self.tool_changed.emit("group")

    def adjust_charge(self, delta: int) -> bool:
        """Change the charge of the selected / hovered / last edited atom."""
        targets = sorted(self._selection)
        if not targets:
            for candidate in (self._hover_atom, self._last_atom):
                if candidate is not None and candidate < self._model.atom_count:
                    targets = [candidate]
                    break
        if not targets:
            return False
        with self._model.compound():
            for idx in targets:
                self._model.set_atom_charge(idx, delta)
        self._after_edit(keep_selection=True)
        return True

    def undo(self) -> bool:
        if not self._model.undo():
            return False
        self._after_edit()
        return True

    def redo(self) -> bool:
        if not self._model.redo():
            return False
        self._after_edit()
        return True

    def clean_2d(self) -> bool:
        if not self._model.clean_2d():
            return False
        self._after_edit()
        self.fit_to_view()
        return True

    def clear(self) -> None:
        self._model.clear()
        self._after_edit()

    def copy_smiles(self) -> str:
        smiles = self._model.to_smiles()
        QGuiApplication.clipboard().setText(smiles)
        return smiles

    def paste_text(self, text: str) -> bool:
        if not self._model.paste_text(text):
            return False
        self._after_edit()
        self.fit_to_view()
        return True

    def selected_atoms(self) -> set[int]:
        return set(self._selection)

    def select_atoms(self, atoms: set[int] | list[int]) -> None:
        self._selection = {i for i in atoms if 0 <= i < self._model.atom_count}
        self.update()

    def select_all(self) -> None:
        self.select_atoms(list(range(self._model.atom_count)))

    # -- clipboard & placement -----------------------------------------

    def _target_atoms(self) -> list[int]:
        """Selected atoms, or every atom when nothing is selected."""
        if self._selection:
            return sorted(self._selection)
        return list(range(self._model.atom_count))

    def copy_selection(self) -> bool:
        """Copy the selection (or the whole drawing) to the clipboard.

        The clipboard gets plain SMILES (for other programs), a MOL block and
        the fragment with its attachment point, so pasting it here can attach
        it to another atom.
        """
        atoms = self._target_atoms()
        if not atoms:
            return False
        fragment = self._model.extract_fragment(atoms)
        mime = QMimeData()
        mime.setText(fragment.smiles() if self._selection else self._model.to_smiles())
        mime.setData(MOLFILE_MIME, fragment.mol_block().encode("utf-8"))
        mime.setData(FRAGMENT_MIME, json.dumps(fragment.to_json()).encode("utf-8"))
        QGuiApplication.clipboard().setMimeData(mime)
        return True

    def cut_selection(self) -> bool:
        if not self._selection or not self.copy_selection():
            return False
        self._model.delete_atoms(self._selection)
        self._after_edit()
        return True

    def duplicate_selection(self) -> list[int]:
        """Copy the selection next to itself and select the copy."""
        atoms = self._target_atoms()
        if not atoms:
            return []
        fragment = self._model.extract_fragment(atoms)
        xs = [self._model.atom_position(i)[0] for i in atoms]
        ys = [self._model.atom_position(i)[1] for i in atoms]
        width = max(xs) - min(xs)
        position = (
            sum(xs) / len(xs) + width + 2 * BOND_LENGTH,
            sum(ys) / len(ys),
        )
        created = self._model.insert_fragment(fragment, position=position)
        self._after_edit()
        self.select_atoms(created)
        return created

    def fragment_from_clipboard(self) -> Fragment | None:
        mime = QGuiApplication.clipboard().mimeData()
        if mime is None:
            return None
        if mime.hasFormat(FRAGMENT_MIME):
            try:
                data = json.loads(bytes(mime.data(FRAGMENT_MIME).data()).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                data = None
            if isinstance(data, dict):
                fragment = Fragment.from_json(data)
                if fragment is not None:
                    return fragment
        if mime.hasFormat(MOLFILE_MIME):
            fragment = self._fragment_from_text(
                bytes(mime.data(MOLFILE_MIME).data()).decode("utf-8", "replace")
            )
            if fragment is not None:
                return fragment
        return self._fragment_from_text(mime.text())

    def _fragment_from_text(self, text: str) -> Fragment | None:
        if not (text or "").strip():
            return None
        if "M  END" in text or "V2000" in text or "V3000" in text:
            model = MolEditorModel()
            if not model.load_mol_block(text, record_undo=False):
                return None
            whole = model.extract_fragment(range(model.atom_count))
            whole.attach = None
            return whole
        group = parse_group(text.strip(), self._custom_groups)
        if group is not None:
            return group
        model = MolEditorModel()
        if model.load_smiles(text.strip(), record_undo=False):
            fragment = model.extract_fragment(range(model.atom_count))
            fragment.attach = None
            return fragment
        return None

    def paste_from_clipboard(self) -> bool:
        """Start placing whatever is on the clipboard (see :meth:`begin_placement`)."""
        fragment = self.fragment_from_clipboard()
        if fragment is None:
            self._set_hint(tr("The clipboard holds no structure"))
            return False
        self.begin_placement(fragment)
        return True

    def begin_placement(self, fragment: Fragment, label: str = "", *, sticky: bool = False) -> None:
        """Let *fragment* follow the cursor until the user clicks.

        Clicking an atom bonds the fragment's attachment atom to it; pressing
        on an atom and dragging sets the direction of that bond; clicking empty
        space drops it there as a separate molecule (salt, solvent …).  With
        *sticky* the fragment stays on the cursor so it can be placed again
        and again.  Esc or a right click ends placing.
        """
        if label:
            fragment.label = label
        self._placement = fragment
        self._placement_sticky = sticky
        self._drag = None
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._update_hint()
        self.update()

    def cancel_placement(self) -> None:
        if self._placement is None:
            return
        self._placement = None
        self.unsetCursor()
        self._update_hint()
        self.update()

    def placement(self) -> Fragment | None:
        return self._placement

    def placement_is_sticky(self) -> bool:
        return self._placement is not None and self._placement_sticky

    def place_fragment(
        self,
        *,
        target_atom: int | None = None,
        position: tuple[float, float] | None = None,
        angle: float | None = None,
    ) -> list[int]:
        """Drop the fragment being placed; returns the new atom indices.

        *angle* (degrees) is the direction of the bond from *target_atom*.
        """
        fragment = self._placement
        if fragment is None:
            return []
        if target_atom is not None and fragment.attach is None:
            # A whole molecule (e.g. a salt) is dropped next to the atom instead.
            position = self._model.atom_position(target_atom)
            target_atom = None
            position = (position[0] + 2 * BOND_LENGTH, position[1])
        created = self._model.insert_fragment(
            fragment, target_atom_idx=target_atom, position=position, angle=angle
        )
        if not self._placement_sticky:
            self._placement = None
            self.unsetCursor()
        self._after_edit()
        self._update_hint()
        return created

    # -- custom groups, labels and atom properties ---------------------

    def set_custom_groups(self, groups: dict[str, str]) -> None:
        self._custom_groups = dict(groups)

    def custom_groups(self) -> dict[str, str]:
        return dict(self._custom_groups)

    def apply_label(self, atom: int, text: str) -> bool:
        if not self._model.apply_label(atom, text, self._custom_groups):
            self._set_hint(tr("Unknown label: {text}").format(text=text))
            return False
        self._last_atom = atom if atom < self._model.atom_count else None
        self._after_edit()
        return True

    def edit_atom_label(self, atom: int) -> None:
        """Open the inline editor over *atom*."""
        if not 0 <= atom < self._model.atom_count:
            return
        self._label_atom = atom
        center = self._atom_screen(atom)
        editor = self._label_editor
        editor.setText(self._model.atom_symbol(atom))
        editor.selectAll()
        editor.setStyleSheet("")
        editor.resize(120, editor.sizeHint().height())
        x = int(min(max(4, center.x() - 20), self.width() - editor.width() - 4))
        y = int(min(max(4, center.y() - editor.height() / 2), self.height() - editor.height() - 4))
        editor.move(x, y)
        editor.show()
        editor.raise_()
        editor.setFocus(Qt.FocusReason.OtherFocusReason)
        self._set_hint(
            tr("Type an element, group (OMe, CO2Et, NHBoc) or SMILES with *; Enter applies")
        )

    def _commit_label_editor(self) -> None:
        atom = self._label_atom
        text = self._label_editor.text().strip()
        if atom is None or not text:
            self._close_label_editor()
            return
        if self.apply_label(atom, text):
            self._close_label_editor()
        else:
            self._label_editor.setStyleSheet(f"border: 2px solid {INVALID_STROKE.name()};")

    def _close_label_editor(self) -> None:
        self._label_atom = None
        self._label_editor.hide()
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        self._update_hint()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802, ANN001
        if watched is self._label_editor and event.type() == event.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self._close_label_editor()
                return True
        if watched is self._label_editor and event.type() == event.Type.FocusOut:
            if self._label_editor.isVisible():
                self._close_label_editor()
        return bool(super().eventFilter(watched, event))

    def open_atom_properties(self, atom: int) -> bool:
        if not 0 <= atom < self._model.atom_count:
            return False
        dialog = AtomPropertiesDialog(self._model, atom, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        values = dialog.values()
        if not is_element_symbol(str(values["symbol"])):
            return False
        if values.get("charge") == dialog.initial_charge:
            values["charge"] = None
        self._model.set_atom_properties(atom, **values)  # type: ignore[arg-type]
        self._last_atom = atom
        self._after_edit()
        return True

    # -- transformations -----------------------------------------------

    def rotate_selection(self, angle_deg: float) -> None:
        atoms = self._target_atoms()
        if atoms:
            self._model.rotate_atoms(atoms, angle_deg)
            self._after_edit(keep_selection=True)

    def flip_selection(self, *, horizontal: bool = True) -> None:
        atoms = self._target_atoms()
        if atoms:
            self._model.flip_atoms(atoms, horizontal=horizontal)
            self._after_edit(keep_selection=True)

    def add_explicit_hydrogens(self) -> int:
        added = self._model.add_explicit_hydrogens(sorted(self._selection) or None)
        if added:
            self._after_edit()
        return added

    def remove_explicit_hydrogens(self) -> int:
        removed = self._model.remove_explicit_hydrogens()
        if removed:
            self._after_edit()
        return removed

    def request_save_group(self) -> bool:
        """Ask the host to store the selection as a reusable custom group."""
        if not self._selection:
            return False
        self.save_group_requested.emit(self._model.extract_fragment(sorted(self._selection)))
        return True

    # -- context menu ---------------------------------------------------

    def build_context_menu(self, point: QPointF) -> QMenu:
        return _build_context_menu(self, point)

    def show_context_menu(self, point: QPointF) -> None:
        menu = self.build_context_menu(point)
        menu.exec(self.mapToGlobal(QPoint(int(point.x()), int(point.y()))))

    # -- display options -----------------------------------------------

    def show_atom_numbers(self) -> bool:
        return self._show_atom_numbers

    def set_show_atom_numbers(self, show: bool) -> None:  # noqa: FBT001
        self._show_atom_numbers = bool(show)
        self.update()

    def show_stereo_labels(self) -> bool:
        return self._show_stereo_labels

    def set_show_stereo_labels(self, show: bool) -> None:  # noqa: FBT001
        self._show_stereo_labels = bool(show)
        self._cache_revision = -1
        self.update()

    def zoom(self) -> float:
        return self._zoom

    def set_zoom(self, zoom: float, anchor: QPointF | None = None) -> None:
        zoom = max(MIN_ZOOM, min(MAX_ZOOM, zoom))
        if anchor is None:
            anchor = QPointF(self.width() / 2, self.height() / 2)
        world = self._to_world(anchor)
        self._zoom = zoom
        screen = self._to_screen(*world)
        self._origin += anchor - screen
        self._needs_fit = False
        self.update()

    def zoom_in(self) -> None:
        self.set_zoom(self._zoom * 1.2)

    def zoom_out(self) -> None:
        self.set_zoom(self._zoom / 1.2)

    def fit_to_view(self) -> None:
        """Centre the structure and zoom so it fills the canvas (max 1.5×)."""
        if self.width() <= 0 or self.height() <= 0:
            self._needs_fit = True
            return
        zoom, origin = self._fit_transform(self.width(), self.height(), max_zoom=1.5)
        self._zoom = zoom
        self._origin = origin
        self._needs_fit = False
        self.update()

    def render_to_png_bytes(self, width: int = 400, height: int = 300) -> bytes:
        """Render the structure (no hover/selection) to a tightly cropped PNG.

        The molecule is scaled to fit ``width`` × ``height`` without being
        distorted, and the empty border is cut off, so the image is shaped
        like the molecule.  ``b""`` when empty.
        """
        if self._model.is_empty():
            return b""
        # Pass 1 measures how big the drawing (labels included) comes out;
        # pass 2 scales it so the cropped image fills the requested box.
        bounds = self._model.bounds() or (0.0, 0.0, 0.0, 0.0)
        span_w = (bounds[2] - bounds[0] + 1.5 * BOND_LENGTH) * BASE_SCALE
        span_h = (bounds[3] - bounds[1] + 1.5 * BOND_LENGTH) * BASE_SCALE
        zoom = min(width / span_w, height / span_h)
        image = QImage()
        for _ in range(4):
            canvas = QImage(QSize(width * 2, height * 2), QImage.Format.Format_ARGB32)
            canvas.fill(Qt.GlobalColor.transparent)
            origin = self._export_origin(zoom, canvas.width(), canvas.height())
            painter = QPainter(canvas)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            self._paint_structure(painter, zoom, origin, interactive=False)
            painter.end()
            image = crop_to_content(canvas, margin=2)
            fill = min(
                (width - 4) / max(image.width() - 4, 1), (height - 4) / max(image.height() - 4, 1)
            )
            if 0.97 <= fill <= 1.0:
                break
            zoom = max(0.05, zoom * fill * 0.995)
        flat = QImage(image.size(), QImage.Format.Format_ARGB32)
        flat.fill(QColor("white"))
        painter = QPainter(flat)
        painter.drawImage(0, 0, image)
        painter.end()
        image = flat
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")  # type: ignore[call-overload, unused-ignore]
        return bytes(buffer.data().data())

    def _export_origin(self, zoom: float, width: int, height: int) -> QPointF:
        """Origin that centres the structure in a ``width`` × ``height`` image."""
        bounds = self._model.bounds()
        scale = self._scale(zoom)
        if bounds is None:
            return QPointF(width / 2, height / 2)
        cx = (bounds[0] + bounds[2]) / 2
        cy = (bounds[1] + bounds[3]) / 2
        return QPointF(width / 2 - cx * scale, height / 2 + cy * scale)

    def hint(self) -> str:
        return self._hint

    # ------------------------------------------------------------------
    # Coordinates & hit testing
    # ------------------------------------------------------------------

    def _scale(self, zoom: float | None = None) -> float:
        return BASE_SCALE * (self._zoom if zoom is None else zoom)

    def _to_screen(
        self, x: float, y: float, zoom: float | None = None, origin: QPointF | None = None
    ) -> QPointF:
        scale = self._scale(zoom)
        o = self._origin if origin is None else origin
        return QPointF(o.x() + x * scale, o.y() - y * scale)

    def _to_world(self, point: QPointF) -> tuple[float, float]:
        scale = self._scale()
        return ((point.x() - self._origin.x()) / scale, (self._origin.y() - point.y()) / scale)

    def _fit_transform(
        self, width: float, height: float, *, max_zoom: float
    ) -> tuple[float, QPointF]:
        bounds = self._model.bounds()
        if bounds is None:
            return 1.0, QPointF(width / 2, height / 2)
        min_x, min_y, max_x, max_y = bounds
        pad = 0.6 * BOND_LENGTH  # room for labels
        bw = (max_x - min_x) + 2 * pad
        bh = (max_y - min_y) + 2 * pad
        avail_w = max(width - 2 * FIT_MARGIN_PX, 40.0)
        avail_h = max(height - 2 * FIT_MARGIN_PX, 40.0)
        zoom = min(avail_w / (bw * BASE_SCALE), avail_h / (bh * BASE_SCALE), max_zoom)
        zoom = max(MIN_ZOOM, min(MAX_ZOOM, zoom))
        scale = BASE_SCALE * zoom
        cx = (min_x + max_x) / 2
        cy = (min_y + max_y) / 2
        origin = QPointF(width / 2 - cx * scale, height / 2 + cy * scale)
        return zoom, origin

    def _atom_screen(self, idx: int) -> QPointF:
        return self._to_screen(*self._model.atom_position(idx))

    def _atom_at(self, point: QPointF, *, exclude: int | None = None) -> int | None:
        best: int | None = None
        best_d = ATOM_HIT_PX
        for idx in range(self._model.atom_count):
            if idx == exclude:
                continue
            p = self._atom_screen(idx)
            d = math.hypot(p.x() - point.x(), p.y() - point.y())
            if d <= best_d:
                best, best_d = idx, d
        return best

    def _bond_at(self, point: QPointF) -> int | None:
        best: int | None = None
        best_d = BOND_HIT_PX
        for idx in range(self._model.bond_count):
            a, b = self._model.bond_atoms(idx)
            d = _segment_distance(point, self._atom_screen(a), self._atom_screen(b))
            if d <= best_d:
                best, best_d = idx, d
        return best

    def _snap_atom(self, point: QPointF, *, exclude: int | None = None) -> int | None:
        best: int | None = None
        best_d = SNAP_PX
        for idx in range(self._model.atom_count):
            if idx == exclude:
                continue
            p = self._atom_screen(idx)
            d = math.hypot(p.x() - point.x(), p.y() - point.y())
            if d <= best_d:
                best, best_d = idx, d
        return best

    def _snapped_angle(
        self,
        start: tuple[float, float],
        point: QPointF,
        atom: int | None = None,
        *,
        free: bool = False,
    ) -> float:
        """Drawing angle (degrees): 30° steps, or parallel to a nearby bond /
        the axial–equatorial directions of a chair; Alt draws at any angle."""
        wx, wy = self._to_world(point)
        angle = math.degrees(math.atan2(wy - start[1], wx - start[0]))
        if free:
            return angle
        best = round(angle / 30.0) * 30.0
        best_gap = abs(angle - best)
        for candidate in self._snap_directions(atom):
            gap = abs((angle - candidate + 180.0) % 360.0 - 180.0)
            if gap < 9.0 and gap < best_gap:
                best, best_gap = angle - ((angle - candidate + 180.0) % 360.0 - 180.0), gap
        return best

    def _snap_directions(self, atom: int | None) -> list[float]:
        """Directions of bonds in the same molecule (both ways) and chair axes."""
        if atom is None or not 0 <= atom < self._model.atom_count:
            return []
        model = self._model
        directions: list[float] = []
        chair = model.chair_directions(atom)
        if chair is not None:
            directions += [math.degrees(a) for a in chair]
        fragment = set(model.fragment_atoms(atom))
        for bond in range(model.bond_count):
            a, b = model.bond_atoms(bond)
            if a in fragment:
                (ax, ay), (bx, by) = model.atom_position(a), model.atom_position(b)
                d = math.degrees(math.atan2(by - ay, bx - ax))
                directions += [d, d + 180.0]
        return directions

    # ------------------------------------------------------------------
    # Model bookkeeping
    # ------------------------------------------------------------------

    def _reset_interaction(self) -> None:
        self._hover_atom = None
        self._hover_bond = None
        self._selection.clear()
        self._last_atom = None
        self._drag = None
        self._cache_revision = -1

    def _after_edit(self, *, keep_selection: bool = False) -> None:
        count = self._model.atom_count
        if not keep_selection:
            self._selection.clear()
        self._selection = {i for i in self._selection if i < count}
        self._hover_atom = None
        self._hover_bond = None
        if self._last_atom is not None and self._last_atom >= count:
            self._last_atom = None
        if self._cursor is not None:
            self._update_hover(self._cursor)
        self.update()
        self.structure_changed.emit()

    def _refresh_cache(self) -> None:
        if self._cache_revision == self._model.revision:
            return
        model = self._model
        self._invalid = model.invalid_atom_indices()
        labels: dict[int, _AtomLabel] = {}
        for idx in range(model.atom_count):
            symbol = model.atom_symbol(idx)
            charge = model.atom_charge(idx)
            degree = model.atom_degree(idx)
            isotope = model.atom_isotope(idx)
            radicals = model.atom_radicals(idx)
            if symbol == "C" and charge == 0 and degree > 0 and not isotope and not radicals:
                continue
            hydrogens = model.implicit_hydrogens(idx)
            ax, ay = model.atom_position(idx)
            bond_angles = [
                math.degrees(math.atan2(ny - ay, nx - ax))
                for nx, ny in (model.atom_position(n) for n in model.atom_neighbors(idx))
            ]
            if degree == 0:
                h_side = "left" if symbol in _H_FIRST_ELEMENTS else "right"
            else:
                h_side = _pick_side(_H_SIDES, bond_angles, 75.0)
            labels[idx] = _AtomLabel(symbol, hydrogens, charge, h_side, isotope, radicals)
        self._labels = labels
        if self._show_stereo_labels:
            self._stereo_atoms, self._stereo_bonds = model.stereo_labels()
        else:
            self._stereo_atoms, self._stereo_bonds = {}, {}
        self._cache_revision = model.revision

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        del event
        if self._needs_fit and self.width() > 0:
            self.fit_to_view()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.fillRect(self.rect(), QColor(theme.SURFACE))
        if self._model.is_empty() and self._drag is None:
            painter.setPen(QColor(theme.TEXT_FAINT))
            painter.drawText(
                self.rect().adjusted(24, 24, -24, -24),
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                tr("Click to draw a bond, pick a ring or paste SMILES (Ctrl+V)"),
            )
        self._paint_highlights(painter)
        self._paint_structure(painter, self._zoom, self._origin, interactive=True)
        self._paint_ghosts(painter)
        if self.hasFocus():
            pen = QPen(QColor(theme.ACCENT))
            pen.setWidthF(1.0)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5))
        painter.end()

    def _font_px(self, zoom: float) -> float:
        return max(7.0, 0.27 * BOND_LENGTH * self._scale(zoom))

    def _paint_highlights(self, painter: QPainter) -> None:
        font_px = self._font_px(self._zoom)
        painter.setPen(Qt.PenStyle.NoPen)
        if self._selection:
            fill = QColor(theme.ACCENT)
            fill.setAlpha(56)
            painter.setBrush(fill)
            radius = 0.5 * font_px + 4
            for idx in self._selection:
                if idx < self._model.atom_count:
                    painter.drawEllipse(self._atom_screen(idx), radius, radius)
        if self._drag is not None and self._drag.kind == "rubber" and self._cursor is not None:
            fill = QColor(theme.ACCENT)
            fill.setAlpha(24)
            pen = QPen(QColor(theme.ACCENT))
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(fill)
            painter.drawRect(QRectF(self._drag.start, self._cursor).normalized())
            painter.setPen(Qt.PenStyle.NoPen)
        if self._hover_atom is not None and self._hover_atom < self._model.atom_count:
            painter.setBrush(HOVER_COLOR)
            radius = 0.5 * font_px + 5
            painter.drawEllipse(self._atom_screen(self._hover_atom), radius, radius)
        elif self._hover_bond is not None and self._hover_bond < self._model.bond_count:
            a, b = self._model.bond_atoms(self._hover_bond)
            pen = QPen(HOVER_COLOR)
            pen.setWidthF(max(10.0, 0.3 * BOND_LENGTH * self._scale()))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(self._atom_screen(a), self._atom_screen(b))

    def _paint_structure(
        self, painter: QPainter, zoom: float, origin: QPointF, *, interactive: bool
    ) -> None:
        self._refresh_cache()
        _use_dark_ink(interactive)
        model = self._model
        if model.is_empty():
            return
        scale = self._scale(zoom)
        bond_px = BOND_LENGTH * scale
        font_px = self._font_px(zoom)
        positions = [
            self._to_screen(*model.atom_position(i), zoom=zoom, origin=origin)
            for i in range(model.atom_count)
        ]

        # Invalid valence markers sit underneath bonds and labels.
        if self._invalid:
            pen = QPen(_ink(INVALID_STROKE, DARK_INVALID_STROKE))
            pen.setWidthF(1.3)
            painter.setPen(pen)
            painter.setBrush(_ink(INVALID_FILL, DARK_INVALID_FILL))
            radius = 0.55 * font_px + 3
            for idx in self._invalid:
                if idx < len(positions):
                    painter.drawEllipse(positions[idx], radius, radius)

        width = max(1.1, min(3.2, 0.035 * bond_px))
        pen = QPen(_ink(BOND_COLOR, DARK_BOND_COLOR))
        pen.setWidthF(width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        label_radius = 0.62 * font_px
        bold = [b for b in range(model.bond_count) if model.bond_bold(b)]
        # Thin bonds first; bold (front) bonds last, each over a white band
        # that cuts the thin bonds passing behind it — the usual depth cue of
        # chair and perspective drawings.
        for bond in [b for b in range(model.bond_count) if b not in set(bold)] + bold:
            a, b = model.bond_atoms(bond)
            p1, p2 = positions[a], positions[b]
            if bond in bold:
                gap = QPen(_paper())
                gap.setWidthF(max(3.0, 0.1 * bond_px) + max(4.0, 0.12 * bond_px))
                gap.setCapStyle(Qt.PenCapStyle.FlatCap)
                painter.setPen(gap)
                inner = 0.22 * bond_px
                painter.drawLine(*_shorten(p1, p2, inner, inner))
            r1 = label_radius if a in self._labels else 0.0
            r2 = label_radius if b in self._labels else 0.0
            q1, q2 = _shorten(p1, p2, r1, r2)
            self._paint_bond(painter, pen, bond, q1, q2, bond_px, zoom, origin)

        font, small = self._label_fonts(zoom)
        for idx, label in self._labels.items():
            bonds = [positions[n] for n in model.atom_neighbors(idx)]
            self._paint_label(painter, positions[idx], label, font, small, bonds)
        if interactive:
            self._paint_annotations(painter, positions, small)

    def _paint_annotations(self, painter: QPainter, positions: list[QPointF], small: QFont) -> None:
        """Atom numbers and R/S, E/Z labels (view options)."""
        offset = 0.42 * self._font_px(self._zoom) + 4
        if self._show_atom_numbers:
            font = QFont(small)
            font.setWeight(QFont.Weight.Normal)
            painter.setFont(font)
            painter.setPen(_ink(ATOM_NUMBER_COLOR, DARK_ATOM_NUMBER_COLOR))
            metrics = QFontMetricsF(font)
            for idx, pos in enumerate(positions):
                text = str(idx + 1)
                # Bottom-left: top-right is where charges go.
                painter.drawText(
                    QPointF(
                        pos.x() - offset * 0.55 - metrics.horizontalAdvance(text),
                        pos.y() + offset * 0.55 + metrics.ascent() * 0.5,
                    ),
                    text,
                )
        if self._stereo_atoms or self._stereo_bonds:
            font = QFont(small)
            font.setItalic(True)
            font.setWeight(QFont.Weight.Bold)
            painter.setFont(font)
            painter.setPen(_ink(STEREO_LABEL_COLOR, DARK_STEREO_LABEL_COLOR))
            for idx, code in self._stereo_atoms.items():
                if idx < len(positions):
                    pos = positions[idx]
                    painter.drawText(
                        QPointF(pos.x() + offset * 0.5, pos.y() + offset * 1.2), f"({code})"
                    )
            for bond, code in self._stereo_bonds.items():
                if bond < self._model.bond_count:
                    a, b = self._model.bond_atoms(bond)
                    pa, pb = positions[a], positions[b]
                    mid = (pa + pb) / 2
                    dx, dy = pb.x() - pa.x(), pb.y() - pa.y()
                    length = math.hypot(dx, dy) or 1.0
                    # Put the label beside the bond, on the side away from the double line
                    # (which sits on the side with more substituents).
                    nx, ny = dy / length, -dx / length
                    total = 0.0
                    for atom, other in ((a, b), (b, a)):
                        for nbr in self._model.atom_neighbors(atom):
                            if nbr != other:
                                q = positions[nbr] - positions[atom]
                                total += q.x() * nx + q.y() * ny
                    if total > 0:
                        nx, ny = -nx, -ny
                    painter.drawText(
                        QPointF(mid.x() + nx * offset * 1.4 - 8, mid.y() + ny * offset * 1.4 + 4),
                        f"({code})",
                    )

    def _paint_bond(
        self,
        painter: QPainter,
        pen: QPen,
        bond: int,
        p1: QPointF,
        p2: QPointF,
        bond_px: float,
        zoom: float,
        origin: QPointF,
    ) -> None:
        model = self._model
        order = model.bond_order(bond)
        stereo = model.bond_stereo(bond)
        dx, dy = p2.x() - p1.x(), p2.y() - p1.y()
        length = math.hypot(dx, dy)
        if length < 1e-6:
            return
        nx, ny = -dy / length, dx / length  # unit normal (screen)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        if stereo == STEREO_WEDGE:
            half = 0.11 * bond_px
            polygon = QPolygonF(
                [
                    p1,
                    QPointF(p2.x() + nx * half, p2.y() + ny * half),
                    QPointF(p2.x() - nx * half, p2.y() - ny * half),
                ]
            )
            painter.setBrush(QBrush(_ink(BOND_COLOR, DARK_BOND_COLOR)))
            thin = QPen(pen)
            thin.setWidthF(0.6)
            painter.setPen(thin)
            painter.drawPolygon(polygon)
            return
        if stereo == STEREO_HASH:
            half = 0.11 * bond_px
            steps = max(4, int(length / max(3.0, 0.11 * bond_px)))
            thin = QPen(pen)
            thin.setWidthF(max(1.0, pen.widthF() * 0.8))
            painter.setPen(thin)
            for k in range(1, steps + 1):
                t = k / steps
                cx = p1.x() + dx * t
                cy = p1.y() + dy * t
                h = max(0.6, half * t)
                painter.drawLine(
                    QPointF(cx + nx * h, cy + ny * h), QPointF(cx - nx * h, cy - ny * h)
                )
            return
        if stereo == STEREO_WAVY:
            cycles = max(3, int(round(length / max(6.0, 0.25 * bond_px))))
            amp = min(3.8, max(2.0, 0.08 * bond_px))
            steps = cycles * 8
            path = QPainterPath(p1)
            for k in range(1, steps + 1):
                t = k / steps
                wave = amp * math.sin(2.0 * math.pi * cycles * t)
                path.lineTo(
                    p1.x() + dx * t + nx * wave,
                    p1.y() + dy * t + ny * wave,
                )
            thin = QPen(pen)
            thin.setWidthF(max(1.0, pen.widthF() * 0.9))
            painter.setPen(thin)
            painter.drawPath(path)
            return

        offset = 0.18 * bond_px
        if order == 1:
            if model.bond_bold(bond):
                thick = QPen(pen)
                thick.setWidthF(max(3.0, 0.1 * bond_px))
                thick.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(thick)
            painter.drawLine(p1, p2)
            return
        if order == 3:
            painter.drawLine(p1, p2)
            trim = 0.06
            for sign in (1.0, -1.0):
                painter.drawLine(
                    *_offset_line(p1, p2, nx * sign * offset, ny * sign * offset, trim)
                )
            return

        # Double bond: inside the ring, centred for terminal bonds, else on
        # the side with more substituents.
        a, b = model.bond_atoms(bond)
        ring_center = model.bond_ring_center(bond)
        side = 0.0
        if ring_center is not None:
            c = self._to_screen(*ring_center, zoom=zoom, origin=origin)
            mid = QPointF((p1.x() + p2.x()) / 2, (p1.y() + p2.y()) / 2)
            side = 1.0 if (c.x() - mid.x()) * nx + (c.y() - mid.y()) * ny > 0 else -1.0
        elif (
            model.atom_degree(a) > 1
            and model.atom_degree(b) > 1
            and a not in self._labels
            and b not in self._labels
        ):
            total = 0.0
            for atom, other in ((a, b), (b, a)):
                origin_pt = self._to_screen(*model.atom_position(atom), zoom=zoom, origin=origin)
                for nbr in model.atom_neighbors(atom):
                    if nbr == other:
                        continue
                    q = self._to_screen(*model.atom_position(nbr), zoom=zoom, origin=origin)
                    total += (q.x() - origin_pt.x()) * nx + (q.y() - origin_pt.y()) * ny
            side = 1.0 if total >= 0 else -1.0
        if side == 0.0:
            half = offset / 2
            painter.drawLine(*_offset_line(p1, p2, nx * half, ny * half, 0.0))
            painter.drawLine(*_offset_line(p1, p2, -nx * half, -ny * half, 0.0))
            return
        painter.drawLine(p1, p2)
        painter.drawLine(*_offset_line(p1, p2, nx * side * offset, ny * side * offset, 0.14))

    def _layout_label(
        self,
        center: QPointF,
        label: _AtomLabel,
        fm: QFontMetricsF,
        sm: QFontMetricsF,
        bonds: list[QPointF] | None = None,
    ) -> _LabelLayout:
        """Place symbol, H, H count, charge, isotope and radical dots.

        *bonds* are the screen positions of the bonded neighbours; the H and
        the charge go where they do not touch any of those bond lines.
        """
        cap = fm.capHeight()
        small_cap = sm.capHeight()
        sym_w = fm.horizontalAdvance(label.symbol)
        baseline = center.y() + cap / 2
        sym_left = center.x() - sym_w / 2
        texts: list[tuple[str, QPointF, bool]] = [
            (label.symbol, QPointF(sym_left, baseline), False)
        ]
        boxes = [QRectF(sym_left, center.y() - cap / 2, sym_w, cap)]
        clear = 0.62 * self._font_px(self._zoom)
        segments = [
            (
                center
                + (p - center)
                * (clear / max(math.dist((p.x(), p.y()), (center.x(), center.y())), 1e-6)),
                p,
            )
            for p in (bonds or [])
        ]

        def free(box: QRectF) -> bool:
            grown = box.adjusted(-1.0, -1.0, 1.0, 1.0)
            return not any(_rect_hits_segment(grown, a, b) for a, b in segments)

        left, right = sym_left, sym_left + sym_w
        iso_w = sm.horizontalAdvance(str(label.isotope)) if label.isotope else 0.0
        if label.hydrogens:
            count = str(label.hydrogens) if label.hydrogens > 1 else ""
            h_w = fm.horizontalAdvance("H")
            c_w = sm.horizontalAdvance(count) if count else 0.0
            drop = cap * 0.45

            def h_box(side: str) -> tuple[float, float, QRectF]:
                if side == "right":
                    hx, hb = right, baseline
                elif side == "left":
                    hx, hb = left - iso_w - h_w - c_w, baseline
                else:
                    hx = center.x() - (h_w + c_w) / 2
                    hb = baseline + (cap * 1.35 if side == "down" else -cap * 1.35)
                return hx, hb, QRectF(hx, hb - cap, h_w + c_w, cap + (drop if count else 0.0))

            order = [label.h_side] + [side for side in _H_SIDES if side != label.h_side]
            side = next((o for o in order if free(h_box(o)[2])), label.h_side)
            hx, hb, box = h_box(side)
            texts.append(("H", QPointF(hx, hb), False))
            boxes.append(box)
            if count:
                texts.append((count, QPointF(hx + h_w, hb + drop), True))
            if side == "right":
                right += h_w + c_w
            elif side == "left":
                left = hx

        if label.isotope:
            iso = str(label.isotope)
            ix = sym_left - iso_w - 0.5  # mass number sits right before the symbol
            ib = center.y() - cap * 0.15
            texts.append((iso, QPointF(ix, ib), True))
            boxes.append(QRectF(ix, ib - small_cap, iso_w, small_cap))
            left = min(left, ix)

        charge = _charge_text(label.charge)
        if charge:
            c_w = sm.horizontalAdvance(charge)

            def charge_box(corner: str) -> QRectF:
                top = corner.startswith("t")
                cb = center.y() - cap * 0.15 if top else center.y() + cap * 0.5 + small_cap * 0.9
                cx = right + 0.5 if corner.endswith("r") else left - c_w - 0.5
                return QRectF(cx, cb - small_cap, c_w, small_cap)

            def clear_of_text(box: QRectF) -> bool:
                return free(box) and not any(box.intersects(other) for other in boxes[1:])

            corner = next(
                (c for c in ("tr", "br", "tl", "bl") if clear_of_text(charge_box(c))), None
            )
            if corner is not None:
                box = charge_box(corner)
            else:
                # Crowded atom (e.g. a quaternary N⁺): walk round it and use the
                # first spot between the bonds.
                radius = max(sym_w, cap) * 0.5 + max(c_w, small_cap) * 0.9 + 2.0
                box = charge_box("tr")
                for step in range(24):
                    angle = math.radians(45.0 + step * 15.0)
                    cx = center.x() + radius * math.cos(angle)
                    cy = center.y() - radius * math.sin(angle)
                    trial = QRectF(cx - c_w / 2, cy - small_cap / 2, c_w, small_cap)
                    if clear_of_text(trial):
                        box = trial
                        break
            texts.append((charge, QPointF(box.left(), box.bottom()), True))
            boxes.append(box)

        dots: list[QPointF] = []
        dot_r = max(1.4, cap * 0.12)
        if label.radicals:
            for dy in (-cap * 0.95, cap * 0.95):
                candidate = [
                    QPointF(
                        center.x() + (k - (label.radicals - 1) / 2) * dot_r * 3, center.y() + dy
                    )
                    for k in range(label.radicals)
                ]
                dot_boxes = [
                    QRectF(d.x() - dot_r, d.y() - dot_r, 2 * dot_r, 2 * dot_r) for d in candidate
                ]
                if all(free(b) and not any(b.intersects(o) for o in boxes) for b in dot_boxes):
                    break
            dots = candidate
            boxes.extend(dot_boxes)
        return _LabelLayout(texts, boxes, dots, dot_r)

    def _label_boxes(
        self, zoom: float | None = None, origin: QPointF | None = None
    ) -> dict[int, list[QRectF]]:
        """Screen boxes covered by each atom label (used for layout checks)."""
        self._refresh_cache()
        zoom = self._zoom if zoom is None else zoom
        font, small = self._label_fonts(zoom)
        fm, sm = QFontMetricsF(font), QFontMetricsF(small)
        result = {}
        positions = [
            self._to_screen(*self._model.atom_position(i), zoom=zoom, origin=origin)
            for i in range(self._model.atom_count)
        ]
        for idx, label in self._labels.items():
            bonds = [positions[n] for n in self._model.atom_neighbors(idx)]
            result[idx] = self._layout_label(positions[idx], label, fm, sm, bonds).boxes
        return result

    def _label_fonts(self, zoom: float) -> tuple[QFont, QFont]:
        font_px = self._font_px(zoom)
        font = QFont(self.font())
        font.setPixelSize(round(font_px))
        font.setWeight(QFont.Weight.DemiBold)
        small = QFont(font)
        small.setPixelSize(max(6, round(font_px * 0.68)))
        return font, small

    def _paint_label(
        self,
        painter: QPainter,
        center: QPointF,
        label: _AtomLabel,
        font: QFont,
        small: QFont,
        bonds: list[QPointF] | None = None,
    ) -> None:
        fm = QFontMetricsF(font)
        sm = QFontMetricsF(small)
        layout = self._layout_label(center, label, fm, sm, bonds)
        color = element_color(label.symbol)

        # A soft halo keeps crossing lines away from the glyphs.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_paper())
        for box in layout.boxes:
            painter.drawRoundedRect(box.adjusted(-1.5, -1.5, 1.5, 1.5), 2.5, 2.5)

        painter.setPen(color)
        for text, origin, is_small in layout.texts:
            painter.setFont(small if is_small else font)
            painter.drawText(origin, text)
        if layout.dots:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            for dot in layout.dots:
                painter.drawEllipse(dot, layout.dot_radius, layout.dot_radius)

    def _ghost_pen(self, alpha: int = 170) -> QPen:
        color = QColor(theme.ACCENT)
        color.setAlpha(alpha)
        pen = QPen(color)
        pen.setWidthF(max(1.4, 0.04 * BOND_LENGTH * self._scale()))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        return pen

    def _paint_ghosts(self, painter: QPainter) -> None:
        cursor = self._cursor
        if cursor is None:
            return
        drag = self._drag
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if self._placement is not None:
            self._paint_placement_ghost(painter, cursor)
            return
        if drag is not None and drag.moved and drag.kind == "move" and len(drag.move_atoms) == 1:
            target = self._merge_target(drag.move_atoms[0])
            if target is not None:
                painter.setBrush(HOVER_COLOR)
                pen = QPen(QColor(theme.ACCENT))
                pen.setWidthF(1.5)
                painter.setPen(pen)
                painter.drawEllipse(self._atom_screen(target), SNAP_PX * 0.8, SNAP_PX * 0.8)
            return
        if drag is not None and drag.moved and drag.kind == "draw" and self._tool == "group":
            if drag.atom is not None:
                angle = math.radians(self._drag_angle(drag, cursor))
                ax, ay = self._model.atom_position(drag.atom)
                end = (ax + BOND_LENGTH * math.cos(angle), ay + BOND_LENGTH * math.sin(angle))
                painter.setPen(self._ghost_pen())
                painter.drawLine(self._atom_screen(drag.atom), self._to_screen(*end))
                font = QFont(self.font())
                font.setPixelSize(13)
                font.setWeight(QFont.Weight.DemiBold)
                painter.setFont(font)
                painter.setPen(QColor(theme.ACCENT_DARK))
                tip = self._to_screen(*end)
                painter.drawText(QPointF(tip.x() + 6, tip.y() - 6), self._group_key)
            return
        if drag is not None and drag.moved and drag.kind == "draw":
            if self._tool == "chain":
                points = self._chain_preview(drag, cursor)
                if len(points) > 1:
                    painter.setPen(self._ghost_pen())
                    screen = [self._to_screen(*p) for p in points]
                    painter.drawPolyline(QPolygonF(screen))
                    count = len(points) - 1 + (0 if drag.atom is not None else 1)
                    text = "C" + str(count).translate(_SUBSCRIPT_DIGITS)
                    font = QFont(self.font())
                    font.setPixelSize(13)
                    font.setWeight(QFont.Weight.DemiBold)
                    painter.setFont(font)
                    painter.setPen(QColor(theme.ACCENT_DARK))
                    painter.drawText(QPointF(cursor.x() + 12, cursor.y() - 10), text)
                return
            start, end, target = self._bond_preview(drag, cursor)
            painter.setPen(self._ghost_pen())
            painter.drawLine(self._to_screen(*start), self._to_screen(*end))
            if drag.free_length and target is None:
                factor = math.hypot(end[0] - start[0], end[1] - start[1]) / BOND_LENGTH
                font = QFont(self.font())
                font.setPixelSize(12)
                painter.setFont(font)
                painter.setPen(QColor(theme.ACCENT_DARK))
                painter.drawText(QPointF(cursor.x() + 12, cursor.y() - 10), f"×{factor:.2f}")
            if target is not None:
                painter.setBrush(HOVER_COLOR)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(self._to_screen(*end), SNAP_PX * 0.7, SNAP_PX * 0.7)
            return
        if drag is None and self._tool == "ring":
            try:
                coords = self._model.ring_template_coordinates(
                    self._ring_type,
                    center=None
                    if self._hover_atom is not None or self._hover_bond is not None
                    else self._to_world(cursor),
                    target_atom_idx=self._hover_atom,
                    target_bond_idx=self._hover_bond if self._hover_atom is None else None,
                )
            except Exception:  # noqa: BLE001
                return
            painter.setPen(self._ghost_pen(120))
            for a, b, order in MolEditorModel.ring_template_bonds(self._ring_type):
                pa = self._to_screen(*coords[a])
                pb = self._to_screen(*coords[b])
                painter.drawLine(pa, pb)
                if order == 2:
                    center = QPointF(
                        sum(self._to_screen(*c).x() for c in coords) / len(coords),
                        sum(self._to_screen(*c).y() for c in coords) / len(coords),
                    )
                    inner_a = pa + (center - pa) * 0.22
                    inner_b = pb + (center - pb) * 0.22
                    painter.drawLine(inner_a, inner_b)
        elif (
            drag is None
            and self._tool == "atom"
            and self._hover_atom is None
            and self._hover_bond is None
        ):
            font = QFont(self.font())
            font.setPixelSize(round(self._font_px(self._zoom)))
            font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(font)
            color = element_color(self._atom_symbol)
            color.setAlpha(120)
            painter.setPen(color)
            painter.drawText(
                QRectF(cursor.x() - 20, cursor.y() - 12, 40, 24),
                Qt.AlignmentFlag.AlignCenter,
                self._atom_symbol,
            )

    def _drag_angle(self, drag: _Drag, point: QPointF) -> float:
        """Snapped direction (degrees) from the pressed atom towards *point*."""
        assert drag.atom is not None
        start = self._model.atom_position(drag.atom)
        return self._snapped_angle(start, point, drag.atom, free=drag.free_angle)

    def _placement_coordinates(self, cursor: QPointF) -> list[tuple[float, float]]:
        fragment = self._placement
        if fragment is None:
            return []
        drag = self._drag
        if (
            drag is not None
            and drag.kind == "place"
            and drag.moved
            and drag.atom is not None
            and fragment.attach is not None
        ):
            return self._model.fragment_coordinates(
                fragment, target_atom_idx=drag.atom, angle=self._drag_angle(drag, cursor)
            )
        if self._hover_atom is not None and fragment.attach is not None:
            return self._model.fragment_coordinates(fragment, target_atom_idx=self._hover_atom)
        return self._model.fragment_coordinates(fragment, position=self._to_world(cursor))

    def _paint_placement_ghost(self, painter: QPainter, cursor: QPointF) -> None:
        fragment = self._placement
        if fragment is None:
            return
        coords = self._placement_coordinates(cursor)
        if not coords:
            return
        points = [self._to_screen(*c) for c in coords]
        painter.setPen(self._ghost_pen(150))
        for bond in fragment.mol.GetBonds():
            pa = points[bond.GetBeginAtomIdx()]
            pb = points[bond.GetEndAtomIdx()]
            painter.drawLine(pa, pb)
            if bond.GetBondTypeAsDouble() >= 2:
                dx, dy = pb.x() - pa.x(), pb.y() - pa.y()
                length = math.hypot(dx, dy) or 1.0
                off = QPointF(-dy / length * 4, dx / length * 4)
                painter.drawLine(pa + off, pb + off)
        drag = self._drag
        anchor_atom = (
            drag.atom
            if drag is not None and drag.kind == "place" and drag.moved
            else self._hover_atom
        )
        if anchor_atom is not None and fragment.attach is not None:
            painter.drawLine(self._atom_screen(anchor_atom), points[fragment.attach])
        font = QFont(self.font())
        font.setPixelSize(max(9, round(self._font_px(self._zoom) * 0.85)))
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        for atom in fragment.mol.GetAtoms():
            symbol = atom.GetSymbol()
            if symbol == "C" and atom.GetDegree() > 0 and not atom.GetFormalCharge():
                continue
            color = element_color(symbol)
            color.setAlpha(170)
            painter.setPen(color)
            text = symbol + _charge_text(atom.GetFormalCharge())
            p = points[atom.GetIdx()]
            painter.drawText(
                QRectF(p.x() - 18, p.y() - 10, 36, 20), Qt.AlignmentFlag.AlignCenter, text
            )

    def _merge_target(self, atom: int) -> int | None:
        """Atom that *atom* would be fused with if dropped now."""
        if not 0 <= atom < self._model.atom_count:
            return None
        target = self._snap_atom(self._atom_screen(atom), exclude=atom)
        if target is None or target in self._model.atom_neighbors(atom):
            return None
        return target

    def _bond_preview(
        self, drag: _Drag, cursor: QPointF
    ) -> tuple[tuple[float, float], tuple[float, float], int | None]:
        start = (
            self._model.atom_position(drag.atom)
            if drag.atom is not None
            else self._to_world(drag.start)
        )
        target = self._snap_atom(cursor, exclude=drag.atom)
        if target is not None:
            return start, self._model.atom_position(target), target
        angle = math.radians(self._snapped_angle(start, cursor, drag.atom, free=drag.free_angle))
        length = self._drag_length(drag, start, cursor)
        end = (start[0] + length * math.cos(angle), start[1] + length * math.sin(angle))
        return start, end, None

    def _drag_length(self, drag: _Drag, start: tuple[float, float], cursor: QPointF) -> float:
        """Standard bond length, or with Shift the cursor distance in ¼-bond steps."""
        if not drag.free_length:
            return BOND_LENGTH
        wx, wy = self._to_world(cursor)
        distance = math.hypot(wx - start[0], wy - start[1])
        step = 0.25 * BOND_LENGTH
        return max(0.5 * BOND_LENGTH, min(6 * BOND_LENGTH, round(distance / step) * step))

    def _chain_preview(self, drag: _Drag, cursor: QPointF) -> list[tuple[float, float]]:
        sx, sy = (
            self._model.atom_position(drag.atom)
            if drag.atom is not None
            else self._to_world(drag.start)
        )
        ex, ey = self._to_world(cursor)
        angle = math.radians(self._snapped_angle((sx, sy), cursor, drag.atom, free=drag.free_angle))
        dist = math.hypot(ex - sx, ey - sy)
        ex, ey = sx + dist * math.cos(angle), sy + dist * math.sin(angle)
        return self._model.chain_coordinates(sx, sy, ex, ey, drag.atom)

    # ------------------------------------------------------------------
    # Hover & hints
    # ------------------------------------------------------------------

    def _update_hover(self, point: QPointF) -> None:
        atom = self._atom_at(point)
        bond = None if atom is not None else self._bond_at(point)
        if atom != self._hover_atom or bond != self._hover_bond:
            self._hover_atom = atom
            self._hover_bond = bond
            self._update_hint()

    def _set_hint(self, hint: str) -> None:
        if hint != self._hint:
            self._hint = hint
            self.hint_changed.emit(hint)

    def _update_hint(self) -> None:
        if self._placement is not None:
            name = self._placement.label or self._placement.smiles()
            if self._placement.attach is None:
                hint = tr("Click to place {name}; Esc cancels").format(name=name)
            else:
                hint = tr(
                    "Click an atom to attach {name} (drag from it to choose the direction), "
                    "or empty space to place it; Esc ends"
                ).format(name=name)
            self._set_hint(hint)
            return
        if self._hover_atom is not None:
            hint = tr(
                "Atom: type C, O, N, S, P, F, I, H, B, L (Cl), R (Br); +/− charge; "
                "Enter = label or group; Del removes"
            )
        elif self._hover_bond is not None:
            hint = tr("Bond: 1/2/3 order, W wedge, H hash, U wavy, B bold, +/− length, Del removes")
        else:
            hints = {
                "select": tr("Drag atoms to move them, drag empty space to select"),
                "erase": tr("Click an atom or bond to delete it"),
                "bond_single": tr(
                    "Click or drag to draw bonds (Shift = longer, Alt = any angle); "
                    "click a bond: single → double → triple → wedge → reversed wedge"
                ),
                "bond_double": tr("Click or drag to draw double bonds"),
                "bond_triple": tr("Click or drag to draw triple bonds"),
                "bond_wedge": tr("Wedge bond (towards viewer); click again to flip"),
                "bond_hash": tr("Hashed bond (away from viewer); click again to flip"),
                "bond_wavy": tr("Wavy bond (unspecified or racemic stereochemistry)"),
                "bond_bold": tr(
                    "Bold bond (front edge of a chair or perspective drawing); "
                    "click a bond to make it bold or thin"
                ),
                "chain": tr("Drag to draw a carbon chain"),
                "atom": tr("Click to place {symbol} or replace an atom").format(
                    symbol=self._atom_symbol
                ),
                "ring": tr("Click empty space, an atom or a bond to add the ring"),
                "group": tr(
                    "Click an atom to attach {group}; drag from it to choose the direction"
                ).format(group=self._group_key),
                "attach": tr(
                    "Click the atom the group attaches through (adds *); click again to remove"
                ),
            }
            hint = hints.get(self._tool, "")
        if hint != self._hint:
            self._hint = hint
            self.hint_changed.emit(hint)

    # ------------------------------------------------------------------
    # Mouse
    # ------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        point = event.position()
        self._cursor = point
        button = event.button()
        if self._placement is not None and button == Qt.MouseButton.LeftButton:
            self._drag = _Drag(button, point, self._atom_at(point), None, "place", last=point)
            return
        if self._placement is not None and button == Qt.MouseButton.RightButton:
            self.cancel_placement()
            return
        if button in (Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton):
            self._drag = _Drag(button, point, None, None, "pan", last=point)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if button != Qt.MouseButton.LeftButton:
            return
        atom = self._atom_at(point)
        bond = None if atom is not None else self._bond_at(point)
        kind = "draw"
        move_atoms: list[int] = []
        if self._tool == "select":
            shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            if atom is not None or bond is not None:
                kind = "move"
                touched = [atom] if atom is not None else list(self._model.bond_atoms(bond or 0))
                if shift:
                    self._selection ^= set(touched)
                elif not set(touched) <= self._selection:
                    self._selection = set(touched)
                move_atoms = sorted(self._selection) if self._selection else touched
            else:
                kind = "rubber"
                if not shift:
                    self._selection.clear()
        self._drag = _Drag(button, point, atom, bond, kind, last=point, move_atoms=move_atoms)
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        point = event.position()
        self._cursor = point
        drag = self._drag
        if drag is not None and drag.kind == "place":
            drag.free_angle = bool(event.modifiers() & Qt.KeyboardModifier.AltModifier)
            if drag.atom is not None and not drag.moved:
                delta = point - drag.start
                drag.moved = math.hypot(delta.x(), delta.y()) >= DRAG_THRESHOLD_PX
            if not drag.moved:
                self._update_hover(point)
            drag.last = point
            self.update()
            return
        if drag is None:
            self._update_hover(point)
            self.update()
            return
        drag.free_length = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        drag.free_angle = bool(event.modifiers() & Qt.KeyboardModifier.AltModifier)
        if not drag.moved:
            delta = point - drag.start
            if math.hypot(delta.x(), delta.y()) < DRAG_THRESHOLD_PX:
                return
            drag.moved = True
            if drag.kind == "move":
                self._model.checkpoint()
        if drag.kind == "pan":
            self._origin += point - drag.last
            self._needs_fit = False
        elif drag.kind == "move":
            scale = self._scale()
            dx = (point.x() - drag.last.x()) / scale
            dy = -(point.y() - drag.last.y()) / scale
            self._model.move_fragment(drag.move_atoms, dx, dy)
        drag.last = point
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        drag = self._drag
        if drag is None or event.button() != drag.button:
            return
        self._drag = None
        point = event.position()
        self._cursor = point
        if drag.kind == "draw":
            drag.free_length = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            drag.free_angle = bool(event.modifiers() & Qt.KeyboardModifier.AltModifier)
        if drag.kind == "place":
            drag.free_angle = bool(event.modifiers() & Qt.KeyboardModifier.AltModifier)
            if drag.atom is not None and drag.moved:
                # Pressed on an atom and dragged: the bond goes where it was pulled.
                self.place_fragment(target_atom=drag.atom, angle=self._drag_angle(drag, point))
                return
            atom = drag.atom if drag.atom is not None else self._atom_at(point)
            if atom is not None:
                self.place_fragment(target_atom=atom)
            else:
                self.place_fragment(position=self._to_world(point))
            return
        self.unsetCursor()
        if drag.kind == "pan":
            if not drag.moved and drag.button == Qt.MouseButton.RightButton:
                self.show_context_menu(point)
            self.update()
            return
        if drag.kind == "move":
            if drag.moved:
                if len(drag.move_atoms) == 1:
                    target = self._merge_target(drag.move_atoms[0])
                    if target is not None:
                        self._model.merge_atoms(target, drag.move_atoms[0], record_undo=False)
                        self._selection.clear()
                self._after_edit(keep_selection=True)
            else:
                self.update()
            return
        if drag.kind == "rubber":
            if drag.moved:
                rect = QRectF(drag.start, point).normalized()
                for idx in range(self._model.atom_count):
                    if rect.contains(self._atom_screen(idx)):
                        self._selection.add(idx)
            self.update()
            return
        if drag.moved:
            self._finish_drag(drag, point)
        else:
            self._click(drag.atom, drag.bond, drag.start)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._tool == "select" and self._placement is None:
            atom = self._atom_at(event.position())
            if atom is not None:
                self.edit_atom_label(atom)
                return
            bond = self._bond_at(event.position())
            if bond is not None:
                self._selection = set(self._model.fragment_atoms(self._model.bond_atoms(bond)[0]))
                self.update()
                return
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        steps = event.angleDelta().y() / 120.0
        if steps:
            self.set_zoom(self._zoom * (1.15**steps), event.position())
        event.accept()

    def leaveEvent(self, event) -> None:  # noqa: N802, ANN001
        self._cursor = None
        self._hover_atom = None
        self._hover_bond = None
        self._update_hint()
        self.update()
        super().leaveEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        old = event.oldSize()
        if self._needs_fit or old.width() <= 0:
            self._needs_fit = True
        else:
            # Keep the drawing centred while the dialog is resized.
            self._origin += QPointF(
                (event.size().width() - old.width()) / 2, (event.size().height() - old.height()) / 2
            )
        super().resizeEvent(event)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _click(self, atom: int | None, bond: int | None, point: QPointF) -> None:
        model = self._model
        tool = self._tool
        world = self._to_world(point)
        if tool == "select":
            return
        if tool == "erase":
            if atom is not None:
                model.delete_atom(atom)
            elif bond is not None:
                model.delete_bond(bond)
            else:
                return
        elif tool == "bond_bold":
            if bond is not None:
                model.set_bond_bold(bond, not model.bond_bold(bond))
            else:
                with model.compound():
                    start = atom if atom is not None else model.add_free_atom(*world)
                    self._last_atom = model.sprout_atom(start)
                    new_bond = model.find_bond(start, self._last_atom)
                    if new_bond is not None:
                        model.set_bond_bold(new_bond, True)
        elif tool in _BOND_TOOLS:
            order, stereo = _BOND_TOOLS[tool]
            if atom is not None:
                self._last_atom = model.sprout_atom(atom, "C", order, stereo)
            elif bond is not None:
                if tool == "bond_single":
                    # single → double → triple → wedge → wedge reversed → single
                    model.cycle_bond(bond)
                else:
                    a, b = model.bond_atoms(bond)
                    model.add_or_update_bond(a, b, order, stereo, cycle_on_existing=False)
            else:
                with model.compound():
                    start = model.add_free_atom(*world)
                    self._last_atom = model.sprout_atom(start, "C", order, stereo)
        elif tool == "chain":
            if atom is not None:
                self._last_atom = model.sprout_atom(atom)
            else:
                self._last_atom = model.add_free_atom(*world)
        elif tool == "atom":
            if atom is not None:
                model.set_atom_symbol(atom, self._atom_symbol)
                self._last_atom = atom
            elif bond is not None:
                return
            else:
                self._last_atom = model.add_free_atom(*world, symbol=self._atom_symbol)
        elif tool == "ring":
            if bond is not None:
                model.add_ring_template(self._ring_type, target_bond_idx=bond)
            elif atom is not None:
                model.add_ring_template(self._ring_type, target_atom_idx=atom)
            else:
                model.add_ring_template(self._ring_type, center=world)
        elif tool == "group":
            if atom is None:
                return
            model.attach_functional_group(atom, self._group_key)
        elif tool == "attach":
            if atom is None:
                return
            model.toggle_attachment_point(atom)
        self._after_edit()

    def _finish_drag(self, drag: _Drag, point: QPointF) -> None:
        model = self._model
        tool = self._tool
        if tool == "chain":
            points = self._chain_preview(drag, point)
            sx, sy = points[0]
            ex, ey = points[-1]
            created = model.add_chain(sx, sy, ex, ey, start_atom_idx=drag.atom)
            self._last_atom = created[-1] if created else None
            self._after_edit()
            return
        if tool in _BOND_TOOLS or tool == "atom":
            if tool == "atom":
                order, stereo, symbol = 1, STEREO_NONE, self._atom_symbol
            else:
                order, stereo = _BOND_TOOLS[tool]
                symbol = "C"
            start, end, target = self._bond_preview(drag, point)
            with model.compound():
                origin_atom = drag.atom if drag.atom is not None else model.add_free_atom(*start)
                if target is not None and target != origin_atom:
                    model.add_or_update_bond(
                        origin_atom, target, order, stereo, cycle_on_existing=False
                    )
                    self._last_atom = target
                else:
                    angle = math.degrees(math.atan2(end[1] - start[1], end[0] - start[0]))
                    length = math.hypot(end[0] - start[0], end[1] - start[1])
                    self._last_atom = model.sprout_atom(
                        origin_atom,
                        symbol,
                        order,
                        stereo,
                        preferred_angle=angle,
                        length=length if drag.free_length else None,
                    )
                if tool == "bond_bold" and self._last_atom is not None:
                    new_bond = model.find_bond(origin_atom, self._last_atom)
                    if new_bond is not None:
                        model.set_bond_bold(new_bond, True)
            self._after_edit()
            return
        if tool == "group" and drag.atom is not None:
            # Drag from an atom: the group's bond points the way it was pulled.
            model.attach_functional_group(
                drag.atom, self._group_key, angle=self._drag_angle(drag, point)
            )
            self._last_atom = drag.atom
            self._after_edit()
            return
        # Other tools treat a drag like a click where the press happened.
        self._click(drag.atom, drag.bond, drag.start)

    # ------------------------------------------------------------------
    # Keyboard
    # ------------------------------------------------------------------

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key = event.key()
        mods = event.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        alt = bool(mods & Qt.KeyboardModifier.AltModifier)
        if ctrl:
            if key == Qt.Key.Key_Z:
                self.redo() if shift else self.undo()
            elif key == Qt.Key.Key_Y:
                self.redo()
            elif key == Qt.Key.Key_C:
                self.copy_selection()
            elif key == Qt.Key.Key_X:
                self.cut_selection()
            elif key == Qt.Key.Key_V:
                self.paste_from_clipboard()
            elif key == Qt.Key.Key_D:
                self.duplicate_selection()
            elif key == Qt.Key.Key_A:
                self.select_all()
            else:
                super().keyPressEvent(event)
                return
            event.accept()
            return
        if alt and key in (Qt.Key.Key_H, Qt.Key.Key_V, Qt.Key.Key_Left, Qt.Key.Key_Right):
            if key == Qt.Key.Key_H:
                self.flip_selection(horizontal=True)
            elif key == Qt.Key.Key_V:
                self.flip_selection(horizontal=False)
            else:
                self.rotate_selection(15.0 if key == Qt.Key.Key_Left else -15.0)
            event.accept()
            return
        if key in (Qt.Key.Key_Space, Qt.Key.Key_0):
            self.fit_to_view()
            event.accept()
            return
        if key == Qt.Key.Key_Escape:
            self._drag = None
            if self._placement is not None:
                self.cancel_placement()
            else:
                self._selection.clear()
                self.update()
            event.accept()
            return
        if (
            key in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and self._hover_atom is not None
            and self._hover_atom < self._model.atom_count
        ):
            self.edit_atom_label(self._hover_atom)
            event.accept()
            return
        delete = key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace)
        text = event.text().upper()
        model = self._model

        if self._hover_atom is not None and self._hover_atom < model.atom_count:
            atom = self._hover_atom
            if text in _HOVER_ELEMENT_KEYS:
                model.set_atom_symbol(atom, _HOVER_ELEMENT_KEYS[text])
                self._last_atom = atom
            elif text in ("+", "="):
                model.set_atom_charge(atom, 1)
            elif text in ("-", "_"):
                model.set_atom_charge(atom, -1)
            elif delete:
                model.delete_atom(atom)
            else:
                self._tool_key(event)
                return
            self._after_edit()
            event.accept()
            return
        if self._hover_bond is not None and self._hover_bond < model.bond_count:
            bond = self._hover_bond
            if key in (Qt.Key.Key_1, Qt.Key.Key_2, Qt.Key.Key_3):
                model.set_bond_order(bond, int(text))
            elif key == Qt.Key.Key_W:
                model.set_bond_stereo(bond, STEREO_WEDGE)
            elif key == Qt.Key.Key_H:
                model.set_bond_stereo(bond, STEREO_HASH)
            elif key == Qt.Key.Key_U:
                model.set_bond_stereo(bond, STEREO_WAVY)
            elif key == Qt.Key.Key_B:
                model.set_bond_bold(bond, not model.bond_bold(bond))
            elif text in ("+", "="):
                model.scale_bond_length(bond, 1.25)
            elif text in ("-", "_"):
                model.scale_bond_length(bond, 0.8)
            elif delete:
                model.delete_bond(bond)
            else:
                self._tool_key(event)
                return
            self._after_edit()
            event.accept()
            return
        if delete:
            if self._selection:
                model.delete_atoms(self._selection)
                self._after_edit()
            else:
                self.set_tool("erase")
            event.accept()
            return
        self._tool_key(event)

    def _tool_key(self, event: QKeyEvent) -> None:
        tool = _TOOL_KEYS.get(event.key())
        if tool is None:
            super().keyPressEvent(event)
            return
        self.set_tool(tool)
        event.accept()


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


def crop_to_content(image: QImage, margin: int = 2) -> QImage:
    """Cut the fully transparent border off *image*, keeping *margin* pixels."""
    import numpy as np  # noqa: PLC0415

    image = image.convertToFormat(QImage.Format.Format_ARGB32)
    width, height = image.width(), image.height()
    if width == 0 or height == 0:
        return image
    raw = np.frombuffer(image.constBits(), dtype=np.uint8, count=image.sizeInBytes())
    pixels = raw.reshape(height, image.bytesPerLine())[:, : width * 4].reshape(height, width, 4)
    # Ink = visible and not white: the white halos behind atom labels do not
    # count as content, so they never leave a blank rim around the drawing.
    ink = (pixels[:, :, 3] > 8) & (pixels[:, :, :3].min(axis=2) < 245)
    rows = np.flatnonzero(ink.any(axis=1))
    cols = np.flatnonzero(ink.any(axis=0))
    if rows.size == 0 or cols.size == 0:
        return image
    top = max(int(rows[0]) - margin, 0)
    bottom = min(int(rows[-1]) + margin, height - 1)
    left = max(int(cols[0]) - margin, 0)
    right = min(int(cols[-1]) + margin, width - 1)
    return image.copy(left, top, right - left + 1, bottom - top + 1)


def _rect_hits_segment(rect: QRectF, a: QPointF, b: QPointF) -> bool:
    """True when the segment a–b touches the rectangle (Liang–Barsky clip)."""
    x0, y0 = a.x(), a.y()
    dx, dy = b.x() - x0, b.y() - y0
    t0, t1 = 0.0, 1.0
    for p, q in (
        (-dx, x0 - rect.left()),
        (dx, rect.right() - x0),
        (-dy, y0 - rect.top()),
        (dy, rect.bottom() - y0),
    ):
        if abs(p) < 1e-12:
            if q < 0:
                return False
            continue
        t = q / p
        if p < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1:
            return False
    return True


def _segment_distance(p: QPointF, a: QPointF, b: QPointF) -> float:
    abx, aby = b.x() - a.x(), b.y() - a.y()
    length2 = abx * abx + aby * aby
    if length2 < 1e-9:
        return math.hypot(p.x() - a.x(), p.y() - a.y())
    t = max(0.0, min(1.0, ((p.x() - a.x()) * abx + (p.y() - a.y()) * aby) / length2))
    cx, cy = a.x() + t * abx, a.y() + t * aby
    return math.hypot(p.x() - cx, p.y() - cy)


def _shorten(p1: QPointF, p2: QPointF, r1: float, r2: float) -> tuple[QPointF, QPointF]:
    dx, dy = p2.x() - p1.x(), p2.y() - p1.y()
    length = math.hypot(dx, dy)
    if length < 1e-6 or r1 + r2 >= length * 0.9:
        return p1, p2
    ux, uy = dx / length, dy / length
    return (
        QPointF(p1.x() + ux * r1, p1.y() + uy * r1),
        QPointF(p2.x() - ux * r2, p2.y() - uy * r2),
    )


def _offset_line(
    p1: QPointF, p2: QPointF, ox: float, oy: float, trim: float
) -> tuple[QPointF, QPointF]:
    dx, dy = p2.x() - p1.x(), p2.y() - p1.y()
    return (
        QPointF(p1.x() + dx * trim + ox, p1.y() + dy * trim + oy),
        QPointF(p2.x() - dx * trim + ox, p2.y() - dy * trim + oy),
    )


# ---------------------------------------------------------------------------
# Periodic table
# ---------------------------------------------------------------------------

_LANTHANIDES = ELEMENT_SYMBOLS[56:71]  # La–Lu
_ACTINIDES = ELEMENT_SYMBOLS[88:103]  # Ac–Lr

_CATEGORY_COLORS: dict[str, str] = {
    "alkali": "#FDE2E2",
    "alkaline": "#FEEBC8",
    "transition": "#E0E7FF",
    "post_transition": "#E2E8F0",
    "metalloid": "#D1FAE5",
    "nonmetal": "#DBEAFE",
    "halogen": "#DCFCE7",
    "noble": "#F3E8FF",
    "lanthanide": "#FCE7F3",
    "actinide": "#FAE8FF",
}
_DARK_CATEGORY_COLORS: dict[str, str] = {
    "alkali": "#4A202A",
    "alkaline": "#4A3019",
    "transition": "#1F2D4D",
    "post_transition": "#283545",
    "metalloid": "#163F35",
    "nonmetal": "#1A365D",
    "halogen": "#19422E",
    "noble": "#352352",
    "lanthanide": "#46203C",
    "actinide": "#3E1F4C",
}
_CATEGORY_MEMBERS: dict[str, frozenset[str]] = {
    "alkali": frozenset({"Li", "Na", "K", "Rb", "Cs", "Fr"}),
    "alkaline": frozenset({"Be", "Mg", "Ca", "Sr", "Ba", "Ra"}),
    "nonmetal": frozenset({"H", "C", "N", "O", "P", "S", "Se"}),
    "halogen": frozenset({"F", "Cl", "Br", "I", "At", "Ts"}),
    "noble": frozenset({"He", "Ne", "Ar", "Kr", "Xe", "Rn", "Og"}),
    "metalloid": frozenset({"B", "Si", "Ge", "As", "Sb", "Te"}),
    "post_transition": frozenset(
        {"Al", "Ga", "In", "Sn", "Tl", "Pb", "Bi", "Po", "Nh", "Fl", "Mc", "Lv"}
    ),
    "lanthanide": frozenset(_LANTHANIDES),
    "actinide": frozenset(_ACTINIDES),
}


def element_category(symbol: str) -> str:
    for category, members in _CATEGORY_MEMBERS.items():
        if symbol in members:
            return category
    return "transition"


def periodic_table_positions() -> dict[str, tuple[int, int]]:
    """``symbol → (row, column)`` in an 18-column table (rows 7 and 8 = f-block)."""
    positions: dict[str, tuple[int, int]] = {"H": (0, 0), "He": (0, 17)}
    z = 2  # index into ELEMENT_SYMBOLS of the next element (Li)
    for row in (1, 2):
        for col in (0, 1, 12, 13, 14, 15, 16, 17):
            positions[ELEMENT_SYMBOLS[z]] = (row, col)
            z += 1
    for row in (3, 4):
        for col in range(18):
            positions[ELEMENT_SYMBOLS[z]] = (row, col)
            z += 1
    for row, f_row, f_block in ((5, 7, _LANTHANIDES), (6, 8, _ACTINIDES)):
        positions[ELEMENT_SYMBOLS[z]] = (row, 0)
        positions[ELEMENT_SYMBOLS[z + 1]] = (row, 1)
        z += 2
        for i, symbol in enumerate(f_block):
            positions[symbol] = (f_row, 2 + i)
        z += len(f_block)
        for col in range(3, 18):
            positions[ELEMENT_SYMBOLS[z]] = (row, col)
            z += 1
    return positions


class PeriodicTableDialog(QDialog):
    """Pick any element; returns its symbol via :meth:`selected_symbol`."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Periodic Table"))
        self._symbol = ""
        self._buttons: dict[str, QPushButton] = {}
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        hint = QLabel(tr("Click an element to use it in the drawing."))
        hint.setStyleSheet(theme.CAPTION_STYLE)
        layout.addWidget(hint)
        grid = QGridLayout()
        grid.setHorizontalSpacing(3)
        grid.setVerticalSpacing(3)
        positions = periodic_table_positions()
        dark = theme.is_dark()
        category_palette = _DARK_CATEGORY_COLORS if dark else _CATEGORY_COLORS
        fg_palette = DARK_ELEMENT_COLORS if dark else ELEMENT_COLORS
        for symbol, (row, col) in positions.items():
            grid_row = row + 1 if row >= 7 else row  # gap above the f-block
            button = QPushButton(symbol)
            button.setObjectName(f"element_{symbol}")
            button.setFixedSize(36, 30)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            z = ELEMENT_SYMBOLS.index(symbol) + 1
            button.setToolTip(f"{symbol} (Z = {z})")
            bg = category_palette[element_category(symbol)]
            fg = fg_palette.get(symbol, theme.TEXT)
            button.setStyleSheet(
                f"QPushButton {{ background: {bg}; color: {fg}; border: 1px solid {theme.BORDER};"
                " border-radius: 4px; font-weight: 600; padding: 0; min-width: 0; }"
                f"QPushButton:hover {{ border: 2px solid {theme.ACCENT}; }}"
            )
            button.clicked.connect(lambda _checked=False, s=symbol: self._choose(s))
            grid.addWidget(button, grid_row, col)
            self._buttons[symbol] = button
        for row, text in ((5, "57–71"), (6, "89–103")):
            marker = QLabel(text)
            marker.setAlignment(Qt.AlignmentFlag.AlignCenter)
            marker.setStyleSheet(theme.CAPTION_STYLE)
            grid.addWidget(marker, row, 2)
        grid.setRowMinimumHeight(7, 8)
        layout.addLayout(grid)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_btn is not None:
            cancel_btn.setText(tr("Cancel"))
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _choose(self, symbol: str) -> None:
        self._symbol = symbol
        self.accept()

    def selected_symbol(self) -> str:
        return self._symbol

    def button_for(self, symbol: str) -> QPushButton:
        return self._buttons[symbol]

    @classmethod
    def get_element(cls, parent: QWidget | None = None) -> str | None:
        dialog = cls(parent)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selected_symbol():
            return dialog.selected_symbol()
        return None


# ---------------------------------------------------------------------------
# Context menu & atom properties
# ---------------------------------------------------------------------------


def _add_action(menu: QMenu, text: str, slot, shortcut: str = "", *, enabled: bool = True):  # noqa: ANN001, ANN202
    action = menu.addAction(text)
    if shortcut:
        action.setShortcut(shortcut)
        action.setShortcutVisibleInContextMenu(True)
    action.setEnabled(enabled)
    action.triggered.connect(lambda _checked=False: slot())
    return action


def _build_context_menu(canvas: MoleculeCanvas, point: QPointF) -> QMenu:
    """Context menu for whatever is under *point* (atom, bond, selection, empty)."""
    menu = QMenu(canvas)
    model = canvas.model()
    atom = canvas._atom_at(point)
    bond = None if atom is not None else canvas._bond_at(point)
    selection = canvas.selected_atoms()

    def after(action):  # noqa: ANN001, ANN202
        def run() -> None:
            action()
            canvas._after_edit(keep_selection=True)

        return run

    if atom is not None:
        menu.addSection(
            tr("Atom {n} ({symbol})").format(n=atom + 1, symbol=model.atom_symbol(atom))
        )
        _add_action(menu, tr("Edit label…"), lambda: canvas.edit_atom_label(atom), "Enter")
        _add_action(menu, tr("Atom properties…"), lambda: canvas.open_atom_properties(atom))
        _add_action(
            menu, tr("Increase charge (+)"), after(lambda: model.set_atom_charge(atom, 1)), "+"
        )
        _add_action(
            menu, tr("Decrease charge (−)"), after(lambda: model.set_atom_charge(atom, -1)), "-"
        )
        _add_action(
            menu,
            tr("Show hydrogens as atoms"),
            after(lambda: model.add_explicit_hydrogens([atom])),
            enabled=model.implicit_hydrogens(atom) > 0,
        )
        _add_action(menu, tr("Delete atom"), after(lambda: model.delete_atom(atom)), "Del")
    elif bond is not None:
        menu.addSection(tr("Bond"))
        for order, text in ((1, tr("Single Bond")), (2, tr("Double Bond")), (3, tr("Triple Bond"))):
            _add_action(
                menu, text, after(lambda o=order: model.set_bond_order(bond, o)), str(order)
            )
        _add_action(
            menu, tr("Wedge Up"), after(lambda: model.set_bond_stereo(bond, STEREO_WEDGE)), "W"
        )
        _add_action(
            menu, tr("Hash Down"), after(lambda: model.set_bond_stereo(bond, STEREO_HASH)), "H"
        )
        _add_action(
            menu,
            tr("Wavy bond (unknown stereo)"),
            after(lambda: model.set_bond_stereo(bond, STEREO_WAVY)),
            "U",
        )
        _add_action(
            menu,
            tr("Bold bond"),
            after(lambda: model.set_bond_bold(bond, not model.bond_bold(bond))),
            "B",
        )
        _add_action(
            menu, tr("Longer bond"), after(lambda: model.scale_bond_length(bond, 1.25)), "+"
        )
        _add_action(
            menu, tr("Shorter bond"), after(lambda: model.scale_bond_length(bond, 0.8)), "-"
        )
        _add_action(
            menu, tr("Standard length"), after(lambda: model.set_bond_length(bond, BOND_LENGTH))
        )
        _add_action(menu, tr("Delete bond"), after(lambda: model.delete_bond(bond)), "Del")
    if selection:
        menu.addSection(tr("Selection ({count} atoms)").format(count=len(selection)))
        _add_action(menu, tr("Copy"), canvas.copy_selection, "Ctrl+C")
        _add_action(menu, tr("Cut"), canvas.cut_selection, "Ctrl+X")
        _add_action(menu, tr("Duplicate"), canvas.duplicate_selection, "Ctrl+D")
        _add_action(menu, tr("Save as custom group…"), canvas.request_save_group)
        _add_action(menu, tr("Rotate left 15°"), lambda: canvas.rotate_selection(15.0), "Alt+Left")
        _add_action(
            menu, tr("Rotate right 15°"), lambda: canvas.rotate_selection(-15.0), "Alt+Right"
        )
        _add_action(
            menu, tr("Flip horizontally"), lambda: canvas.flip_selection(horizontal=True), "Alt+H"
        )
        _add_action(
            menu, tr("Flip vertically"), lambda: canvas.flip_selection(horizontal=False), "Alt+V"
        )
        _add_action(
            menu, tr("Delete selection"), after(lambda: model.delete_atoms(selection)), "Del"
        )
    menu.addSection(tr("Structure"))
    _add_action(menu, tr("Paste"), canvas.paste_from_clipboard, "Ctrl+V")
    _add_action(menu, tr("Copy structure"), canvas.copy_selection, enabled=not model.is_empty())
    _add_action(menu, tr("Select all"), canvas.select_all, "Ctrl+A", enabled=not model.is_empty())
    _add_action(
        menu, tr("Show all hydrogens"), canvas.add_explicit_hydrogens, enabled=not model.is_empty()
    )
    _add_action(
        menu,
        tr("Hide explicit hydrogens"),
        canvas.remove_explicit_hydrogens,
        enabled=not model.is_empty(),
    )
    _add_action(menu, tr("Clean 2D"), canvas.clean_2d, enabled=not model.is_empty())
    _add_action(menu, tr("Fit View"), canvas.fit_to_view, "Space")
    return menu


_RADICAL_CHOICES = ((0, "none"), (1, "monovalent •"), (2, "divalent ••"))


class AtomPropertiesDialog(QDialog):
    """Element, charge, isotope, hydrogen count and radical of one atom."""

    def __init__(self, model: MolEditorModel, atom: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Atom Properties"))
        form = QFormLayout(self)
        self.symbol_edit = QLineEdit(model.atom_symbol(atom))
        self.symbol_edit.setMaxLength(3)
        self.initial_charge = model.atom_charge(atom)
        self.charge_spin = QSpinBox()
        self.charge_spin.setRange(-8, 8)
        self.charge_spin.setValue(self.initial_charge)
        self.isotope_spin = QSpinBox()
        self.isotope_spin.setRange(0, 300)
        self.isotope_spin.setSpecialValueText(tr("natural"))
        self.isotope_spin.setValue(model.atom_isotope(atom))
        self.hydrogen_spin = QSpinBox()
        self.hydrogen_spin.setRange(-1, 8)
        self.hydrogen_spin.setSpecialValueText(tr("automatic"))
        self.hydrogen_spin.setValue(
            model.implicit_hydrogens(atom)
            if model.atom_hydrogens_fixed(atom) and not model.atom_radicals(atom)
            else -1
        )
        self.radical_combo = QComboBox()
        for value, text in _RADICAL_CHOICES:
            self.radical_combo.addItem(tr(text), value)
        self.radical_combo.setCurrentIndex(max(0, min(2, model.atom_radicals(atom))))
        form.addRow(tr("Element"), self.symbol_edit)
        form.addRow(tr("Charge"), self.charge_spin)
        form.addRow(tr("Isotope (mass number)"), self.isotope_spin)
        form.addRow(tr("Hydrogens"), self.hydrogen_spin)
        form.addRow(tr("Radical"), self.radical_combo)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn is not None:
            ok_btn.setText(tr("OK"))
        cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_btn is not None:
            cancel_btn.setText(tr("Cancel"))
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _on_accept(self) -> None:
        symbol = self.symbol_edit.text().strip()
        if not is_element_symbol(symbol):
            self.symbol_edit.setStyleSheet(f"border: 2px solid {INVALID_STROKE.name()};")
            return
        self.accept()

    def values(self) -> dict[str, object]:
        hydrogens = self.hydrogen_spin.value()
        return {
            "symbol": self.symbol_edit.text().strip(),
            "charge": self.charge_spin.value(),
            "isotope": self.isotope_spin.value(),
            "hydrogens": None if hydrogens < 0 else hydrogens,
            "radicals": int(self.radical_combo.currentData()),
        }
