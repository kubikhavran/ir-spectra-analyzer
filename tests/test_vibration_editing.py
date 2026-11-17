"""Editing vibrations: built-in and custom entries can be changed, removed and reset."""

from __future__ import annotations

import sqlite3

import pytest

from storage.database import Database


def _db(tmp_path, name: str = "vib.db") -> Database:
    db = Database(tmp_path / name)
    db.initialize()
    return db


def _builtin(db: Database, name: str) -> dict:
    return next(p for p in db.get_vibration_presets() if p["name"] == name)


# ── Seeding ──────────────────────────────────────────────────────────────────


def test_reopening_the_database_keeps_edits_and_removals(tmp_path) -> None:
    """Seeding used to replace the whole library whenever the count was not 168."""
    db = _db(tmp_path)
    edited = _builtin(db, "ν(OH) –OH isolated")
    removed = _builtin(db, "ν(OH) H₂O crystal")
    db.update_vibration_preset(
        edited["id"], name="ν(OH) free", range_min=3590.0, range_max=3660.0, category="stretch"
    )
    db.delete_vibration_preset(removed["id"])
    custom_id = db.add_vibration_preset("my band", 1000.0, 1100.0)
    db.close()

    reopened = _db(tmp_path)
    presets = reopened.get_vibration_presets()
    names = {p["name"] for p in presets}
    assert "ν(OH) free" in names
    assert "ν(OH) –OH isolated" not in names  # the edit was not undone
    assert "ν(OH) H₂O crystal" not in names  # the removal was not undone
    assert sum(1 for p in presets if p["is_builtin"] == 1) == 247
    kept = next(p for p in presets if p["name"] == "ν(OH) free")
    assert kept["id"] == edited["id"]
    assert (kept["typical_range_min"], kept["typical_range_max"]) == (3590.0, 3660.0)
    assert any(p["id"] == custom_id for p in presets)


def test_a_database_from_before_editing_gets_the_current_library(tmp_path) -> None:
    """An outdated built-in library in an old database is still brought up to date."""
    path = tmp_path / "old.db"
    db = Database(path)
    db.initialize()
    db.close()
    # Turn it into what an older version left behind: no seed version, an
    # incomplete built-in library, one custom entry.
    raw = sqlite3.connect(path)
    raw.execute("DELETE FROM app_meta")
    raw.execute("DELETE FROM vibration_presets WHERE is_builtin = 1 AND category = 'silyl'")
    raw.execute("UPDATE vibration_presets SET seed_name = NULL")
    raw.execute(
        "INSERT INTO vibration_presets (name, typical_range_min, typical_range_max, is_builtin) "
        "VALUES ('custom kept', 500, 600, 0)"
    )
    raw.commit()
    raw.close()

    upgraded = Database(path)
    upgraded.initialize()
    presets = upgraded.get_vibration_presets()
    builtin = [p for p in presets if p["is_builtin"] == 1]
    assert len(builtin) == 248
    assert all(p["seed_name"] == p["name"] for p in builtin)
    assert any(p["name"] == "custom kept" and p["is_builtin"] == 0 for p in presets)


def test_a_newer_catalog_only_adds_what_is_missing(tmp_path, monkeypatch) -> None:
    db = _db(tmp_path)
    edited = _builtin(db, "ν(OH) –OH isolated")
    db.update_vibration_preset(
        edited["id"], name="ν(OH) mine", range_min=3500.0, range_max=3700.0, category="stretch"
    )
    db.close()

    original = Database._builtin_vibration_catalog()
    extended = [*original, ("ν(new) added later", 2000.0, 2100.0, "stretch", "", "#000000")]
    monkeypatch.setattr(Database, "_builtin_vibration_catalog", staticmethod(lambda: extended))
    monkeypatch.setattr(
        Database, "_BUILTIN_VIBRATIONS_SEED_VERSION", Database._BUILTIN_VIBRATIONS_SEED_VERSION + 1
    )

    upgraded = _db(tmp_path)
    names = {p["name"] for p in upgraded.get_vibration_presets()}
    assert "ν(new) added later" in names
    assert "ν(OH) mine" in names
    assert "ν(OH) –OH isolated" not in names


# ── Update / delete / reset ──────────────────────────────────────────────────


def test_update_changes_any_preset_and_validates(tmp_path) -> None:
    db = _db(tmp_path)
    custom_id = db.add_vibration_preset("ν(X)", 1000.0, 1100.0)
    db.update_vibration_preset(
        custom_id,
        name="  ν(X) renamed ",
        range_min=1200.0,
        range_max=1150.0,  # given the wrong way round
        category="bend",
        description="note",
    )
    row = next(p for p in db.get_vibration_presets() if p["id"] == custom_id)
    assert row["name"] == "ν(X) renamed"
    assert (row["typical_range_min"], row["typical_range_max"]) == (1150.0, 1200.0)
    assert (row["category"], row["description"]) == ("bend", "note")
    assert row["color"] == "#4A90D9"  # untouched unless given

    with pytest.raises(ValueError, match="name"):
        db.update_vibration_preset(custom_id, name="   ", range_min=1.0, range_max=2.0)


