"""Shared text editor helpers for vibration labels with scientific symbols."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

_GREEK_SYMBOLS: tuple[str, ...] = (
    "α",
    "β",
    "γ",
    "δ",
    "ε",
    "ζ",
    "η",
    "θ",
    "ι",
    "κ",
    "λ",
    "μ",
    "ν",
    "ξ",
    "π",
    "ρ",
    "σ",
    "τ",
    "φ",
    "χ",
    "ψ",
    "ω",
    "Δ",
)

_SUPERSCRIPT_MAP: dict[str, str] = {
    "0": "⁰",
    "1": "¹",
    "2": "²",
    "3": "³",
    "4": "⁴",
    "5": "⁵",
    "6": "⁶",
    "7": "⁷",
    "8": "⁸",
    "9": "⁹",
    "+": "⁺",
    "-": "⁻",
    "=": "⁼",
    "(": "⁽",
    ")": "⁾",
    "a": "ᵃ",
    "b": "ᵇ",
    "c": "ᶜ",
    "d": "ᵈ",
    "e": "ᵉ",
    "f": "ᶠ",
    "g": "ᵍ",
    "h": "ʰ",
    "i": "ⁱ",
    "j": "ʲ",
    "k": "ᵏ",
    "l": "ˡ",
    "m": "ᵐ",
    "n": "ⁿ",
    "o": "ᵒ",
    "p": "ᵖ",
    "r": "ʳ",
    "s": "ˢ",
    "t": "ᵗ",
    "u": "ᵘ",
    "v": "ᵛ",
    "w": "ʷ",
    "x": "ˣ",
    "y": "ʸ",
    "z": "ᶻ",
}

_SUBSCRIPT_MAP: dict[str, str] = {
    "0": "₀",
    "1": "₁",
    "2": "₂",
    "3": "₃",
    "4": "₄",
    "5": "₅",
    "6": "₆",
    "7": "₇",
    "8": "₈",
    "9": "₉",
    "+": "₊",
    "-": "₋",
    "=": "₌",
    "(": "₍",
    ")": "₎",
    "a": "ₐ",
    "e": "ₑ",
    "h": "ₕ",
    "i": "ᵢ",
    "j": "ⱼ",
    "k": "ₖ",
    "l": "ₗ",
    "m": "ₘ",
    "n": "ₙ",
    "o": "ₒ",
    "p": "ₚ",
    "r": "ᵣ",
    "s": "ₛ",
    "t": "ₜ",
    "u": "ᵤ",
    "v": "ᵥ",
    "x": "ₓ",
    "β": "ᵦ",
    "γ": "ᵧ",
    "ρ": "ᵨ",
    "φ": "ᵩ",
    "χ": "ᵪ",
}


def _convert_text(text: str, mapping: dict[str, str]) -> str:
    return "".join(mapping.get(char, mapping.get(char.lower(), char)) for char in text)


class VibrationTextEdit(QWidget):
    """Single-line editor with helpers for Greek symbols and index conversion."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.line_edit = QLineEdit(self)
        layout.addWidget(self.line_edit, 1)

        greek_button = QToolButton(self)
        greek_button.setText("αβγ")
        greek_button.setToolTip("Insert Greek letters")
        greek_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        greek_button.setMenu(self._build_greek_menu(greek_button))
        layout.addWidget(greek_button)

        superscript_button = QToolButton(self)
        superscript_button.setText("x²")
        superscript_button.setToolTip(
            "Convert the selection, or previous character, to superscript"
        )
        superscript_button.clicked.connect(self.apply_superscript)
        layout.addWidget(superscript_button)

        subscript_button = QToolButton(self)
        subscript_button.setText("x₂")
        subscript_button.setToolTip("Convert the selection, or previous character, to subscript")
        subscript_button.clicked.connect(self.apply_subscript)
        layout.addWidget(subscript_button)

    def _build_greek_menu(self, parent: QWidget) -> QMenu:
        menu = QMenu(parent)
        for symbol in _GREEK_SYMBOLS:
            action = menu.addAction(symbol)
            action.triggered.connect(lambda _checked=False, value=symbol: self.insert_text(value))
        return menu

    def text(self) -> str:
        return self.line_edit.text()

    def set_text(self, text: str) -> None:
        self.line_edit.setText(text)

    def set_placeholder_text(self, text: str) -> None:
        self.line_edit.setPlaceholderText(text)

    def insert_text(self, text: str) -> None:
        self.line_edit.insert(text)

    def apply_superscript(self) -> None:
        self._apply_mapping(_SUPERSCRIPT_MAP)

    def apply_subscript(self) -> None:
        self._apply_mapping(_SUBSCRIPT_MAP)

    def _apply_mapping(self, mapping: dict[str, str]) -> None:
        start, original = self._current_target_text()
        if not original:
            return
        self._replace_text(start, len(original), _convert_text(original, mapping))

    def _current_target_text(self) -> tuple[int, str]:
        if self.line_edit.hasSelectedText():
            start = self.line_edit.selectionStart()
            return start, self.line_edit.selectedText()

        cursor = self.line_edit.cursorPosition()
        if cursor <= 0:
            return 0, ""
        start = cursor - 1
        text = self.line_edit.text()
        return start, text[start:cursor]

    def _replace_text(self, start: int, length: int, replacement: str) -> None:
        current = self.line_edit.text()
        updated = current[:start] + replacement + current[start + length :]
        self.line_edit.setText(updated)
        self.line_edit.setCursorPosition(start + len(replacement))


class VibrationTextEditDialog(QDialog):
    """Dialog for editing a vibration label with scientific symbols."""

    def __init__(
        self,
        parent=None,
        *,
        title: str = "Edit Vibration",
        label: str = "Vibration:",
        text: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._editor = VibrationTextEdit(self)
        self._editor.set_text(text)
        form.addRow(label, self._editor)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def value(self) -> str:
        return self._editor.text()
