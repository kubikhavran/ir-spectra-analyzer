"""
MoleculeEditorDialog — Dialog for editing molecular structures.

Provides two tabs:
  - Draw: native 2D structure editor (QPainter canvas over RDKit), fully offline
  - SMILES: text-based input with live RDKit preview

Both tabs stay in sync: edits on the canvas update the SMILES field, and a
valid SMILES typed on the SMILES tab is loaded into the canvas when the user
clicks *Preview* or switches back to *Draw*.

The Draw tab follows what professional sketchers (Ketcher, Marvin, ChemDraw,
PubChem Sketcher) offer: ring and functional-group templates, salts and
solvents, user-defined groups typed as abbreviations / condensed formulas /
SMILES, copy-paste of structure parts, atom properties (charge, isotope,
hydrogens, radicals), rotate/flip, stereo (R/S, E/Z) and atom-number display,
MOL/InChI export and a structure check.
"""

from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QIcon,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.custom_groups import CustomGroupStore
from chemistry.mol_editor_model import MolEditorModel
from chemistry.mol_fragments import (
    SALTS_AND_SOLVENTS,
    Fragment,
    fragment_from_smiles,
    fragment_to_group_smiles,
    parse_group,
)
from ui import icons, theme
from ui.i18n import tr
from ui.widgets.molecule_canvas import (
    BOND_COLOR,
    MoleculeCanvas,
    PeriodicTableDialog,
    element_color,
)

# (tool, label, shortcut shown in the tooltip)
_TOOL_BUTTONS: tuple[tuple[str, str, str], ...] = (
    ("select", "Select / Move", "V"),
    ("erase", "Erase", "Del"),
    ("bond_single", "Single Bond", "1"),
    ("bond_double", "Double Bond", "2"),
    ("bond_triple", "Triple Bond", "3"),
    ("bond_wedge", "Wedge Up", "W"),
    ("bond_hash", "Hash Down", "H"),
    ("bond_wavy", "Wavy Bond", "U"),
    ("bond_bold", "Bold Bond", "B"),
    ("chain", "Carbon Chain", "C"),
)
_RING_BUTTONS: tuple[tuple[str, str], ...] = (
    ("cyclopropane", "Cyclopropane"),
    ("cyclobutane", "Cyclobutane"),
    ("cyclopentane", "Cyclopentane"),
    ("cyclohexane", "Cyclohexane"),
    ("cycloheptane", "Cycloheptane"),
    ("benzene", "Benzene"),
    ("naphthalene", "Naphthalene"),
    ("pyridine", "Pyridine"),
    ("pyrimidine", "Pyrimidine"),
    ("furan", "Furan"),
    ("thiophene", "Thiophene"),
    ("pyrrole", "Pyrrole"),
    ("imidazole", "Imidazole"),
    ("indole", "Indole"),
    ("quinoline", "Quinoline"),
)
# Saturated O/N rings, chairs and sugars (the building blocks of carbohydrates).
_HETEROCYCLE_BUTTONS: tuple[tuple[str, str], ...] = (
    ("oxane", "Tetrahydropyran (oxane)"),
    ("oxolane", "Tetrahydrofuran (oxolane)"),
    ("dioxane", "1,4-Dioxane"),
    ("piperidine", "Piperidine"),
    ("morpholine", "Morpholine"),
    ("piperazine", "Piperazine"),
    ("chair", "Cyclohexane chair"),
    ("oxane_chair", "Pyranose chair (oxane)"),
    ("beta_glucopyranose", "β-D-Glucopyranose (click an OH or atom to make a glycoside)"),
    ("alpha_glucopyranose", "α-D-Glucopyranose (click an OH or atom to make a glycoside)"),
    ("beta_ribofuranose", "β-D-Ribofuranose (click an OH or atom to make a glycoside)"),
)
# (group key, button label)
_GROUP_BUTTONS: tuple[tuple[str, str], ...] = (
    ("-OH", "-OH"),
    ("-NH2", "-NH₂"),
    ("-COOH", "-COOH"),
    ("-COOMe", "-COOMe"),
    ("-CHO", "-CHO"),
    ("-CN", "-CN"),
    ("-NO2", "-NO₂"),
    ("-SO3H", "-SO₃H"),
    ("-CF3", "-CF₃"),
    ("-TMS", "-TMS"),
    ("-Ph", "-Ph"),
    ("-Ac", "-Ac"),
    ("-Boc", "-Boc"),
)
_ELEMENT_BUTTONS: tuple[str, ...] = (
    "C",
    "H",
    "O",
    "N",
    "S",
    "P",
    "F",
    "Cl",
    "Br",
    "I",
    "Si",
    "B",
    "Na",
    "K",
    "Mg",
    "Li",
)

_PALETTE_STYLE = f"""
QToolButton#molPaletteButton {{
    background: {theme.SURFACE}; color: {theme.TEXT};
    border: 1px solid {theme.BORDER}; border-radius: 5px; padding: 2px;
}}
QToolButton#molPaletteButton:hover {{ border-color: {theme.ACCENT}; background: {theme.ACCENT_SOFT}; }}
QToolButton#molPaletteButton:checked {{
    background: {theme.ACCENT_SOFT}; border: 2px solid {theme.ACCENT};
}}
QToolButton#molPaletteButton:disabled {{ color: {theme.TEXT_FAINT}; }}
QFrame#molSidePanel {{
    background: {theme.SURFACE_ALT}; border: 1px solid {theme.BORDER}; border-radius: 6px;
}}
QFrame#molCanvasFrame {{
    background: {theme.SURFACE}; border: 1px solid {theme.BORDER_STRONG}; border-radius: 6px;
}}
"""


# ---------------------------------------------------------------------------
# Icons painted with QPainter
# ---------------------------------------------------------------------------


def _new_pixmap(size: int) -> tuple[QPixmap, QPainter]:
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.setDevicePixelRatio(2.0)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    return pixmap, painter