def test_removing_a_builtin_hides_it_and_removing_a_custom_deletes_it(tmp_path) -> None:
    db = _db(tmp_path)
    builtin = _builtin(db, "ν(OH) –OH isolated")
    custom_id = db.add_vibration_preset("my band", 1000.0, 1100.0)

    db.delete_vibration_preset(builtin["id"])
    db.delete_vibration_preset(custom_id)

    ids = {p["id"] for p in db.get_vibration_presets()}
    assert builtin["id"] not in ids
    assert custom_id not in ids
    raw = db._conn.execute(
        "SELECT is_hidden FROM vibration_presets WHERE id = ?", (builtin["id"],)
    ).fetchone()
    assert raw[0] == 1  # still there, to be restored
    assert (
        db._conn.execute("SELECT 1 FROM vibration_presets WHERE id = ?", (custom_id,)).fetchone()
        is None
    )


def test_reset_restores_builtins_and_leaves_custom_alone(tmp_path) -> None:
    db = _db(tmp_path)
    edited = _builtin(db, "ν(OH) –OH isolated")
    removed = _builtin(db, "ν(OH) H₂O crystal")
    db.update_vibration_preset(
        edited["id"], name="changed", range_min=1.0, range_max=2.0, category="bend"
    )
    db.delete_vibration_preset(removed["id"])
    custom_id = db.add_vibration_preset("my band", 1000.0, 1100.0)

    assert db.reset_builtin_vibration_presets() == 2

    restored = _builtin(db, "ν(OH) –OH isolated")
    assert restored["id"] == edited["id"]  # ids survive, assignments stay valid
    assert (restored["typical_range_min"], restored["typical_range_max"]) == (3580.0, 3670.0)
    assert restored["category"] == "stretch"
    assert _builtin(db, "ν(OH) H₂O crystal")["id"] == removed["id"]
    presets = db.get_vibration_presets()
    assert sum(1 for p in presets if p["is_builtin"] == 1) == 248
    assert any(p["id"] == custom_id and p["name"] == "my band" for p in presets)
    assert db.reset_builtin_vibration_presets() == 0  # nothing left to restore


# ── Panel and main window ────────────────────────────────────────────────────

from unittest.mock import MagicMock  # noqa: E402

import numpy as np  # noqa: E402
from PySide6.QtWidgets import QDialog, QMessageBox  # noqa: E402

from core.peak import Peak  # noqa: E402
from core.project import Project  # noqa: E402
from core.spectrum import SpectralUnit, Spectrum  # noqa: E402
from core.vibration_presets import VibrationPreset  # noqa: E402
from ui.vibration_panel import VibrationPanel, _VibrationEditorDialog  # noqa: E402


def _window(qtbot, tmp_path):
    from storage.settings import Settings
    from ui.main_window import MainWindow

    db = _db(tmp_path, "window.db")
    settings = Settings(tmp_path / "settings.json")
    settings.load()
    window = MainWindow(db=db, settings=settings)

    def _discard(closing) -> None:
        closing._non_undo_dirty = False
        closing._undo_stack.setClean()

    qtbot.addWidget(window, before_close_func=_discard)
    return window, db


def test_editor_prefills_a_builtin_and_returns_the_edit(qtbot) -> None:
    preset = VibrationPreset(
        "ν(C=O) mine",
        1700.0,
        1750.0,
        category="stretch",
        description="lit.",
        db_id=5,
        seed_name="ν(C=O) ester",
    )
    dialog = _VibrationEditorDialog(preset=preset)
    qtbot.addWidget(dialog)
    assert dialog.windowTitle() == "Edit Vibration"
    values = dialog.values()
    assert values.name == "ν(C=O) mine"
    assert (values.range_min, values.range_max) == (1700.0, 1750.0)
    assert values.category == "stretch"
    assert values.description == "lit."

    dialog._name_edit.set_text("  ν(C=O) changed ")
    dialog._category_combo.setCurrentIndex(dialog._category_combo.findData("bend"))
    assert dialog.values().name == "ν(C=O) changed"
    assert dialog.values().category == "bend"

    unknown = _VibrationEditorDialog(preset=VibrationPreset("x", 1.0, 2.0, category="lab"))
    qtbot.addWidget(unknown)
    assert unknown.values().category == "lab"  # an unlisted category is kept


