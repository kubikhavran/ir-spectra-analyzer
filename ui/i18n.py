"""
I18n — Jazyk uživatelského rozhraní.

Zodpovědnost:
- Přepínání mezi angličtinou a češtinou
- ``tr("English text")`` vrací text v aktivním jazyce; pro angličtinu a pro
  text bez překladu vrací vstup beze změny
- Překlad statických textů hotového okna jedním průchodem (``translate_tree``),
  aby dialogy nemusely obalovat každý řetězec zvlášť

Angličtina je zdrojový jazyk i výchozí stav modulu: bez explicitního
``set_language("cs")`` se nic nepřekládá, takže kód i testy, které o jazyku
nevědí, se chovají přesně jako dřív.

Chemické názvy (předvolby vibrací, funkční skupiny z knowledge base) se
nepřekládají — jsou to data, stejná v aplikaci i v reportu.
"""

from __future__ import annotations

import os

ENGLISH = "en"
CZECH = "cs"
SYSTEM = "system"
LANGUAGES: tuple[tuple[str, str], ...] = (
    (SYSTEM, "System"),
    (ENGLISH, "English"),
    (CZECH, "Čeština"),
)
#: Environment override — used by the test suite to stay in English on a
#: machine whose system language is Czech.
ENV_VAR = "IR_SPECTRA_LANGUAGE"

_language = ENGLISH
_catalog: dict[str, str] = {}


def language() -> str:
    """The active UI language code."""
    return _language


def set_language(code: str) -> str:
    """Activate a language; anything but Czech means English. Returns the code."""
    global _language, _catalog  # noqa: PLW0603 — module-level state by design
    if code == CZECH:
        from ui.i18n_cs import CZECH_TEXTS  # noqa: PLC0415

        _language, _catalog = CZECH, CZECH_TEXTS
    else:
        _language, _catalog = ENGLISH, {}
    return _language


def resolve_language(setting: object) -> str:
    """Turn the stored preference into a concrete language.

    ``None``/"system" follows the operating system, so a Czech Windows starts
    in Czech without anybody opening a menu.
    """
    override = os.environ.get(ENV_VAR, "").strip().lower()
    if override in (ENGLISH, CZECH):
        return override
    if setting in (ENGLISH, CZECH):
        return str(setting)
    try:
        from PySide6.QtCore import QLocale  # noqa: PLC0415

        if QLocale.system().language() == QLocale.Language.Czech:
            return CZECH
    except Exception:  # noqa: BLE001 — never let locale detection stop a start-up
        pass
    return ENGLISH


def tr(text: str) -> str:
    """``text`` in the active language (unchanged when there is no translation)."""
    if not _catalog:
        return text
    return _catalog.get(text, text)


#: Item-data role under which a translated combo-box entry keeps its English text.
SOURCE_TEXT_ROLE = 0x0100 + 4711


def current_source_text(combo) -> str:
    """The English text of a combo box's current entry, whatever language it shows.

    Use this instead of ``currentText()`` wherever code decides something from
    the selected entry.
    """
    source = combo.itemData(combo.currentIndex(), SOURCE_TEXT_ROLE)
    return str(source) if isinstance(source, str) and source else str(combo.currentText())


def translate_tree(root) -> None:
    """Translate the static texts of ``root`` and everything inside it.

    Covers what a dialog shows without any code of its own knowing about
    languages: window titles, labels, buttons, check boxes, group boxes, tabs,
    table headers, combo items, placeholders, tooltips and menu/action texts.
    Texts with no catalog entry — file names, numbers, chemistry — are left
    alone, so running it twice, or on a widget built with ``tr`` already, is
    harmless.
    """
    if not _catalog:
        return
    from PySide6.QtGui import QAction  # noqa: PLC0415
    from PySide6.QtWidgets import (  # noqa: PLC0415
        QAbstractButton,
        QComboBox,
        QDockWidget,
        QGroupBox,
        QLabel,
        QLineEdit,
        QMenu,
        QTableWidget,
        QTabWidget,
        QWidget,
    )

    def _swap(getter, setter) -> None:
        try:
            current = getter()
        except (RuntimeError, TypeError):
            return
        if isinstance(current, str) and current in _catalog:
            setter(_catalog[current])

    widgets = [root, *root.findChildren(QWidget)] if isinstance(root, QWidget) else []
    for widget in widgets:
        _swap(widget.toolTip, widget.setToolTip)
        if widget.isWindow() or isinstance(widget, QDockWidget):
            _swap(widget.windowTitle, widget.setWindowTitle)
        if isinstance(widget, (QLabel, QAbstractButton)):
            _swap(widget.text, widget.setText)
        elif isinstance(widget, QGroupBox):
            _swap(widget.title, widget.setTitle)
        elif isinstance(widget, QLineEdit):
            _swap(widget.placeholderText, widget.setPlaceholderText)
        elif isinstance(widget, QMenu):
            _swap(widget.title, widget.setTitle)
        elif isinstance(widget, QComboBox):
            for index in range(widget.count()):
                text = widget.itemText(index)
                if text in _catalog:
                    # Code that branches on the chosen entry keeps working: the
                    # English source text travels with the item.
                    widget.setItemData(index, text, SOURCE_TEXT_ROLE)
                    widget.setItemText(index, _catalog[text])
        elif isinstance(widget, QTabWidget):
            for index in range(widget.count()):
                text = widget.tabText(index)
                if text in _catalog:
                    widget.setTabText(index, _catalog[text])
        if isinstance(widget, QTableWidget):
            for column in range(widget.columnCount()):
                item = widget.horizontalHeaderItem(column)
                if item is not None:
                    _swap(item.text, item.setText)

    for action in root.findChildren(QAction):
        _swap(action.text, action.setText)
        _swap(action.toolTip, action.setToolTip)
        _swap(action.statusTip, action.setStatusTip)
