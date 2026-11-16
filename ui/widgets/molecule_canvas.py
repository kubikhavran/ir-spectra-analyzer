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
* Global: Ctrl+Z, Ctrl+Y / Ctrl+Shift+Z, Ctrl+C (SMILES), Ctrl+V (SMILES or
  MOL block), Space / 0 fit view, mouse wheel zoom, middle/right drag pan.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from PySide6.QtCore import QBuffer, QIODevice, QPointF, QRectF, QSize, Qt, Signal
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
    QPaintEvent,
    QPen,
    QPolygonF,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from chemistry.mol_editor_model import (
    BOND_LENGTH,
    ELEMENT_SYMBOLS,
    STEREO_HASH,
    STEREO_NONE,
    STEREO_WEDGE,
    MolEditorModel,
)
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

TOOLS: tuple[str, ...] = (
    "select",
    "erase",
    "bond_single",
    "bond_double",
    "bond_triple",
    "bond_wedge",
    "bond_hash",
    "chain",
    "atom",
    "ring",
    "group",
)
_BOND_TOOLS: dict[str, tuple[int, str]] = {
    "bond_single": (1, STEREO_NONE),
    "bond_double": (2, STEREO_NONE),
    "bond_triple": (3, STEREO_NONE),
    "bond_wedge": (1, STEREO_WEDGE),
    "bond_hash": (1, STEREO_HASH),
}
# Keys that switch tools when the pointer is not over an atom or bond.
_TOOL_KEYS: dict[int, str] = {
    Qt.Key.Key_V: "select",
    Qt.Key.Key_1: "bond_single",
    Qt.Key.Key_2: "bond_double",
    Qt.Key.Key_3: "bond_triple",
    Qt.Key.Key_W: "bond_wedge",
    Qt.Key.Key_H: "bond_hash",
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


def element_color(symbol: str) -> QColor:
    return QColor(ELEMENT_COLORS.get(symbol, DEFAULT_ELEMENT_COLOR))


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
    h_left: bool


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


class MoleculeCanvas(QWidget):
    """Interactive 2D structure editor canvas."""

    structure_changed = Signal()
    tool_changed = Signal(str)
    hint_changed = Signal(str)

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

        self._cache_revision = -1
        self._invalid: set[int] = set()
        self._labels: dict[int, _AtomLabel] = {}
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

    def to_smiles(self) -> str:
        return self._model.to_smiles()

    def to_mol_block(self) -> str:
        return self._model.to_mol_block()

    def tool(self) -> str:
        return self._tool

    def set_tool(self, tool: str) -> None:
        if tool not in TOOLS:
            raise ValueError(f"Unknown tool: {tool!r}")
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
        self.set_tool("atom")
        self._update_hint()

    def ring_type(self) -> str:
        return self._ring_type

    def set_ring_type(self, ring_type: str) -> None:
        self._ring_type = ring_type
        self.set_tool("ring")
        self._update_hint()

    def group_key(self) -> str:
        return self._group_key

    def set_group(self, group_key: str) -> None:
        self._group_key = group_key
        self.set_tool("group")
        self._update_hint()

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
        """Render the structure (no hover/selection) to PNG; ``b""`` when empty."""
        if self._model.is_empty():
            return b""
        image = QImage(QSize(width, height), QImage.Format.Format_ARGB32)
        image.fill(QColor("white"))
        zoom, origin = self._fit_transform(width, height, max_zoom=2.0)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        self._paint_structure(painter, zoom, origin, interactive=False)
        painter.end()
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")  # type: ignore[call-overload]
        return bytes(buffer.data().data())

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

    def _snapped_angle(self, start: tuple[float, float], point: QPointF) -> float:
        wx, wy = self._to_world(point)
        angle = math.degrees(math.atan2(wy - start[1], wx - start[0]))
        return round(angle / 30.0) * 30.0

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
            if symbol == "C" and charge == 0 and degree > 0:
                continue
            hydrogens = model.implicit_hydrogens(idx)
            if degree == 0:
                h_left = symbol in _H_FIRST_ELEMENTS
            else:
                ax, _ay = model.atom_position(idx)
                dx = sum(model.atom_position(n)[0] - ax for n in model.atom_neighbors(idx))
                h_left = dx > 0.1
            labels[idx] = _AtomLabel(symbol, hydrogens, charge, h_left)
        self._labels = labels
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
        del interactive
        self._refresh_cache()
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
            pen = QPen(INVALID_STROKE)
            pen.setWidthF(1.3)
            painter.setPen(pen)
            painter.setBrush(INVALID_FILL)
            radius = 0.55 * font_px + 3
            for idx in self._invalid:
                if idx < len(positions):
                    painter.drawEllipse(positions[idx], radius, radius)

        width = max(1.1, min(3.2, 0.035 * bond_px))
        pen = QPen(BOND_COLOR)
        pen.setWidthF(width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        label_radius = 0.62 * font_px
        for bond in range(model.bond_count):
            a, b = model.bond_atoms(bond)
            p1, p2 = positions[a], positions[b]
            r1 = label_radius if a in self._labels else 0.0
            r2 = label_radius if b in self._labels else 0.0
            q1, q2 = _shorten(p1, p2, r1, r2)
            self._paint_bond(painter, pen, bond, q1, q2, bond_px, zoom, origin)

        font = QFont(self.font())
        font.setPixelSize(round(font_px))
        font.setWeight(QFont.Weight.DemiBold)
        small = QFont(font)
        small.setPixelSize(max(6, round(font_px * 0.68)))
        for idx, label in self._labels.items():
            self._paint_label(painter, positions[idx], label, font, small)

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
            painter.setBrush(QBrush(BOND_COLOR))
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

        offset = 0.18 * bond_px
        if order == 1:
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

    def _paint_label(
        self, painter: QPainter, center: QPointF, label: _AtomLabel, font: QFont, small: QFont
    ) -> None:
        fm = QFontMetricsF(font)
        sm = QFontMetricsF(small)
        color = element_color(label.symbol)
        sym_w = fm.horizontalAdvance(label.symbol)
        baseline = center.y() + (fm.ascent() - fm.descent()) / 2
        sym_left = center.x() - sym_w / 2

        h_text = "H" if label.hydrogens else ""
        h_count = str(label.hydrogens) if label.hydrogens > 1 else ""
        h_w = fm.horizontalAdvance(h_text) + (sm.horizontalAdvance(h_count) if h_count else 0)
        h_left = label.h_left and bool(h_text)
        sub_drop = fm.ascent() * 0.35

        # A soft halo keeps crossing lines away from the glyphs.
        halo_left = sym_left - (h_w if h_left else 0) - 1
        halo_right = sym_left + sym_w + (0 if h_left else h_w) + 1
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.SURFACE))
        painter.drawRoundedRect(
            QRectF(
                halo_left, center.y() - fm.ascent() / 2 - 1, halo_right - halo_left, fm.ascent() + 2
            ),
            3,
            3,
        )

        painter.setPen(color)
        painter.setFont(font)
        painter.drawText(QPointF(sym_left, baseline), label.symbol)
        if h_text:
            x = sym_left - h_w if h_left else sym_left + sym_w
            painter.setFont(font)
            painter.drawText(QPointF(x, baseline), h_text)
            if h_count:
                painter.setFont(small)
                painter.drawText(
                    QPointF(x + fm.horizontalAdvance(h_text), baseline + sub_drop), h_count
                )
        charge = _charge_text(label.charge)
        if charge:
            painter.setFont(small)
            right = sym_left + sym_w + (0 if h_left else h_w)
            painter.drawText(QPointF(right + 0.5, baseline - fm.ascent() * 0.55), charge)

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
        angle = math.radians(self._snapped_angle(start, cursor))
        end = (start[0] + BOND_LENGTH * math.cos(angle), start[1] + BOND_LENGTH * math.sin(angle))
        return start, end, None

    def _chain_preview(self, drag: _Drag, cursor: QPointF) -> list[tuple[float, float]]:
        sx, sy = (
            self._model.atom_position(drag.atom)
            if drag.atom is not None
            else self._to_world(drag.start)
        )
        ex, ey = self._to_world(cursor)
        angle = math.radians(self._snapped_angle((sx, sy), cursor))
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

    def _update_hint(self) -> None:
        if self._hover_atom is not None:
            hint = tr(
                "Atom: type C, O, N, S, P, F, I, H, B, L (Cl), R (Br); +/− charge; Del removes"
            )
        elif self._hover_bond is not None:
            hint = tr("Bond: 1/2/3 order, W wedge, H hash, Del removes")
        else:
            hints = {
                "select": tr("Drag atoms to move them, drag empty space to select"),
                "erase": tr("Click an atom or bond to delete it"),
                "bond_single": tr("Click or drag to draw bonds; click a bond to cycle its order"),
                "bond_double": tr("Click or drag to draw double bonds"),
                "bond_triple": tr("Click or drag to draw triple bonds"),
                "bond_wedge": tr("Wedge bond (towards viewer); click again to flip"),
                "bond_hash": tr("Hashed bond (away from viewer); click again to flip"),
                "chain": tr("Drag to draw a carbon chain"),
                "atom": tr("Click to place {symbol} or replace an atom").format(
                    symbol=self._atom_symbol
                ),
                "ring": tr("Click empty space, an atom or a bond to add the ring"),
                "group": tr("Click an atom to attach {group}").format(group=self._group_key),
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
        if drag is None:
            self._update_hover(point)
            self.update()
            return
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
        self.unsetCursor()
        if drag.kind == "pan":
            self.update()
            return
        if drag.kind == "move":
            if drag.moved:
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
        if self._tool == "select":
            atom = self._atom_at(event.position())
            if atom is not None:
                self._selection = set(self._model.fragment_atoms(atom))
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
        elif tool in _BOND_TOOLS:
            order, stereo = _BOND_TOOLS[tool]
            if atom is not None:
                self._last_atom = model.sprout_atom(atom, "C", order, stereo)
            elif bond is not None:
                a, b = model.bond_atoms(bond)
                model.add_or_update_bond(
                    a, b, order, stereo, cycle_on_existing=tool == "bond_single"
                )
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
                    self._last_atom = model.sprout_atom(
                        origin_atom, symbol, order, stereo, preferred_angle=angle
                    )
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
        if ctrl:
            if key == Qt.Key.Key_Z:
                self.redo() if shift else self.undo()
            elif key == Qt.Key.Key_Y:
                self.redo()
            elif key == Qt.Key.Key_C:
                self.copy_smiles()
            elif key == Qt.Key.Key_V:
                self.paste_text(QGuiApplication.clipboard().text())
            elif key == Qt.Key.Key_A:
                self._selection = set(range(self._model.atom_count))
                self.update()
            else:
                super().keyPressEvent(event)
                return
            event.accept()
            return
        if key in (Qt.Key.Key_Space, Qt.Key.Key_0):
            self.fit_to_view()
            event.accept()
            return
        if key == Qt.Key.Key_Escape:
            self._drag = None
            self._selection.clear()
            self.update()
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
        for symbol, (row, col) in positions.items():
            grid_row = row + 1 if row >= 7 else row  # gap above the f-block
            button = QPushButton(symbol)
            button.setObjectName(f"element_{symbol}")
            button.setFixedSize(36, 30)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            z = ELEMENT_SYMBOLS.index(symbol) + 1
            button.setToolTip(f"{symbol} (Z = {z})")
            bg = _CATEGORY_COLORS[element_category(symbol)]
            fg = ELEMENT_COLORS.get(symbol, theme.TEXT)
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