def test_panel_edits_deletes_and_resets_through_the_database(qtbot, monkeypatch) -> None:
    db = MagicMock()
    panel = VibrationPanel(db=db)
    qtbot.addWidget(panel)
    preset = VibrationPreset("ν(OH)", 3200.0, 3600.0, category="stretch", db_id=7)
    changed: list[int] = []
    deleted: list[int] = []
    panel.presets_changed.connect(lambda: changed.append(1))
    panel.preset_deleted.connect(lambda: deleted.append(1))

    monkeypatch.setattr(_VibrationEditorDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    assert panel.edit_preset(preset)
    db.update_vibration_preset.assert_called_once()
    assert db.update_vibration_preset.call_args.kwargs["name"] == "ν(OH)"
    assert changed == [1]

    monkeypatch.setattr(
        "ui.vibration_panel.QMessageBox.question",
        lambda *a, **k: QMessageBox.StandardButton.Cancel,
    )
    assert not panel.delete_preset(preset)
    assert not panel.reset_builtin_presets()
    db.delete_vibration_preset.assert_not_called()
    db.reset_builtin_vibration_presets.assert_not_called()

    monkeypatch.setattr(
        "ui.vibration_panel.QMessageBox.question",
        lambda *a, **k: QMessageBox.StandardButton.Yes,
    )
    assert panel.delete_preset(preset)
    db.delete_vibration_preset.assert_called_once_with(7)
    assert deleted == [1]
    assert panel.reset_builtin_presets()
    db.reset_builtin_vibration_presets.assert_called_once()
    assert changed == [1, 1]


def test_renaming_a_vibration_renames_it_on_the_peaks_that_carry_it(qtbot, tmp_path) -> None:
    window, db = _window(qtbot, tmp_path)
    wn = np.linspace(400.0, 4000.0, 1000)
    window._apply_project_to_ui(
        Project(
            name="p",
            spectrum=Spectrum(wn, np.zeros_like(wn) + 0.1, y_unit=SpectralUnit.ABSORBANCE),
        )
    )
    preset = next(p for p in window._vibration_presets_cache if p.name == "ν(OH) –OH isolated")
    assigned = Peak(
        position=3600.0,
        intensity=0.5,
        vibration_labels=["ν(OH) –OH isolated"],
        vibration_ids=[preset.db_id],
    )
    retyped = Peak(  # same id, but the analyst typed their own text — leave it
        position=3610.0,
        intensity=0.5,
        vibration_labels=["my own words"],
        vibration_ids=[preset.db_id],
    )
    window._project.add_peak(assigned)
    window._project.add_peak(retyped)
    window._refresh_peak_views()

    db.update_vibration_preset(
        preset.db_id,
        name="ν(OH) free",
        range_min=3580.0,
        range_max=3670.0,
        category="stretch",
    )
    window._vibration_panel.presets_changed.emit()

    assert assigned.vibration_labels == ["ν(OH) free"]
    assert retyped.vibration_labels == ["my own words"]
    assert window._has_unsaved_changes()
    texts = [window._peak_table._table.item(r, 3).text() for r in range(2)]
    assert "ν(OH) free" in texts

    # Reset brings the shipped name back — on the peak too.
    db.reset_builtin_vibration_presets()
    window._vibration_panel.presets_changed.emit()
    assert assigned.vibration_labels == ["ν(OH) –OH isolated"]


def test_suggestions_still_find_a_renamed_builtin(qtbot, tmp_path) -> None:
    """Functional-group suggestions name vibrations as shipped; a rename must not break them."""
    window, db = _window(qtbot, tmp_path)
    preset = next(p for p in window._vibration_presets_cache if p.name == "ν(OH) –OH isolated")
    db.update_vibration_preset(
        preset.db_id, name="ν(OH) free", range_min=3580.0, range_max=3670.0, category="stretch"
    )
    window._vibration_panel.presets_changed.emit()

    band = MagicMock()
    band.suggested_preset_names = ("ν(OH) –OH isolated",)
    found = window._find_best_preset_for_band(band, 3620.0)
    assert found is not None
    assert found.name == "ν(OH) free"
    assert found.catalog_name == "ν(OH) –OH isolated"


def test_f2_and_the_context_menu_offer_editing_for_builtins(qtbot) -> None:
    from PySide6.QtGui import QShortcut

    panel = VibrationPanel(db=MagicMock())
    qtbot.addWidget(panel)
    panel.set_presets([VibrationPreset("ν(OH)", 3200.0, 3600.0, db_id=1, is_builtin=True)])
    keys = {sc.key().toString() for sc in panel._list.findChildren(QShortcut)}
    assert "F2" in keys
