"""
MoleculeEditorDialog — Dialog for editing molecular structures.

Provides two tabs:
  - Draw: native 2D structure editor (QPainter canvas over RDKit), fully offline
  - SMILES: text-based input with live RDKit preview

Both tabs stay in sync: edits on the canvas update the SMILES field, and a
valid SMILES typed on the SMILES tab is loaded into the canvas when the user
clicks *Preview* or switches back to *Draw*.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from chemistry.mol_editor_model import MolEditorModel
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
    ("furan", "Furan"),
    ("thiophene", "Thiophene"),
    ("pyrrole", "Pyrrole"),
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
    elif tool == "bond_wedge":
        painter.setBrush(QColor(theme.TEXT))
        painter.drawPolygon(QPolygonF([a, QPointF(16.5, 3.5), QPointF(20.5, 7.5)]))
    elif tool == "bond_hash":
        for k in range(1, 7):
            t = k / 6
            cx, cy = 5 + 14 * t, 19 - 14 * t
            h = 0.6 + 2.8 * t
            painter.drawLine(QPointF(cx - h, cy - h), QPointF(cx + h, cy + h))
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
        if symbol == "C":
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
        self._live_smiles_label = QLabel()
        self._live_smiles_label.setObjectName("molecule_live_smiles_label")
        self._live_smiles_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._live_smiles_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self._hint_label = QLabel()
        self._hint_label.setObjectName("molecule_hint_label")
        self._hint_label.setStyleSheet(theme.CAPTION_STYLE)
        self._hint_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._hint_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        for info_label in (self._formula_label, self._mw_label):
            info_label.setStyleSheet(f"color: {theme.TEXT}; font-weight: 600;")
        self._live_smiles_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        info.addWidget(self._formula_label)
        info.addWidget(self._mw_label)
        info.addWidget(self._live_smiles_label, 2)
        info.addWidget(self._hint_label, 3)
        vbox.addLayout(info)

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
        panel.setFixedWidth(176)
        vbox = QVBoxLayout(panel)
        vbox.setContentsMargins(8, 6, 8, 8)
        vbox.setSpacing(4)

        vbox.addWidget(_section_label(tr("Rings")))
        rings = QGridLayout()
        rings.setSpacing(4)
        for i, (ring_type, label) in enumerate(_RING_BUTTONS):
            button = _palette_button(tooltip=tr(label))
            button.setIcon(_ring_icon(ring_type))
            button.setIconSize(QSize(34, 34))
            button.setFixedSize(48, 44)
            button.clicked.connect(
                lambda _checked=False, r=ring_type: self._canvas.set_ring_type(r)
            )
            self._palette_group.addButton(button)
            self._ring_buttons[ring_type] = button
            rings.addWidget(button, i // 3, i % 3)
        vbox.addLayout(rings)

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
        return panel

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
        formula = model.molecular_formula() or "—"
        weight = model.molecular_weight()
        mw = f"{weight:.2f} g/mol" if weight else "—"
        smiles = model.to_smiles() or "—"
        self._formula_label.setText(tr("Formula: {formula}").format(formula=formula))
        self._mw_label.setText(tr("MW: {mw}").format(mw=mw))
        self._live_smiles_label.setText(f"SMILES: {smiles}")
        self._live_smiles_label.setToolTip(smiles)
        self._undo_btn.setEnabled(model.can_undo())
        self._redo_btn.setEnabled(model.can_redo())
        self._clean_btn.setEnabled(not model.is_empty())

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