def _tool_icon(tool: str) -> QIcon:
    if tool == "select":
        return icons.icon("select")
    size = 24
    pixmap, painter = _new_pixmap(size)
    pen = QPen(QColor(theme.TEXT))
    pen.setWidthF(1.8)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    a, b = QPointF(5, 19), QPointF(19, 5)
    if tool == "erase":
        painter.translate(12, 12)
        painter.rotate(-45)
        painter.setBrush(QColor(theme.DANGER_SOFT))
        painter.drawRoundedRect(QRectF(-8, -4.5, 16, 9), 2, 2)
        painter.setBrush(QColor(theme.DANGER))
        painter.drawRoundedRect(QRectF(-8, -4.5, 6, 9), 2, 2)
    elif tool == "bond_single":
        painter.drawLine(a, b)
    elif tool in ("bond_double", "bond_triple"):
        offsets = (-2.2, 2.2) if tool == "bond_double" else (-3.4, 0.0, 3.4)
        for o in offsets:
            painter.drawLine(a + QPointF(o, o), b + QPointF(o, o))
    elif tool == "bond_bold":
        thick = QPen(QColor(theme.TEXT))
        thick.setWidthF(4.2)
        thick.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(thick)
        painter.drawLine(a, b)
    elif tool == "bond_wedge":
        painter.setBrush(QColor(theme.TEXT))
        painter.drawPolygon(QPolygonF([a, QPointF(16.5, 3.5), QPointF(20.5, 7.5)]))
    elif tool == "bond_hash":
        for k in range(1, 7):
            t = k / 6
            cx, cy = 5 + 14 * t, 19 - 14 * t
            h = 0.6 + 2.8 * t
            painter.drawLine(QPointF(cx - h, cy - h), QPointF(cx + h, cy + h))
    elif tool == "bond_wavy":
        path = QPainterPath(a)
        dx, dy = b.x() - a.x(), b.y() - a.y()
        nx, ny = -dy / math.hypot(dx, dy), dx / math.hypot(dx, dy)
        steps = 24
        for k in range(1, steps + 1):
            t = k / steps
            wave = 2.2 * math.sin(2.0 * math.pi * 3.0 * t)
            path.lineTo(a.x() + dx * t + nx * wave, a.y() + dy * t + ny * wave)
        painter.drawPath(path)
    elif tool in ("rotate_left", "rotate_right"):
        painter.drawArc(
            QRectF(5, 5, 14, 14), 30 * 16 if tool == "rotate_left" else 150 * 16, 270 * 16
        )
        tip = QPointF(17.5, 7.5) if tool == "rotate_left" else QPointF(6.5, 7.5)
        side = -1 if tool == "rotate_left" else 1
        painter.drawLine(tip, tip + QPointF(side * 4.0, -1.0))
        painter.drawLine(tip, tip + QPointF(side * 1.0, 4.0))
    elif tool in ("flip_h", "flip_v"):
        if tool == "flip_v":
            painter.translate(12, 12)
            painter.rotate(90)
            painter.translate(-12, -12)
        painter.drawLine(QPointF(12, 3), QPointF(12, 21))
        painter.setBrush(QColor(theme.TEXT))
        painter.drawPolygon(QPolygonF([QPointF(9.5, 6), QPointF(9.5, 18), QPointF(3, 18)]))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolygon(QPolygonF([QPointF(14.5, 6), QPointF(14.5, 18), QPointF(21, 18)]))
    elif tool == "chain":
        painter.drawPolyline(
            QPolygonF(
                [QPointF(3, 15), QPointF(8, 9), QPointF(13, 15), QPointF(18, 9), QPointF(22, 14)]
            )
        )
    painter.end()
    return QIcon(pixmap)


def _ring_icon(ring_type: str, size: int = 34) -> QIcon:
    model = MolEditorModel()
    model.add_ring_template(ring_type, center=(0.0, 0.0))
    coords = [model.atom_position(i) for i in range(model.atom_count)]
    xs = [x for x, _ in coords]
    ys = [y for _, y in coords]
    span = max(max(xs) - min(xs), max(ys) - min(ys), 1e-6)
    scale = (size - 8.0) / span
    cx = (max(xs) + min(xs)) / 2
    cy = (max(ys) + min(ys)) / 2

    def to_icon(x: float, y: float) -> QPointF:
        return QPointF(size / 2 + (x - cx) * scale, size / 2 - (y - cy) * scale)

    points = [to_icon(x, y) for x, y in coords]
    pixmap, painter = _new_pixmap(size)
    pen = QPen(BOND_COLOR)
    pen.setWidthF(1.4)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    for bond in range(model.bond_count):
        i, j = model.bond_atoms(bond)
        painter.drawLine(points[i], points[j])
        ring_center = model.bond_ring_center(bond)
        if model.bond_order(bond) == 2 and ring_center is not None:
            center = to_icon(*ring_center)
            painter.drawLine(
                points[i] + (center - points[i]) * 0.24,
                points[j] + (center - points[j]) * 0.24,
            )
    font = QFont()
    font.setPixelSize(9)
    font.setWeight(QFont.Weight.Bold)
    painter.setFont(font)
    for idx, point in enumerate(points):
        symbol = model.atom_symbol(idx)
        if symbol == "C" or (model.atom_degree(idx) == 1 and model.atom_count > 8):
            # Sugar OH groups stay plain stubs; letters would crowd the icon.
            continue
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.SURFACE))
        painter.drawEllipse(point, 4.6, 4.6)
        painter.setPen(element_color(symbol))
        painter.drawText(
            QRectF(point.x() - 6, point.y() - 6, 12, 12), Qt.AlignmentFlag.AlignCenter, symbol
        )
    painter.end()
    return QIcon(pixmap)


