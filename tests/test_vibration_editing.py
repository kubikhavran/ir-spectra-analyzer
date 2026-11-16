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
    assert sum(1 for p in presets if p["is_builtin"] == 1) == 167
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
    assert len(builtin) == 168
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
    monkeypatch.setattr(Database, "_BUILTIN_VIBRATIONS_SEED_VERSION", 2)

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
    assert sum(1 for p in presets if p["is_builtin"] == 1) == 168
    assert any(p["id"] == custom_id and p["name"] == "my band" for p in presets)
    assert db.reset_builtin_vibration_presets() == 0  # nothing left to restore
