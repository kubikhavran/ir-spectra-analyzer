from __future__ import annotations

import sqlite3

import numpy as np

from storage.database import Database


def test_database_seeds_expanded_builtin_vibration_presets():
    database = Database(":memory:")
    database.initialize()

    presets = database.get_vibration_presets()
    builtin_names = {preset["name"] for preset in presets if preset["is_builtin"] == 1}

    assert len(builtin_names) == 204
    assert "ν(C=O) –COCl acid halide" in builtin_names
    assert "ν(C=O) anhydride asym." in builtin_names
    assert "ν(N₃) –N₃ azide" in builtin_names
    assert "ν(N=C=O) –N=C=O isocyanate" in builtin_names
    assert "ν(N=C=N) carbodiimide" in builtin_names
    assert "ν(N=C=S) –N=C=S isothiocyanate" in builtin_names
    assert "ν(C=C=O) ketene" in builtin_names
    assert "ν(CO) R–O–R aliph. ether" in builtin_names
    assert "ν(CO) Ar–O–R aryl ether" in builtin_names
    assert "ν(CO) CH₂=CH–O– vinyl ether" in builtin_names
    assert "ν(S=O) sulfoxide" in builtin_names
    assert "ν(C=N) R₂C=N–R imine" in builtin_names
    assert "ν(ring) oxirane breathing" in builtin_names
    assert "δs(Si–CH₃) silicone" in builtin_names
    assert "νas(Si–O–Si) siloxane" in builtin_names
    # Heteroaromatic and oxygen-heterocycle expansion
    assert "ν(C=N) pyridin ~1600" in builtin_names
    assert "γ(CH) pyridin 3-subst." in builtin_names
    assert "ν(C=N) imidazol" in builtin_names
    assert "ν(ring) triazol" in builtin_names
    assert "ν(NH) tetrazol assoc." in builtin_names
    assert "ν(ring) furan" in builtin_names
    assert "γ(CH) thiofen" in builtin_names
    assert "ν(NH) pyrrol/indol" in builtin_names
    assert "νas(C–O–C) cykl. ether" in builtin_names
    assert "ν(CH) O–CH₃" in builtin_names
    assert "ν(P=O) phosphoryl" in builtin_names
    assert "ν(P–O–C) aliph. phosphate" in builtin_names
    assert "δs(Si–CH₃) TMS/TBS" in builtin_names
    assert "ν(Si–O–C) silyl ether" in builtin_names
    assert "ν(Si–Ph) TBDPS" in builtin_names
    silyl = {p["name"] for p in presets if p.get("category") == "silyl"}
    assert len(silyl) == 15
    assert "νas(SO₂) sulfone" in builtin_names
    assert "νas(SO₃) sulfate" in builtin_names
    assert "νas(SO₃) sulfonate" in builtin_names
    assert "νs(SO₂) sulfonyl chloride" in builtin_names
    assert "ν(SH) thiol" in builtin_names

    database.close()


def test_database_enables_foreign_keys() -> None:
    database = Database(":memory:")
    database.initialize()

    assert database._conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1

    database.close()


def test_reference_source_prefix_escapes_sql_wildcards() -> None:
    clause, params = Database._reference_source_prefix_clause("c:/lab/reference library_1")
    database = Database(":memory:")
    database.initialize()
    connection = database._conn

    wildcard_sibling = "c:/lab/reference libraryx1/sample.spa"
    exact_descendant = "c:/lab/reference library_1/sample.spa"
    sql = f"SELECT CASE WHEN {clause} THEN 1 ELSE 0 END FROM (SELECT ? AS source_norm)"

    assert connection.execute(sql, (*params, wildcard_sibling)).fetchone()[0] == 0
    assert connection.execute(sql, (*params, exact_descendant)).fetchone()[0] == 1

    database.close()


def test_top_level_savepoint_preserves_commit_false_semantics() -> None:
    db = Database(":memory:")
    db.initialize()

    with db.savepoint():
        db.add_reference_spectrum(
            name="pending",
            wavenumbers=np.asarray([1000.0, 900.0]),
            intensities=np.asarray([0.1, 0.2]),
            commit=False,
        )

    assert db._conn is not None
    db._conn.rollback()

    assert db.get_reference_metadata() == []

    db.close()


def test_startup_migration_ignores_malformed_legacy_web_source(tmp_path) -> None:
    path = tmp_path / "legacy.db"
    db = Database(path)
    db.initialize()
    assert db._conn is not None
    db._conn.execute(
        """
        INSERT INTO reference_spectra (name, wavenumbers, intensities, source, source_norm)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("legacy", b"", b"", "https://", "keep-existing-normalization"),
    )
    db._conn.commit()
    db.close()

    reopened = Database(path)
    reopened.initialize()

    assert reopened.get_reference_identity_rows()[0]["source_norm"] == "keep-existing-normalization"
    reopened.close()


def test_startup_url_migration_preserves_duplicate_legacy_rows(tmp_path) -> None:
    path = tmp_path / "duplicates.db"
    db = Database(path)
    db.initialize()
    assert db._conn is not None
    values = [
        ("first", b"", b"", "https://example.test/spectrum", "legacy/one"),
        ("second", b"", b"", "https://example.test/spectrum", "legacy/two"),
    ]
    db._conn.executemany(
        """
        INSERT INTO reference_spectra (name, wavenumbers, intensities, source, source_norm)
        VALUES (?, ?, ?, ?, ?)
        """,
        values,
    )
    db._conn.commit()
    db.close()

    reopened = Database(path)
    reopened.initialize()
    rows = reopened.get_reference_identity_rows()

    assert len(rows) == 2
    assert {row["source_norm"] for row in rows} == {"https://example.test/spectrum"}
    reopened.close()


def test_startup_migrates_legacy_reference_features_foreign_key(tmp_path) -> None:
    path = tmp_path / "legacy-features.db"
    db = Database(path)
    db.initialize()
    ref_id = db.add_reference_spectrum(
        name="parent",
        wavenumbers=np.asarray([1000.0]),
        intensities=np.asarray([0.1]),
    )
    db.close()

    legacy = sqlite3.connect(path)
    legacy.executescript(
        """
        ALTER TABLE reference_features RENAME TO reference_features_current;
        CREATE TABLE reference_features (
            reference_id INTEGER NOT NULL,
            feature_version INTEGER NOT NULL,
            feature_vector BLOB NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (reference_id, feature_version)
        );
        INSERT INTO reference_features (reference_id, feature_version, feature_vector)
            VALUES (1, 1, X'01'), (999, 1, X'02');
        DROP TABLE reference_features_current;
        """
    )
    legacy.close()

    reopened = Database(path)
    reopened.initialize()
    assert reopened._conn is not None

    foreign_keys = reopened._conn.execute("PRAGMA foreign_key_list(reference_features)").fetchall()
    assert any(
        row["table"] == "reference_spectra"
        and row["from"] == "reference_id"
        and row["on_delete"] == "CASCADE"
        for row in foreign_keys
    )
    feature_ids = [
        row[0]
        for row in reopened._conn.execute("SELECT reference_id FROM reference_features").fetchall()
    ]
    assert feature_ids == [ref_id]

    reopened._conn.execute("DELETE FROM reference_spectra WHERE id = ?", (ref_id,))
    assert reopened._conn.execute("SELECT COUNT(*) FROM reference_features").fetchone()[0] == 0
    reopened.close()