class _ElidedLabel(QLabel):
    """A one-line label that shortens its text with "…" when it does not fit."""

    def __init__(
        self,
        mode: Qt.TextElideMode,
        *,
        tooltip_from_text: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._mode = mode
        self._tooltip_from_text = tooltip_from_text
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(40)

    def setText(self, text: str) -> None:  # noqa: N802
        super().setText(text)
        if self._tooltip_from_text:
            self.setToolTip(text)

    def paintEvent(self, event) -> None:  # noqa: N802, ANN001
        del event
        painter = QPainter(self)
        rect = self.contentsRect()
        shown = self.fontMetrics().elidedText(self.text(), self._mode, rect.width())
        self.style().drawItemText(
            painter,
            rect,
            int(self.alignment().value),
            self.palette(),
            self.isEnabled(),
            shown,
            self.foregroundRole(),
        )
        painter.end()


def _palette_button(text: str = "", *, tooltip: str = "", checkable: bool = True) -> QToolButton:
    button = QToolButton()
    button.setObjectName("molPaletteButton")
    button.setText(text)
    button.setToolTip(tooltip)
    button.setCheckable(checkable)
    button.setAutoRaise(False)
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


def _section_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(theme.SECTION_TITLE_STYLE)
    return label


def _create_group_store() -> CustomGroupStore:
    """Where custom groups live (tests replace this with a temporary store)."""
    return CustomGroupStore()


def _first_mol_record(text: str) -> str:
    """The first record of an SDF file (a plain MOL file is returned as is)."""
    return text.split("$$$$", 1)[0]


class MoleculeEditorDialog(QDialog):
    """Dialog for editing a molecular structure.

    Tab 1 — Draw: native QPainter structure editor.
    Tab 2 — SMILES: text input with live RDKit preview.
    """

    def __init__(self, initial_smiles: str = "", initial_mol_block: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Edit Molecular Structure"))
        self.setMinimumSize(820, 560)
        self.resize(1000, 660)

        self._initial_smiles = initial_smiles
        self._initial_mol_block = initial_mol_block
        self._initial_mol_block_loaded = False
        self._accepted_smiles: str = ""
        self._canvas_png_bytes: bytes = b""
        self._canvas_mol_block: str = ""
        self._canvas_modified = False
        self._loading = True
        self._syncing_from_text = False
        self._synced_smiles = ""

        self._tool_buttons: dict[str, QToolButton] = {}
        self._ring_buttons: dict[str, QToolButton] = {}
        self._group_buttons: dict[str, QToolButton] = {}
        self._element_buttons: dict[str, QToolButton] = {}
        self._salt_buttons: dict[str, QToolButton] = {}
        try:
            self._group_store: CustomGroupStore | None = _create_group_store()
        except OSError:
            self._group_store = None

        self._build_ui()
        self._connect_signals()
        self._load_initial_structure()
        self._loading = False

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self._tabs = QTabWidget()
        layout.addWidget(self._tabs)

        self._tabs.addTab(self._build_draw_tab(), tr("Draw"))
        self._tabs.addTab(self._build_smiles_tab(), tr("SMILES"))

        # Button box
        buttons = QDialogButtonBox()
        ok_btn = buttons.addButton(tr("OK"), QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(tr("Cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        clear_btn = buttons.addButton(tr("Clear"), QDialogButtonBox.ButtonRole.ResetRole)
        ok_btn.setDefault(True)

        ok_btn.clicked.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        clear_btn.clicked.connect(self._on_clear)

        layout.addWidget(buttons)

    def _build_draw_tab(self) -> QWidget:
        container = QWidget()
        container.setObjectName("molecule_draw_tab")
        container.setStyleSheet(_PALETTE_STYLE)
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(6, 6, 6, 6)
        vbox.setSpacing(6)

        self._canvas = MoleculeCanvas()

        # ── Toolbar ────────────────────────────────────────────────────
        toolbar = QHBoxLayout()
        toolbar.setSpacing(4)
        self._palette_group = QButtonGroup(self)
        self._palette_group.setExclusive(True)
        for tool, label, key in _TOOL_BUTTONS:
            button = _palette_button(tooltip=f"{tr(label)} ({key})")
            button.setIcon(_tool_icon(tool))
            button.setIconSize(QSize(22, 22))
            button.setFixedSize(34, 34)
            button.setObjectName("molPaletteButton")
            button.setProperty("tool", tool)
            button.clicked.connect(lambda _checked=False, t=tool: self._canvas.set_tool(t))
            self._palette_group.addButton(button)
            self._tool_buttons[tool] = button
            toolbar.addWidget(button)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setStyleSheet(f"color: {theme.BORDER};")
        toolbar.addSpacing(4)
        toolbar.addWidget(separator)
        toolbar.addSpacing(4)

        self._undo_btn = self._action_button(icons.icon("undo"), tr("Undo"), "Ctrl+Z")
        self._redo_btn = self._action_button(icons.icon("redo"), tr("Redo"), "Ctrl+Y")
        self._clean_btn = self._action_button(QIcon(), tr("Clean 2D"), "")
        self._clean_btn.setText(tr("Clean 2D"))
        self._clean_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._clean_btn.setFixedSize(QSize(78, 34))
        self._fit_btn = self._action_button(icons.icon("zoom"), tr("Fit View"), "Space")
        self._undo_btn.clicked.connect(self._canvas.undo)
        self._redo_btn.clicked.connect(self._canvas.redo)
        self._clean_btn.clicked.connect(self._canvas.clean_2d)
        self._fit_btn.clicked.connect(self._canvas.fit_to_view)
        for button in (self._undo_btn, self._redo_btn, self._clean_btn, self._fit_btn):
            toolbar.addWidget(button)

        toolbar.addSpacing(4)
        self._rotate_left_btn = self._action_button(
            _tool_icon("rotate_left"), tr("Rotate left 15°"), "Alt+←"
        )
        self._rotate_right_btn = self._action_button(
            _tool_icon("rotate_right"), tr("Rotate right 15°"), "Alt+→"
        )
        self._flip_h_btn = self._action_button(
            _tool_icon("flip_h"), tr("Flip horizontally"), "Alt+H"
        )
        self._flip_v_btn = self._action_button(_tool_icon("flip_v"), tr("Flip vertically"), "Alt+V")
        self._rotate_left_btn.clicked.connect(lambda: self._canvas.rotate_selection(15.0))
        self._rotate_right_btn.clicked.connect(lambda: self._canvas.rotate_selection(-15.0))
        self._flip_h_btn.clicked.connect(lambda: self._canvas.flip_selection(horizontal=True))
        self._flip_v_btn.clicked.connect(lambda: self._canvas.flip_selection(horizontal=False))
        for button in (
            self._rotate_left_btn,
            self._rotate_right_btn,
            self._flip_h_btn,
            self._flip_v_btn,
        ):
            toolbar.addWidget(button)

        toolbar.addSpacing(4)
        self._numbers_btn = _palette_button("1·2", tooltip=tr("Show atom numbers"))
        self._numbers_btn.setFixedSize(38, 34)
        self._numbers_btn.toggled.connect(self._canvas.set_show_atom_numbers)
        self._stereo_btn = _palette_button("R/S", tooltip=tr("Show R/S and E/Z labels"))
        self._stereo_btn.setFixedSize(38, 34)
        self._stereo_btn.toggled.connect(self._canvas.set_show_stereo_labels)
        toolbar.addWidget(self._numbers_btn)
        toolbar.addWidget(self._stereo_btn)

        self._more_btn = _palette_button(
            tr("More"), tooltip=tr("Export, import and hydrogens"), checkable=False
        )
        self._more_btn.setFixedHeight(34)
        self._more_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._more_btn.setMenu(self._build_more_menu())
        toolbar.addWidget(self._more_btn)
        toolbar.addStretch(1)
        vbox.addLayout(toolbar)

        # ── Body: rings & groups | canvas | elements ───────────────────
        body = QHBoxLayout()
        body.setSpacing(6)
        body.addWidget(self._build_left_panel())

        canvas_frame = QFrame()
        canvas_frame.setObjectName("molCanvasFrame")
        frame_layout = QVBoxLayout(canvas_frame)
        frame_layout.setContentsMargins(1, 1, 1, 1)
        frame_layout.addWidget(self._canvas)
        body.addWidget(canvas_frame, 1)

        body.addWidget(self._build_right_panel())
        vbox.addLayout(body, 1)

        # ── Info bar ───────────────────────────────────────────────────
        info = QHBoxLayout()
        info.setSpacing(14)
        self._formula_label = QLabel()
        self._formula_label.setObjectName("molecule_formula_label")
        self._mw_label = QLabel()
        self._mw_label.setObjectName("molecule_mw_label")
        # Long SMILES and hints are cut with "…" (full text in the tooltip)
        # instead of running into each other.
        self._live_smiles_label = _ElidedLabel(Qt.TextElideMode.ElideMiddle)
        self._live_smiles_label.setObjectName("molecule_live_smiles_label")
        self._hint_label = _ElidedLabel(Qt.TextElideMode.ElideRight, tooltip_from_text=True)
        self._hint_label.setObjectName("molecule_hint_label")
        self._hint_label.setStyleSheet(theme.CAPTION_STYLE)
        self._hint_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._exact_mass_label = QLabel()
        self._exact_mass_label.setObjectName("molecule_exact_mass_label")
        self._charge_label = QLabel()
        self._charge_label.setObjectName("molecule_charge_label")
        self._dbe_label = QLabel()
        self._dbe_label.setObjectName("molecule_dbe_label")
        self._dbe_label.setToolTip(tr("Double bond equivalents: rings + π bonds"))
        self._warning_label = QLabel()
        self._warning_label.setObjectName("molecule_warning_label")
        self._warning_label.setStyleSheet(
            f"color: {theme.DANGER}; background: {theme.DANGER_SOFT}; border-radius: 4px; "
            "padding: 1px 6px; font-weight: 600;"
        )
        for info_label in (self._formula_label, self._mw_label):
            info_label.setStyleSheet(f"color: {theme.TEXT}; font-weight: 600;")
        for info_label in (self._exact_mass_label, self._charge_label, self._dbe_label):
            info_label.setStyleSheet(f"color: {theme.TEXT};")
        self._live_smiles_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        info.addWidget(self._formula_label)
        info.addWidget(self._mw_label)
        info.addWidget(self._exact_mass_label)
        info.addWidget(self._charge_label)
        info.addWidget(self._dbe_label)
        info.addStretch(1)
        info.addWidget(self._warning_label)
        vbox.addLayout(info)
        info2 = QHBoxLayout()
        info2.setSpacing(14)
        info2.addWidget(self._live_smiles_label, 2)
        info2.addWidget(self._hint_label, 3)
        vbox.addLayout(info2)

        self._update_info_bar()
        self._sync_palette(self._canvas.tool())
        return container

    def _action_button(self, icon: QIcon, label: str, key: str) -> QToolButton:
        tooltip = f"{label} ({key})" if key else label
        button = _palette_button(tooltip=tooltip, checkable=False)
        button.setIcon(icon)
        button.setIconSize(QSize(20, 20))
        button.setFixedSize(34, 34)
        return button

    def _build_left_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("molSidePanel")
        panel.setFixedWidth(196)
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(4, 4, 4, 4)
        self._left_tabs = QTabWidget()
        self._left_tabs.setObjectName("molecule_template_tabs")
        self._left_tabs.setDocumentMode(True)
        self._left_tabs.setUsesScrollButtons(False)
        self._left_tabs.tabBar().setExpanding(True)
        self._left_tabs.setStyleSheet(
            "QTabBar::tab { padding: 4px 4px; min-width: 0px; margin: 0px; }"
        )
        self._left_tabs.addTab(self._build_templates_page(), tr("Templates"))
        self._left_tabs.addTab(self._build_salts_page(), tr("Salts"))
        self._left_tabs.addTab(self._build_custom_page(), tr("Custom"))
        outer.addWidget(self._left_tabs)
        return panel

    def _build_templates_page(self) -> QWidget:
        page = QWidget()
        vbox = QVBoxLayout(page)
        vbox.setContentsMargins(4, 4, 4, 4)
        vbox.setSpacing(4)

        vbox.addWidget(_section_label(tr("Rings")))
        vbox.addLayout(self._ring_grid(_RING_BUTTONS))
        vbox.addSpacing(6)
        vbox.addWidget(_section_label(tr("O/N rings, chairs and sugars")))
        vbox.addLayout(self._ring_grid(_HETEROCYCLE_BUTTONS))

        vbox.addSpacing(6)
        vbox.addWidget(_section_label(tr("IR Groups")))
        groups = QGridLayout()
        groups.setSpacing(4)
        for i, (key, label) in enumerate(_GROUP_BUTTONS):
            button = _palette_button(
                label, tooltip=tr("Attach {group} to an atom").format(group=label)
            )
            button.setFixedHeight(28)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda _checked=False, g=key: self._canvas.set_group(g))
            self._palette_group.addButton(button)
            self._group_buttons[key] = button
            groups.addWidget(button, i // 2, i % 2)
        vbox.addLayout(groups)
        vbox.addStretch(1)
        scroll = QScrollArea()
        scroll.setObjectName("molecule_templates_scroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(page)
        return scroll

    def _ring_grid(self, items: tuple[tuple[str, str], ...]) -> QGridLayout:
        grid = QGridLayout()
        grid.setSpacing(4)
        for i, (ring_type, label) in enumerate(items):
            button = _palette_button(tooltip=tr(label))
            button.setIcon(_ring_icon(ring_type, 40))
            button.setIconSize(QSize(40, 40))
            button.setFixedSize(52, 48)
            button.clicked.connect(
                lambda _checked=False, r=ring_type: self._canvas.set_ring_type(r)
            )
            self._palette_group.addButton(button)
            self._ring_buttons[ring_type] = button
            grid.addWidget(button, i // 3, i % 3)
        return grid

    def _build_salts_page(self) -> QWidget:
        page = QWidget()
        vbox = QVBoxLayout(page)
        vbox.setContentsMargins(4, 4, 4, 4)
        vbox.setSpacing(4)
        caption = QLabel(tr("Click, then click in the drawing to add a counter-ion or solvent."))
        caption.setWordWrap(True)
        caption.setStyleSheet(theme.CAPTION_STYLE)
        vbox.addWidget(caption)
        grid = QGridLayout()
        grid.setSpacing(4)
        for i, (label, smiles) in enumerate(SALTS_AND_SOLVENTS):
            button = _palette_button(label, tooltip=smiles, checkable=False)
            button.setFixedHeight(28)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.clicked.connect(
                lambda _checked=False, lab=label, smi=smiles: self._place_salt(lab, smi)
            )
            self._salt_buttons[label] = button
            grid.addWidget(button, i // 3, i % 3)
        vbox.addLayout(grid)
        vbox.addStretch(1)
        return page

    def _build_custom_page(self) -> QWidget:
        page = QWidget()
        vbox = QVBoxLayout(page)
        vbox.setContentsMargins(4, 4, 4, 4)
        vbox.setSpacing(4)
        caption = QLabel(
            tr("Abbreviation, condensed formula or SMILES; * marks where it attaches.")
        )
        caption.setWordWrap(True)
        caption.setStyleSheet(theme.CAPTION_STYLE)
        vbox.addWidget(caption)
        self._group_input = QLineEdit()
        self._group_input.setObjectName("molecule_group_input")
        self._group_input.setPlaceholderText("OMe, CH2CH2OH, *OCC(C)C")
        self._group_input.textChanged.connect(self._on_group_input_changed)
        self._group_input.returnPressed.connect(self._on_group_place)
        vbox.addWidget(self._group_input)
        self._group_status = QLabel()
        self._group_status.setObjectName("molecule_group_status")
        self._group_status.setWordWrap(True)
        self._group_status.setStyleSheet(theme.CAPTION_STYLE)
        vbox.addWidget(self._group_status)
        row = QHBoxLayout()
        row.setSpacing(4)
        self._group_place_btn = QPushButton(tr("Place"))
        self._group_place_btn.setToolTip(tr("Attach to the atom you click next"))
        self._group_place_btn.clicked.connect(self._on_group_place)
        self._group_save_btn = QPushButton(tr("Save…"))
        self._group_save_btn.setToolTip(tr("Keep this group in the list below"))
        self._group_save_btn.clicked.connect(self._on_group_save)
        for button in (self._group_place_btn, self._group_save_btn):
            button.setEnabled(False)
            row.addWidget(button)
        vbox.addLayout(row)

        vbox.addSpacing(6)
        vbox.addWidget(_section_label(tr("Saved groups")))
        self._custom_list = QListWidget()
        self._custom_list.setObjectName("molecule_custom_groups")
        self._custom_list.itemClicked.connect(self._on_custom_item_clicked)
        vbox.addWidget(self._custom_list, 1)
        self._custom_remove_btn = QPushButton(tr("Remove"))
        self._custom_remove_btn.clicked.connect(self._on_custom_remove)
        vbox.addWidget(self._custom_remove_btn)
        tip = QLabel(tr("Tip: select atoms, right-click and choose Save as custom group."))
        tip.setWordWrap(True)
        tip.setStyleSheet(theme.CAPTION_STYLE)
        vbox.addWidget(tip)
        self._refresh_custom_groups()
        return page

    def _build_more_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.setObjectName("molecule_more_menu")
        menu.addAction(tr("Copy SMILES"), lambda: self._copy_text("smiles"))
        menu.addAction(tr("Copy MOL block"), lambda: self._copy_text("mol"))
        menu.addAction(tr("Copy InChI"), lambda: self._copy_text("inchi"))
        menu.addAction(tr("Copy InChIKey"), lambda: self._copy_text("inchikey"))
        menu.addAction(tr("Copy as image"), self._copy_image)
        menu.addSeparator()
        menu.addAction(tr("Open MOL/SDF file…"), self._open_mol_file)
        menu.addAction(tr("Save MOL file…"), self._save_mol_file)
        menu.addSeparator()
        menu.addAction(tr("Show all hydrogens"), self._canvas.add_explicit_hydrogens)
        menu.addAction(tr("Hide explicit hydrogens"), self._canvas.remove_explicit_hydrogens)
        return menu

    def _build_right_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("molSidePanel")
        panel.setFixedWidth(108)
        vbox = QVBoxLayout(panel)
        vbox.setContentsMargins(8, 6, 8, 8)
        vbox.setSpacing(4)

        vbox.addWidget(_section_label(tr("Elements")))
        grid = QGridLayout()
        grid.setSpacing(4)
        for i, symbol in enumerate(_ELEMENT_BUTTONS):
            button = _palette_button(
                symbol, tooltip=tr("Draw {element} atoms").format(element=symbol)
            )
            button.setFixedSize(42, 28)
            color = element_color(symbol).name()
            button.setStyleSheet(
                f"QToolButton#molPaletteButton {{ color: {color}; font-weight: 700; }}"
            )
            button.clicked.connect(lambda _checked=False, s=symbol: self._canvas.set_atom_symbol(s))
            self._palette_group.addButton(button)
            self._element_buttons[symbol] = button
            grid.addWidget(button, i // 2, i % 2)
        vbox.addLayout(grid)

        self._periodic_btn = _palette_button(
            tr("PT…"), tooltip=tr("Periodic table"), checkable=False
        )
        self._periodic_btn.setFixedHeight(28)
        self._periodic_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._periodic_btn.clicked.connect(self._on_periodic_table)
        vbox.addWidget(self._periodic_btn)

        vbox.addSpacing(6)
        vbox.addWidget(_section_label(tr("Charge")))
        charges = QHBoxLayout()
        charges.setSpacing(4)
        self._charge_plus_btn = _palette_button(
            "+", tooltip=tr("Increase charge (+)"), checkable=False
        )
        self._charge_minus_btn = _palette_button(
            "−", tooltip=tr("Decrease charge (−)"), checkable=False
        )
        for button, delta in ((self._charge_plus_btn, 1), (self._charge_minus_btn, -1)):
            button.setFixedSize(42, 28)
            button.clicked.connect(lambda _checked=False, d=delta: self._canvas.adjust_charge(d))
            charges.addWidget(button)
        vbox.addLayout(charges)
        vbox.addStretch(1)
        return panel

    def _build_smiles_tab(self) -> QWidget:
        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(8, 8, 8, 8)
        vbox.setSpacing(6)

        # Input row
        input_row = QHBoxLayout()
        self._smiles_input = QLineEdit()
        self._smiles_input.setPlaceholderText(tr("Enter SMILES (e.g. CCO)"))
        if self._initial_smiles:
            self._smiles_input.setText(self._initial_smiles)
        self._preview_btn = QPushButton(tr("Preview"))
        input_row.addWidget(self._smiles_input)
        input_row.addWidget(self._preview_btn)
        vbox.addLayout(input_row)

        # Status label
        self._smiles_status = QLabel("")
        vbox.addWidget(self._smiles_status)

        # Preview image
        self._smiles_preview = QLabel(tr("Enter SMILES to preview"))
        self._smiles_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._smiles_preview.setMinimumSize(300, 300)
        self._smiles_preview.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._smiles_preview.setStyleSheet(
            f"background: {theme.SURFACE}; border: 1px solid {theme.BORDER}; border-radius: 6px;"
        )
        vbox.addWidget(self._smiles_preview)

        # Trigger initial preview if SMILES provided
        if self._initial_smiles:
            self._update_smiles_preview(self._initial_smiles)

        return container

    # ------------------------------------------------------------------
    # Signal connections & initial state
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        self._preview_btn.clicked.connect(self._on_preview_clicked)
        self._smiles_input.returnPressed.connect(self._on_preview_clicked)
        self._canvas.structure_changed.connect(self._on_canvas_changed)
        self._canvas.tool_changed.connect(self._sync_palette)
        self._canvas.hint_changed.connect(self._hint_label.setText)
        self._canvas.save_group_requested.connect(self._on_save_group_requested)
        self._tabs.currentChanged.connect(self._on_tab_changed)

    def _load_initial_structure(self) -> None:
        """Prefer the stored MOL block: it keeps the exact 2D layout drawn last time."""
        if self._initial_mol_block and self._canvas.load_mol_block(self._initial_mol_block):
            self._initial_mol_block_loaded = True
        elif self._initial_smiles and not self._canvas.load_smiles(self._initial_smiles):
            self._smiles_status.setText(tr("Invalid SMILES"))
        # The SMILES field shows exactly what the caller passed in.
        self._smiles_input.setText(self._initial_smiles or self._canvas.to_smiles())
        self._synced_smiles = self._smiles_input.text().strip()
        self._update_info_bar()
        self._hint_label.setText(self._canvas.hint())

    def showEvent(self, event) -> None:  # noqa: N802, ANN001
        super().showEvent(event)
        if self._tabs.currentIndex() == 0:
            self._canvas.setFocus(Qt.FocusReason.OtherFocusReason)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_canvas_changed(self) -> None:
        if not self._loading:
            self._canvas_modified = True
        if self._syncing_from_text:
            # Keep the user's own spelling of the SMILES they just typed.
            self._synced_smiles = self._smiles_input.text().strip()
        else:
            smiles = self._canvas.to_smiles()
            self._smiles_input.blockSignals(True)
            self._smiles_input.setText(smiles)
            self._smiles_input.blockSignals(False)
            self._synced_smiles = smiles
        self._update_info_bar()

    def _update_info_bar(self) -> None:
        model = self._canvas.model()
        formula = model.display_formula() or "—"
        weight = model.molecular_weight()
        mw = f"{weight:.2f} g/mol" if weight else "—"
        smiles = model.to_smiles() or "—"
        self._formula_label.setText(tr("Formula: {formula}").format(formula=formula))
        self._mw_label.setText(tr("MW: {mw}").format(mw=mw))
        exact = model.exact_mass()
        self._exact_mass_label.setText(
            tr("Exact mass: {mass}").format(mass=f"{exact:.4f}" if exact else "—")
        )
        charge = model.net_charge()
        self._charge_label.setText(
            tr("Charge: {charge}").format(charge=f"{charge:+d}" if charge else "0")
        )
        self._dbe_label.setText(tr("DBE: {dbe}").format(dbe=model.unsaturation()))
        problems = self._problem_messages()
        self._warning_label.setVisible(bool(problems))
        self._warning_label.setText(
            "⚠ " + tr("{count} to check").format(count=len(problems)) if problems else ""
        )
        self._warning_label.setToolTip("\n".join(problems))
        self._live_smiles_label.setText(f"SMILES: {smiles}")
        self._live_smiles_label.setToolTip(smiles)
        self._undo_btn.setEnabled(model.can_undo())
        self._redo_btn.setEnabled(model.can_redo())
        self._clean_btn.setEnabled(not model.is_empty())

    def _problem_messages(self) -> list[str]:
        model = self._canvas.model()
        messages = []
        for kind, atom in model.structure_problems():
            if atom is None:
                continue
            where = tr("Atom {n} ({symbol})").format(n=atom + 1, symbol=model.atom_symbol(atom))
            if kind == "valence":
                messages.append(tr("{where}: too many bonds for this element").format(where=where))
            elif kind == "radical":
                messages.append(tr("{where}: unpaired electron (radical)").format(where=where))
        return messages

    # -- salts & custom groups -----------------------------------------

    def _place_salt(self, label: str, smiles: str) -> None:
        fragment = fragment_from_smiles(smiles, label=label)
        if fragment is None:
            return
        fragment.attach = None  # always a separate molecule / ion
        self._canvas.begin_placement(fragment, label)
        self._canvas.setFocus(Qt.FocusReason.OtherFocusReason)

    def _custom_groups(self) -> dict[str, str]:
        return self._group_store.groups() if self._group_store is not None else {}

    def _refresh_custom_groups(self) -> None:
        groups = self._custom_groups()
        self._canvas.set_custom_groups(groups)
        self._custom_list.clear()
        for name, smiles in sorted(groups.items(), key=lambda kv: kv[0].lower()):
            item = QListWidgetItem(name)
            item.setToolTip(smiles)
            item.setData(Qt.ItemDataRole.UserRole, smiles)
            self._custom_list.addItem(item)
        self._custom_remove_btn.setEnabled(bool(groups))

    def _parse_group_input(self) -> Fragment | None:
        return parse_group(self._group_input.text(), self._custom_groups())

    def _on_group_input_changed(self, text: str) -> None:
        fragment = self._parse_group_input() if text.strip() else None
        valid = fragment is not None
        self._group_place_btn.setEnabled(valid)
        self._group_save_btn.setEnabled(valid and self._group_store is not None)
        if not text.strip():
            self._group_status.setText("")
        elif fragment is None:
            self._group_status.setText(tr("Not recognised"))
        else:
            self._group_status.setText(fragment_to_group_smiles(fragment))

    def _on_group_place(self) -> None:
        fragment = self._parse_group_input()
        if fragment is None:
            return
        self._canvas.begin_placement(fragment, self._group_input.text().strip())
        self._canvas.setFocus(Qt.FocusReason.OtherFocusReason)

    def _ask_group_name(self, default: str) -> str:
        name, ok = QInputDialog.getText(
            self, tr("Save Custom Group"), tr("Name of the group:"), text=default
        )
        return str(name).strip() if ok else ""

    def _store_group(self, name: str, fragment: Fragment) -> bool:
        if self._group_store is None or not name:
            return False
        try:
            self._group_store.save(name, fragment_to_group_smiles(fragment))
        except (OSError, ValueError):
            self._group_status.setText(tr("The group could not be saved"))
            return False
        self._refresh_custom_groups()
        self._left_tabs.setCurrentIndex(2)
        return True

    def _on_group_save(self) -> None:
        fragment = self._parse_group_input()
        if fragment is None:
            return
        name = self._ask_group_name(self._group_input.text().strip().lstrip("*"))
        self._store_group(name, fragment)

    def _on_save_group_requested(self, fragment: object) -> None:
        if not isinstance(fragment, Fragment):
            return
        name = self._ask_group_name("")
        self._store_group(name, fragment)

    def _on_custom_item_clicked(self, item: QListWidgetItem) -> None:
        fragment = fragment_from_smiles(str(item.data(Qt.ItemDataRole.UserRole)), label=item.text())
        if fragment is None:
            return
        self._canvas.begin_placement(fragment, item.text())
        self._canvas.setFocus(Qt.FocusReason.OtherFocusReason)

    def _on_custom_remove(self) -> None:
        item = self._custom_list.currentItem()
        if item is None or self._group_store is None:
            return
        try:
            self._group_store.remove(item.text())
        except OSError:
            return
        self._refresh_custom_groups()

    # -- export / import -----------------------------------------------

    def _copy_text(self, kind: str) -> str:
        model = self._canvas.model()
        if kind == "smiles":
            text = model.to_smiles()
        elif kind == "mol":
            text = model.to_mol_block()
        else:
            inchi, key = model.inchi()
            text = inchi if kind == "inchi" else key
        if text:
            QGuiApplication.clipboard().setText(text)
        return text

    def _copy_image(self) -> bool:
        png = self._canvas.render_to_png_bytes(800, 600)
        if not png:
            return False
        QGuiApplication.clipboard().setImage(QImage.fromData(png))
        return True

    def _open_mol_file(self) -> bool:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("Open Structure"), "", tr("MOL / SDF files (*.mol *.sdf *.sd);;All files (*)")
        )
        if not path:
            return False
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            self._hint_label.setText(tr("The file could not be read"))
            return False
        if not self._canvas.replace_mol_block(_first_mol_record(text)):
            self._hint_label.setText(tr("The file holds no readable structure"))
            return False
        return True

    def _save_mol_file(self) -> bool:
        mol_block = self._canvas.to_mol_block()
        if not mol_block:
            return False
        path, _ = QFileDialog.getSaveFileName(
            self, tr("Save Structure"), "structure.mol", tr("MOL files (*.mol)")
        )
        if not path:
            return False
        try:
            Path(path).write_text(mol_block, encoding="utf-8")
        except OSError:
            self._hint_label.setText(tr("The file could not be saved"))
            return False
        return True

    def _sync_palette(self, tool: str) -> None:
        """Check the palette button that matches the canvas' active tool."""
        target: QToolButton | None
        if tool == "ring":
            target = self._ring_buttons.get(self._canvas.ring_type())
        elif tool == "group":
            target = self._group_buttons.get(self._canvas.group_key())
        elif tool == "atom":
            target = self._element_buttons.get(self._canvas.atom_symbol())
        else:
            target = self._tool_buttons.get(tool)
        if target is not None:
            target.setChecked(True)
            return
        checked = self._palette_group.checkedButton()
        if checked is not None:
            self._palette_group.setExclusive(False)
            checked.setChecked(False)
            self._palette_group.setExclusive(True)

    def _on_periodic_table(self) -> None:
        symbol = PeriodicTableDialog.get_element(self)
        if symbol:
            self._canvas.set_atom_symbol(symbol)
            self._sync_palette("atom")
        self._canvas.setFocus(Qt.FocusReason.OtherFocusReason)

    def _on_tab_changed(self, index: int) -> None:
        if index == 0:
            self._sync_smiles_to_canvas()
            self._canvas.setFocus(Qt.FocusReason.OtherFocusReason)
        else:
            text = self._smiles_input.text().strip()
            if text:
                self._update_smiles_preview(text)

    def _sync_smiles_to_canvas(self) -> bool:
        """Load the SMILES field into the canvas if it changed since the last sync."""
        text = self._smiles_input.text().strip()
        if text == self._synced_smiles:
            return True
        self._syncing_from_text = True
        try:
            if not text:
                self._canvas.clear()
                self._synced_smiles = ""
                return True
            if not self._canvas.replace_smiles(text):
                self._smiles_status.setText(tr("Invalid SMILES"))
                return False
        finally:
            self._syncing_from_text = False
        self._synced_smiles = text
        return True

    def _on_preview_clicked(self) -> None:
        smiles = self._smiles_input.text().strip()
        if self._update_smiles_preview(smiles) and smiles:
            self._sync_smiles_to_canvas()

    def _update_smiles_preview(self, smiles: str) -> bool:
        if not smiles:
            self._smiles_preview.setPixmap(QPixmap())
            self._smiles_preview.setText(tr("Enter SMILES to preview"))
            self._smiles_status.setText("")
            return True

        try:
            from chemistry.structure_renderer import render_smiles_to_png  # noqa: PLC0415

            png_bytes = render_smiles_to_png(smiles, (300, 300))
        except Exception:  # noqa: BLE001
            png_bytes = None
            self._smiles_status.setText(tr("RDKit not installed"))
            self._smiles_preview.setPixmap(QPixmap())
            self._smiles_preview.setText(tr("Enter SMILES to preview"))
            return False

        if png_bytes is None:
            self._smiles_status.setText(tr("Invalid SMILES"))
            self._smiles_preview.setPixmap(QPixmap())
            self._smiles_preview.setText(tr("Enter SMILES to preview"))
            return False
        self._smiles_status.setText(tr("Valid"))
        image = QImage.fromData(png_bytes)
        pixmap = QPixmap.fromImage(image)
        self._smiles_preview.setPixmap(
            pixmap.scaled(
                self._smiles_preview.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        return True

    def _structure_mol_block(self) -> str:
        """MOL block for the canvas, keeping the caller's layout when untouched."""
        if not self._canvas_modified and self._initial_mol_block_loaded:
            return self._initial_mol_block
        return self._canvas.to_mol_block()

    def _on_ok(self) -> None:
        """Collect the structure from the active tab and accept the dialog."""
        if self._tabs.currentIndex() == 0:
            if self._canvas_modified:
                self._accepted_smiles = self._canvas.to_smiles()
            else:
                # Untouched: return the caller's SMILES verbatim so merely
                # opening the editor never registers as a change.
                self._accepted_smiles = self._initial_smiles or self._canvas.to_smiles()
            self._canvas_mol_block = self._structure_mol_block()
            self._canvas_png_bytes = self._canvas.render_to_png_bytes()
        else:
            candidate = self._smiles_input.text().strip()
            # The text may have changed since Preview was last clicked. Validate
            # the exact value that would be committed; an empty value remains a
            # valid request to clear the current structure.
            if not self._update_smiles_preview(candidate):
                self._tabs.setCurrentIndex(1)
                return
            self._accepted_smiles = candidate
            if not candidate:
                self._canvas_mol_block = ""
                self._canvas_png_bytes = b""
            elif candidate == self._synced_smiles:
                self._canvas_mol_block = self._structure_mol_block()
                self._canvas_png_bytes = self._canvas.render_to_png_bytes()
            else:
                try:
                    self._canvas_mol_block = MolEditorModel.from_smiles(candidate).to_mol_block()
                except ValueError:
                    self._canvas_mol_block = ""
                self._canvas_png_bytes = b""
        self.accept()

    def _on_clear(self) -> None:
        """Clear the structure in the active tab."""
        if self._tabs.currentIndex() == 0:
            self._canvas.clear()
        else:
            self._smiles_input.clear()
            self._smiles_preview.setText(tr("Enter SMILES to preview"))
            self._smiles_preview.setPixmap(QPixmap())
            self._smiles_status.setText("")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def smiles(self) -> str:
        """Return the SMILES committed when the dialog was accepted."""
        return self._accepted_smiles

    def png_bytes(self) -> bytes:
        """Return a PNG rendering of the accepted structure (empty bytes if not available)."""
        return self._canvas_png_bytes

    def mol_block(self) -> str:
        """Return the MOL V2000 block of the accepted structure (empty if unavailable)."""
        return self._canvas_mol_block
