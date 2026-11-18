"""
Database — SQLite persistence pro projekty a vibrační předvolby.

Zodpovědnost:
- Inicializace schématu databáze
- CRUD operace pro Project, Peak, VibrationPreset, VibrationAssignment
- Migrace schématu (viz migrations.py)
- Výchozí sada vibračních předvoleb (seed data)

Schéma:
  - projects              — IR analytické projekty
  - peaks                 — detekované peaky projektu
  - vibration_presets     — předvolby vibrací (builtins + uživatelské)
  - vibration_assignments — přiřazení předvolby k peaku
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import numpy as np

from app.config import DB_PATH
from utils.file_utils import normalize_source_path, normalize_source_url


class Database:
    """SQLite database manager for IR Spectra Analyzer."""

    SCHEMA_VERSION = 1

    def __init__(self, db_path: str | Path = DB_PATH) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._savepoint_counter = 0

    def initialize(self) -> None:
        """Create data directory, open connection, apply schema, seed data."""
        db_path = str(self._db_path)
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._apply_schema()
        self._seed_vibration_presets()
        # SQLite leaves FK enforcement disabled by default. Enable it only after
        # legacy seed/schema maintenance so an old, unused project row cannot
        # prevent the application from opening; all runtime writes are guarded.
        self._conn.execute("PRAGMA foreign_keys = ON")
        if self._conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            raise RuntimeError("Could not enable SQLite foreign-key enforcement")

    def commit(self) -> None:
        """Commit the current transaction."""
        assert self._conn is not None
        self._conn.commit()

    @contextmanager
    def savepoint(self) -> Iterator[None]:
        """Rollback one logical write unit without discarding the outer batch."""
        assert self._conn is not None
        # A top-level SQLite SAVEPOINT commits when it is released. Start an
        # explicit outer transaction so callers' ``commit=False`` contract is
        # preserved and they can still roll back the completed logical unit.
        started_transaction = not self._conn.in_transaction
        if started_transaction:
            self._conn.execute("BEGIN")
        self._savepoint_counter += 1
        name = f"ir_item_{self._savepoint_counter}"
        self._conn.execute(f"SAVEPOINT {name}")
        try:
            yield
        except BaseException:
            self._conn.execute(f"ROLLBACK TO SAVEPOINT {name}")
            self._conn.execute(f"RELEASE SAVEPOINT {name}")
            if started_transaction:
                self._conn.rollback()
            raise
        else:
            self._conn.execute(f"RELEASE SAVEPOINT {name}")

    @property
    def db_path(self) -> str | Path:
        """Return the configured SQLite database path."""
        return self._db_path

    @property
    def is_in_memory(self) -> bool:
        """Return True when the database uses SQLite's in-memory mode."""
        return str(self._db_path) == ":memory:"

    def _apply_schema(self) -> None:
        """Create all tables if they do not exist."""
        assert self._conn is not None
        cursor = self._conn.cursor()
        cursor.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT    NOT NULL,
                spa_path      TEXT,
                created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
                updated_at    TEXT    NOT NULL DEFAULT (datetime('now')),
                metadata_json TEXT
            );

            CREATE TABLE IF NOT EXISTS peaks (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id       INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                position         REAL    NOT NULL,
                intensity        REAL    NOT NULL,
                label            TEXT    NOT NULL DEFAULT '',
                vibration_id     INTEGER REFERENCES vibration_presets(id),
                label_offset_x   REAL    NOT NULL DEFAULT 0.0,
                label_offset_y   REAL    NOT NULL DEFAULT 0.0,
                manual_placement INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS vibration_presets (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                name              TEXT    NOT NULL,
                typical_range_min REAL    NOT NULL,
                typical_range_max REAL    NOT NULL,
                category          TEXT    NOT NULL DEFAULT '',
                description       TEXT    NOT NULL DEFAULT '',
                color             TEXT    NOT NULL DEFAULT '#4A90D9'
            );

            CREATE TABLE IF NOT EXISTS vibration_assignments (
                peak_id             INTEGER NOT NULL REFERENCES peaks(id) ON DELETE CASCADE,
                vibration_preset_id INTEGER NOT NULL REFERENCES vibration_presets(id),
                notes               TEXT    NOT NULL DEFAULT '',
                PRIMARY KEY (peak_id, vibration_preset_id)
            );

            CREATE INDEX IF NOT EXISTS idx_peaks_project  ON peaks(project_id);
            CREATE INDEX IF NOT EXISTS idx_peaks_position ON peaks(position);

            CREATE TABLE IF NOT EXISTS reference_spectra (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                name           TEXT    NOT NULL,
                description    TEXT    NOT NULL DEFAULT '',
                source         TEXT    NOT NULL DEFAULT '',
                source_norm    TEXT    NOT NULL DEFAULT '',
                source_provider TEXT   NOT NULL DEFAULT 'local',
                external_id    TEXT    NOT NULL DEFAULT '',
                sample_state   TEXT    NOT NULL DEFAULT '',
                sampling_procedure TEXT NOT NULL DEFAULT '',
                path_length    TEXT    NOT NULL DEFAULT '',
                resolution     TEXT    NOT NULL DEFAULT '',
                origin         TEXT    NOT NULL DEFAULT '',
                owner          TEXT    NOT NULL DEFAULT '',
                source_mtime_ns INTEGER NOT NULL DEFAULT 0,
                source_size    INTEGER NOT NULL DEFAULT 0,
                n_points       INTEGER NOT NULL DEFAULT 0,
                wavenumbers    BLOB    NOT NULL,
                intensities    BLOB    NOT NULL,
                y_unit         TEXT    NOT NULL DEFAULT 'Absorbance',
                created_at     TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_reference_spectra_name ON reference_spectra(name);

            CREATE TABLE IF NOT EXISTS reference_features (
                reference_id     INTEGER NOT NULL REFERENCES reference_spectra(id)
                                                ON DELETE CASCADE,
                feature_version  INTEGER NOT NULL,
                feature_vector   BLOB    NOT NULL,
                created_at       TEXT    NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (reference_id, feature_version)
            );

            CREATE INDEX IF NOT EXISTS idx_reference_features_version
                ON reference_features(feature_version);
        """)
        self._conn.commit()

        # Migration: add is_builtin column if missing
        try:
            cursor = self._conn.cursor()
            cursor.execute(
                "ALTER TABLE vibration_presets ADD COLUMN is_builtin INTEGER NOT NULL DEFAULT 1"
            )
            self._conn.commit()
        except sqlite3.OperationalError:
            pass  # column already exists

        # Migration: built-in vibrations became editable. ``seed_name`` keeps
        # the name a built-in entry shipped with (its identity for re-seeding,
        # for "reset to defaults" and for the functional-group knowledge base,
        # which refers to vibrations by that name); ``is_hidden`` marks a
        # built-in entry the user removed, so it can be brought back.
        for column_sql in (
            "ALTER TABLE vibration_presets ADD COLUMN seed_name TEXT",
            "ALTER TABLE vibration_presets ADD COLUMN is_hidden INTEGER NOT NULL DEFAULT 0",
        ):
            try:
                self._conn.execute(column_sql)
                self._conn.commit()
            except sqlite3.OperationalError:
                pass  # column already exists
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        self._conn.commit()

        for column_sql in (
            "ALTER TABLE reference_spectra ADD COLUMN source_norm TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE reference_spectra ADD COLUMN source_provider TEXT NOT NULL DEFAULT 'local'",
            "ALTER TABLE reference_spectra ADD COLUMN external_id TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE reference_spectra ADD COLUMN sample_state TEXT NOT NULL DEFAULT ''",
            (
                "ALTER TABLE reference_spectra ADD COLUMN "
                "sampling_procedure TEXT NOT NULL DEFAULT ''"
            ),
            "ALTER TABLE reference_spectra ADD COLUMN path_length TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE reference_spectra ADD COLUMN resolution TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE reference_spectra ADD COLUMN origin TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE reference_spectra ADD COLUMN owner TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE reference_spectra ADD COLUMN source_mtime_ns INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE reference_spectra ADD COLUMN source_size INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE reference_spectra ADD COLUMN n_points INTEGER NOT NULL DEFAULT 0",
        ):
            try:
                cursor.execute(column_sql)
                self._conn.commit()
            except sqlite3.OperationalError:
                pass

        self._migrate_reference_features_foreign_key(cursor)

        cursor.execute(
            """
            UPDATE reference_spectra
            SET source_norm = lower(replace(source, '\\', '/'))
            WHERE source_norm = '' AND source != ''
            """
        )
        cursor.execute(
            """
            UPDATE reference_spectra
            SET source_provider = 'local'
            WHERE source_provider = ''
            """
        )
        cursor.execute(
            """
            UPDATE reference_spectra
            SET n_points = length(wavenumbers) / 8
            WHERE n_points = 0
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_reference_spectra_source_norm
                ON reference_spectra(source_norm)
            """
        )
        # Older builds treated web URLs as filesystem paths, making source_norm
        # depend on the process CWD. Repair those rows in place on first startup.
        web_rows = cursor.execute(
            """
            SELECT id, source
            FROM reference_spectra
            WHERE source LIKE 'http://%' OR source LIKE 'https://%'
            """
        ).fetchall()
        for row in web_rows:
            try:
                normalized_url = normalize_source_url(row["source"])
            except ValueError:
                # Preserve malformed legacy data instead of making application
                # startup depend on a historical source string being valid.
                continue
            cursor.execute(
                "UPDATE reference_spectra SET source_norm = ? WHERE id = ?",
                (normalized_url, int(row["id"])),
            )
        self._conn.commit()

    def _migrate_reference_features_foreign_key(self, cursor: sqlite3.Cursor) -> None:
        """Add the reference-feature FK to databases created by older releases."""
        assert self._conn is not None
        foreign_keys = cursor.execute("PRAGMA foreign_key_list(reference_features)").fetchall()
        if any(
            row["table"] == "reference_spectra"
            and row["from"] == "reference_id"
            and row["on_delete"].casefold() == "cascade"
            for row in foreign_keys
        ):
            return

        # Cached features are fully recomputable. Preserve valid rows while
        # dropping only historical orphans that cannot satisfy the new FK.
        cursor.execute("DROP TABLE IF EXISTS reference_features_with_fk")
        cursor.execute(
            """
            CREATE TABLE reference_features_with_fk (
                reference_id INTEGER NOT NULL REFERENCES reference_spectra(id)
                                              ON DELETE CASCADE,
                feature_version INTEGER NOT NULL,
                feature_vector BLOB NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (reference_id, feature_version)
            )
            """
        )
        cursor.execute(
            """
            INSERT INTO reference_features_with_fk
                (reference_id, feature_version, feature_vector, created_at)
            SELECT rf.reference_id, rf.feature_version, rf.feature_vector, rf.created_at
            FROM reference_features AS rf
            INNER JOIN reference_spectra AS rs ON rs.id = rf.reference_id
            """
        )
        cursor.execute("DROP TABLE reference_features")
        cursor.execute("ALTER TABLE reference_features_with_fk RENAME TO reference_features")
        cursor.execute(
            """
            CREATE INDEX idx_reference_features_version
                ON reference_features(feature_version)
            """
        )
        self._conn.commit()

    #: Raise when the built-in catalog below gains entries; databases seeded
    #: with a lower number get the new entries added, nothing else is touched.
    _BUILTIN_VIBRATIONS_SEED_VERSION = 3
    _SEED_VERSION_KEY = "builtin_vibrations_seed_version"

    def _get_meta(self, key: str) -> str | None:
        assert self._conn is not None
        row = self._conn.execute("SELECT value FROM app_meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row[0])

    def _set_meta(self, key: str, value: str) -> None:
        assert self._conn is not None
        self._conn.execute(
            "INSERT INTO app_meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    def _seed_vibration_presets(self) -> None:
        """Make sure the built-in IR vibration library is present.

        Built-in vibrations can be edited and removed by the user, so seeding
        must never undo that. Once a database carries a seed version, seeding
        only *adds* catalog entries it does not have yet (identified by
        ``seed_name``). The whole-library replacement that used to run whenever
        the count was not exactly right would have wiped every edit at the next
        start; it is kept only for databases from before editing existed, where
        the built-in rows cannot contain anything of the user's.
        """
        assert self._conn is not None
        cursor = self._conn.cursor()
        catalog = self._builtin_vibration_catalog()
        catalog_names = {entry[0] for entry in catalog}

        if self._get_meta(self._SEED_VERSION_KEY) is None:
            existing = {
                str(row[0])
                for row in cursor.execute(
                    "SELECT name FROM vibration_presets WHERE is_builtin = 1"
                ).fetchall()
            }
            if existing != catalog_names:
                cursor.execute("DELETE FROM vibration_presets WHERE is_builtin = 1")
            cursor.execute(
                "UPDATE vibration_presets SET seed_name = name "
                "WHERE is_builtin = 1 AND seed_name IS NULL"
            )

        present = {
            str(row[0])
            for row in cursor.execute(
                "SELECT seed_name FROM vibration_presets "
                "WHERE is_builtin = 1 AND seed_name IS NOT NULL"
            ).fetchall()
        }
        cursor.executemany(
            """INSERT INTO vibration_presets
               (name, typical_range_min, typical_range_max, category, description, color,
                is_builtin, seed_name)
               VALUES (?, ?, ?, ?, ?, ?, 1, ?)""",
            [(*entry, entry[0]) for entry in catalog if entry[0] not in present],
        )
        self._set_meta(self._SEED_VERSION_KEY, str(self._BUILTIN_VIBRATIONS_SEED_VERSION))
        self._conn.commit()

    @staticmethod
    def _builtin_vibration_catalog() -> list[tuple[str, float, float, str, str, str]]:
        """The built-in vibration library as shipped.

        The library started from the original VŠCHT Praha table and is extended
        with additional sourced diagnostic bands used by the functional-group
        scoring assistant.
        """
        presets = [
            # (name, range_min, range_max, category, description, color)
            # O-H stretch
            ("ν(OH) –OH isolated", 3580.0, 3670.0, "stretch", "", "#E74C3C"),
            ("ν(OH) –OH solid/liq.", 3150.0, 3640.0, "stretch", "", "#E74C3C"),
            ("ν(OH) H₂O crystal", 3100.0, 3620.0, "stretch", "", "#E57373"),
            ("ν(OH) –OH intramol. H-bond", 3400.0, 3590.0, "stretch", "", "#E74C3C"),
            ("ν(OH) –COOH monomer", 3500.0, 3550.0, "stretch", "", "#C0392B"),
            ("ν(OH) –OH dimer H-bond", 3230.0, 3550.0, "stretch", "", "#C0392B"),
            ("ν(OH) –OH chelate H-bond", 2500.0, 3200.0, "stretch", "", "#A93226"),
            # N-H stretch
            ("νas(NH₂) –NH₂", 3330.0, 3550.0, "stretch", "", "#E67E22"),
            ("νas(NH₂) –CO–NH₂", 3480.0, 3540.0, "stretch", "", "#E67E22"),
            ("ν(NH) –NH–", 3300.0, 3500.0, "stretch", "", "#E67E22"),
            ("νs(NH₂) –NH₂", 3250.0, 3450.0, "stretch", "", "#F39C12"),
            ("νs(NH₂) –CO–NH₂", 3380.0, 3420.0, "stretch", "", "#F39C12"),
            ("νas(NH₂) –CONH₂", 3320.0, 3360.0, "stretch", "", "#E67E22"),
            ("νs(NH₂) –CONH₂", 3180.0, 3220.0, "stretch", "", "#F39C12"),
            ("ν(NH) amine salt", 2800.0, 3000.0, "stretch", "", "#E67E22"),
            # C-H stretch
            ("ν(CH) –C≡C–H", 3300.0, 3340.0, "stretch", "", "#9B59B6"),
            ("2×ν(C=O) overtone", 3200.0, 3550.0, "overtone", "", "#BDC3C7"),
            ("νas(CH₂) >C=CH₂", 3075.0, 3095.0, "stretch", "", "#9B59B6"),
            ("ν(CH) Ar", 3000.0, 3090.0, "stretch", "", "#9B59B6"),
            ("ν(CH) =CH–", 2995.0, 3050.0, "stretch", "", "#9B59B6"),
            ("νas(CH₃) –CH₃", 2940.0, 2995.0, "stretch", "", "#8E44AD"),
            ("νas(CH₂) –CH₂–", 2915.0, 2955.0, "stretch", "", "#8E44AD"),
            ("ν(CH) sat.", 2880.0, 2890.0, "stretch", "", "#8E44AD"),
            ("νs(CH₃) –CH₃", 2840.0, 2895.0, "stretch", "", "#8E44AD"),
            ("νs(CH₂) –CH₂–", 2830.0, 2880.0, "stretch", "", "#8E44AD"),
            ("ν(CH) –CHO", 2810.0, 2830.0, "stretch", "", "#9B59B6"),
            ("ν(CH)+overtone –CHO", 2650.0, 2745.0, "overtone", "", "#BDC3C7"),
            ("ν(SH) thiol", 2550.0, 2600.0, "stretch", "", "#7D6608"),
            # CO₂, triple bonds
            ("ν(CO₂) ~2350", 2330.0, 2370.0, "stretch", "", "#95A5A6"),
            ("ν(N=C=O) –N=C=O isocyanate", 2250.0, 2275.0, "stretch", "", "#16A085"),
            ("ν(C≡N) –C≡N", 2200.0, 2270.0, "stretch", "", "#1ABC9C"),
            ("ν(C≡C) –C≡C– disubst.", 2190.0, 2260.0, "stretch", "", "#1ABC9C"),
            ("ν(N₃) –N₃ azide", 2120.0, 2160.0, "stretch", "", "#16A085"),
            ("ν(S–C≡N) –SCN thiocyanate", 2140.0, 2160.0, "stretch", "", "#16A085"),
            ("ν(N=C=N) carbodiimide", 2120.0, 2145.0, "stretch", "", "#16A085"),
            ("ν(N=C=S) –N=C=S isothiocyanate", 1990.0, 2140.0, "stretch", "", "#16A085"),
            ("ν(C=C=O) ketene", 2140.0, 2160.0, "stretch", "", "#16A085"),
            ("ν(C≡C) –C≡C–H", 2100.0, 2140.0, "stretch", "", "#1ABC9C"),
            ("ν(C=C=C) allene", 1925.0, 1990.0, "stretch", "", "#5DADE2"),
            # Ar overtone/combination
            ("Ar overtone/comb.", 1650.0, 2000.0, "overtone", "", "#BDC3C7"),
            ("2×γ(CH) vinyl/vinylidene", 1775.0, 1985.0, "overtone", "", "#BDC3C7"),
            # C=O stretch
            ("ν(C=O) –COCl acid halide", 1770.0, 1800.0, "stretch", "", "#C0392B"),
            ("ν(C=O) conj. –COCl acid halide", 1755.0, 1780.0, "stretch", "", "#C0392B"),
            ("ν(C=O) anhydride asym.", 1800.0, 1825.0, "stretch", "", "#C0392B"),
            ("ν(C=O) anhydride sym.", 1740.0, 1775.0, "stretch", "", "#C0392B"),
            ("ν(C=O) vinyl/phenyl ester", 1750.0, 1800.0, "stretch", "", "#C0392B"),
            ("ν(C=O) –COOH monomer", 1740.0, 1800.0, "stretch", "", "#C0392B"),
            ("ν(C=O) –CO–O– sat. ester", 1720.0, 1750.0, "stretch", "", "#C0392B"),
            ("ν(C=O) R–CO–R' sat. ketone", 1690.0, 1750.0, "stretch", "", "#C0392B"),
            ("ν(C=O) –CHO aldehyde", 1650.0, 1745.0, "stretch", "", "#C0392B"),
            ("ν(C=O) –CO–O– α,β-unsat. ester", 1705.0, 1740.0, "stretch", "", "#C0392B"),
            ("ν(C=O) Ar–CO–O–R ester", 1705.0, 1730.0, "stretch", "", "#C0392B"),
            ("ν(C=O) H–CO–O–R formate", 1720.0, 1725.0, "stretch", "", "#C0392B"),
            ("ν(C=O) –COOH dimer", 1700.0, 1725.0, "stretch", "", "#C0392B"),
            ("ν(C=O) Ar–COOH dimer", 1680.0, 1715.0, "stretch", "", "#C0392B"),
            ("ν(C=O) ArCO– α,β-unsat. ketone", 1650.0, 1705.0, "stretch", "", "#C0392B"),
            ("ν(C=O) amide I –CO–NH₂ (1670–1690)", 1670.0, 1690.0, "stretch", "", "#E74C3C"),
            ("ν(C=O) amide I –CO–NH₂ (1650–1670)", 1650.0, 1670.0, "stretch", "", "#E74C3C"),
            ("ν(C=O) β-diketone enol", 1580.0, 1640.0, "stretch", "", "#C0392B"),
            ("ν(C=N) C=N–OH oxime", 1650.0, 1690.0, "stretch", "", "#16A085"),
            # C=C and H₂O
            ("ν(C=C) >C=C< alkene", 1620.0, 1685.0, "stretch", "", "#5DADE2"),
            ("δ(H₂O) crystal/solv.", 1615.0, 1645.0, "bend", "", "#85C1E9"),
            ("ν(C=C) Ar ~1600", 1585.0, 1625.0, "stretch", "", "#2980B9"),
            ("ν(C=C) –C=C–C=C– conj.", 1590.0, 1650.0, "stretch", "", "#5DADE2"),
            # N-H bending (amide / amines)
            ("δ(NH₃⁺) amine salt", 1510.0, 1610.0, "bend", "", "#E67E22"),
            ("δ(NH₂) amide II –CO–NH₂", 1620.0, 1650.0, "bend", "", "#E67E22"),
            ("δ(NH₂) –NH₂", 1580.0, 1650.0, "bend", "", "#E67E22"),
            ("δ(NH₂) –CO–NH₂", 1590.0, 1620.0, "bend", "", "#E67E22"),
            # COO⁻
            ("νas(COO⁻) carboxylate", 1550.0, 1610.0, "stretch", "", "#8E44AD"),
            # Ar C=C / N-H
            ("ν(C=C) Ar conj. ~1580", 1570.0, 1590.0, "stretch", "", "#2980B9"),
            ("δ(NH) –NH–", 1490.0, 1580.0, "bend", "", "#E67E22"),
            # NO₂
            ("νas(NO₂) –NO₂", 1485.0, 1570.0, "stretch", "", "#D35400"),
            ("νs(NO₂) –NO₂", 1315.0, 1385.0, "stretch", "", "#D35400"),
            ("νas(SO₃) sulfate", 1380.0, 1415.0, "stretch", "", "#D35400"),
            ("νas(SO₂) sulfonyl chloride", 1380.0, 1410.0, "stretch", "", "#D35400"),
            ("νas(SO₃) sulfonate", 1335.0, 1372.0, "stretch", "", "#D35400"),
            ("νas(SO₂) sulfone", 1300.0, 1350.0, "stretch", "", "#D35400"),
            ("νas(SO₂) sulfonamide", 1335.0, 1350.0, "stretch", "", "#D35400"),
            # Ar C=C
            ("ν(C=C) Ar ~1490", 1470.0, 1525.0, "stretch", "", "#2980B9"),
            # C-H bending
            ("δ(CH₂) –CH₂–", 1440.0, 1480.0, "bend", "", "#27AE60"),
            ("δd(CH₃) –CH₃", 1440.0, 1470.0, "bend", "", "#27AE60"),
            ("δd(CH₃) CH₃–C=O/N/S", 1390.0, 1450.0, "bend", "", "#27AE60"),
            ("δ(CH₂) adj. C=O/Ar", 1385.0, 1445.0, "bend", "", "#27AE60"),
            ("δ(OH)+ν(CO) –COOH dimer", 1395.0, 1440.0, "bend", "", "#A93226"),
            ("δ(CH) –CHO", 1325.0, 1440.0, "bend", "", "#27AE60"),
            ("δ(CH₂) –HC=CH₂", 1390.0, 1440.0, "bend", "", "#27AE60"),
            ("δ(COH) tert./Ar–OH", 1310.0, 1440.0, "bend", "", "#A93226"),
            # C-N amide III
            ("ν(CN) amide III –CO–NH₂", 1400.0, 1420.0, "stretch", "", "#16A085"),
            # COO⁻ sym
            ("νs(COO⁻) carboxylate", 1335.0, 1420.0, "stretch", "", "#8E44AD"),
            # C-H bending cont.
            ("δ(CH) –CH=CH– cis", 1350.0, 1415.0, "bend", "", "#27AE60"),
            ("δs(CH₃) (CH₃)₂CH isopropyl", 1345.0, 1395.0, "bend", "", "#27AE60"),
            ("δs(CH₃) CH₃–C=O", 1330.0, 1385.0, "bend", "", "#27AE60"),
            ("δ(OH) –COOH monomer", 1280.0, 1380.0, "bend", "", "#A93226"),
            ("δ(CH) –C≡C–H", 1225.0, 1375.0, "bend", "", "#9B59B6"),
            ("δ(CH) >C=CH–", 1340.0, 1350.0, "bend", "", "#27AE60"),
            ("δ(CH) –HC=CH– trans", 1300.0, 1350.0, "bend", "", "#27AE60"),
            # C-N amide III secondary
            ("ν(CN) amide III –NH–CO–", 1300.0, 1350.0, "stretch", "", "#16A085"),
            # C-O alcohols
            ("δ(COH) R–OH prim./sec.", 1260.0, 1350.0, "bend", "", "#A93226"),
            # C-O esters
            ("ν(C–O) α,β-unsat. ester", 1250.0, 1345.0, "stretch", "", "#F39C12"),
            # C-N amines
            ("ν(CN) Ar₂NH/Ar–NH–R", 1250.0, 1360.0, "stretch", "", "#16A085"),
            ("ν(CN) Ar–NH₂ aniline", 1200.0, 1360.0, "stretch", "", "#16A085"),
            # NCO
            ("νs(NCO) –N=C=O", 1340.0, 1460.0, "stretch", "", "#16A085"),
            # C-N secondary amine
            ("ν(CN) R₂NH", 1170.0, 1190.0, "stretch", "", "#16A085"),
            # C-O
            ("ν(CO) Ar–O–R aryl ether", 1200.0, 1275.0, "stretch", "", "#F39C12"),
            ("ν(CO) CH₂=CH–O– vinyl ether", 1200.0, 1225.0, "stretch", "", "#F39C12"),
            ("ν(CO) –COOH monomer", 1075.0, 1190.0, "stretch", "", "#F39C12"),
            ("ν(CO–O–CO) anhydride", 900.0, 1300.0, "stretch", "", "#F39C12"),
            ("ν(CC) –CH(CH₃)₂", 1165.0, 1175.0, "stretch", "", "#7F8C8D"),
            ("ν(CO) R–O–R aliph. ether", 1085.0, 1150.0, "stretch", "", "#F39C12"),
            ("νs(COC) R–CO–O–R' sat.", 1050.0, 1160.0, "stretch", "", "#F39C12"),
            ("ν(CO) R₂CH–OH sec.", 1065.0, 1130.0, "stretch", "", "#F39C12"),
            ("ν(CCC) R–CO–R' ketone", 1080.0, 1120.0, "stretch", "", "#7F8C8D"),
            ("ν(CN) RNH₂", 1000.0, 1100.0, "stretch", "", "#16A085"),
            ("ν(S=O) sulfoxide", 1030.0, 1070.0, "stretch", "", "#D35400"),
            ("νs(SO₂) sulfonamide", 1155.0, 1170.0, "stretch", "", "#D35400"),
            ("νs(SO₃) sulfonate", 1168.0, 1195.0, "stretch", "", "#D35400"),
            ("νs(SO₂) sulfone", 1130.0, 1170.0, "stretch", "", "#D35400"),
            ("νs(SO₂) sulfonyl chloride", 1160.0, 1190.0, "stretch", "", "#D35400"),
            ("νs(SO₃) sulfate", 1185.0, 1200.0, "stretch", "", "#D35400"),
            ("ν(CO) R–OH prim.", 1020.0, 1085.0, "stretch", "", "#F39C12"),
            # OOP alkenes / aldehyde
            ("γ(CH) –CH=CH₂ vinyl", 980.0, 995.0, "oop", "", "#7F8C8D"),
            ("γ(CH) R–CH=CH–R trans", 955.0, 980.0, "oop", "", "#7F8C8D"),
            ("γ(CH) –CHO", 780.0, 975.0, "oop", "", "#7F8C8D"),
            ("ν(NO) –C=N–OH oxime", 930.0, 960.0, "stretch", "", "#D35400"),
            ("γ(OH) –COOH dimer", 915.0, 955.0, "oop", "", "#A93226"),
            ("–C(CH₃)₃ tert-butyl", 925.0, 930.0, "stretch", "", "#7F8C8D"),
            ("γ(CH) R–CH=CH₂ terminal", 905.0, 915.0, "oop", "", "#7F8C8D"),
            ("γ(CH) RR'C=CH₂ vinylidene", 885.0, 895.0, "oop", "", "#7F8C8D"),
            # OOP Ar C-H (substitution patterns)
            ("γ(CH) Ar 1H isolated", 830.0, 900.0, "oop", "", "#5D6D7E"),
            ("γ(CH) Ar 2H adjacent", 800.0, 860.0, "oop", "", "#5D6D7E"),
            ("γ(CH) RR'C=CHR'' trisubst.", 790.0, 850.0, "oop", "", "#7F8C8D"),
            ("γ(CH) Ar 3H adjacent", 760.0, 820.0, "oop", "", "#5D6D7E"),
            ("ρ(CH₂) adj. CHx≠2", 750.0, 785.0, "rocking", "", "#95A5A6"),
            ("γ(CH) Ar 4H 1,2-disubst.", 735.0, 770.0, "oop", "", "#5D6D7E"),
            ("γ(CH) Ar 5H monosubst.", 735.0, 770.0, "oop", "", "#5D6D7E"),
            ("ω(NH) –NH–", 700.0, 750.0, "wagging", "", "#E67E22"),
            ("γ(NH₂) –CO–NH₂ amide", 600.0, 750.0, "oop", "", "#E67E22"),
            ("ρ(CH₂) propyl/(CH₂)n–O–", 735.0, 750.0, "rocking", "", "#95A5A6"),
            ("ρ(CH₂) (CH₂)n– n>3", 720.0, 735.0, "rocking", "", "#95A5A6"),
            ("γ(CH) R–CH=CH–R' cis", 665.0, 730.0, "oop", "", "#7F8C8D"),
            ("γ(CH) Ar mono/1,3-/1,2,3-/1,2,4-", 680.0, 730.0, "oop", "", "#5D6D7E"),
            ("δ(CH) –C≡C–H in-plane", 575.0, 695.0, "bend", "", "#9B59B6"),
            ("γ(CH) Ar 6H benzene ~670", 660.0, 680.0, "oop", "", "#5D6D7E"),
            ("γ(NH) –NH₂", 650.0, 900.0, "oop", "", "#E67E22"),
            ("δ(CO₂) ~670", 660.0, 680.0, "bend", "", "#95A5A6"),
            # Third sourced wave — imine, epoxide, silicone, organophosphate
            ("ν(C=N) R₂C=N–R imine", 1640.0, 1690.0, "stretch", "", "#2E86C1"),
            ("ν(ring) oxirane breathing", 1230.0, 1280.0, "stretch", "", "#148F77"),
            ("νas(ring) oxirane", 880.0, 950.0, "stretch", "", "#148F77"),
            ("δs(Si–CH₃) silicone", 1255.0, 1270.0, "bend", "", "#7D6608"),
            ("νas(Si–O–Si) siloxane", 1000.0, 1130.0, "stretch", "", "#7D6608"),
            ("ν(Si–C)+ρ(CH₃) silicone", 780.0, 840.0, "stretch", "", "#7D6608"),
            ("ν(P=O) phosphoryl", 1150.0, 1280.0, "stretch", "", "#6C3483"),
            ("ν(P–O–C) aliph. phosphate", 970.0, 1060.0, "stretch", "", "#6C3483"),
            # Protecting-group wave 1 — silyl groups (category "silyl" -> own
            # section in the vibration panel). Values corroborated against
            # institute notes (TMS/TIPS/TBDMS) and silyl-ether IR literature.
            ("δs(Si–CH₃) TMS/TBS", 1245.0, 1265.0, "silyl", "", "#6D4C41"),
            ("δa(Si–CH₃)", 1400.0, 1420.0, "silyl", "", "#6D4C41"),
            ("ρ(CH₃) Si(CH₃)₃ TMS", 835.0, 865.0, "silyl", "", "#6D4C41"),
            ("νas(Si–C₃) TMS", 685.0, 715.0, "silyl", "", "#6D4C41"),
            ("νs(Si–C₃) TMS", 615.0, 640.0, "silyl", "", "#6D4C41"),
            ("ν(Si–O–C) silyl ether", 1050.0, 1110.0, "silyl", "", "#6D4C41"),
            ("ρ(Si–CH₃) TBS", 830.0, 845.0, "silyl", "", "#6D4C41"),
            ("ω(t-Bu) TBS", 930.0, 945.0, "silyl", "", "#6D4C41"),
            ("νas(Si–C) TBS", 670.0, 690.0, "silyl", "", "#6D4C41"),
            ("δ(CH₃) t-Bu dublet (silyl)", 1360.0, 1395.0, "silyl", "", "#6D4C41"),
            ("ρ(CH₃) iPr TIPS", 908.0, 926.0, "silyl", "", "#6D4C41"),
            ("ν(CCC) TIPS", 876.0, 894.0, "silyl", "", "#6D4C41"),
            ("νas(CCC) TIPS", 1060.0, 1085.0, "silyl", "", "#6D4C41"),
            ("δ(CH₃) iPr TIPS", 1458.0, 1472.0, "silyl", "", "#6D4C41"),
            ("ν(Si–Ph) TBDPS", 1100.0, 1120.0, "silyl", "", "#6D4C41"),
            # ── Seed version 2: vibrations of the groups the structure
            # perception recognises (carbamates, ureas, imides, lactams,
            # lactones, heteroaromatic rings, halogens, boron, …). Ranges from
            # Socrates (Infrared and Raman Characteristic Group Frequencies),
            # Pavia and Silverstein; deliberately wide — they say where a band
            # can appear, not where it must.
            ("ν(C=O) –NH–CO–O– carbamate", 1680.0, 1740.0, "stretch", "", "#8E44AD"),
            ("δ(NH)+ν(CN) carbamate amide II", 1500.0, 1560.0, "bend", "", "#8E44AD"),
            ("ν(C–O) carbamate", 1200.0, 1280.0, "stretch", "", "#8E44AD"),
            ("ν(C=O) urea", 1630.0, 1700.0, "stretch", "", "#7D3C98"),
            ("δ(NH)+ν(CN) urea amide II", 1530.0, 1600.0, "bend", "", "#7D3C98"),
            ("νas(C=O) imide", 1740.0, 1790.0, "stretch", "", "#6C3483"),
            ("νs(C=O) imide", 1670.0, 1730.0, "stretch", "", "#6C3483"),
            ("ν(C=O) amide I –CO–NH– sec.", 1630.0, 1680.0, "stretch", "", "#884EA0"),
            ("δ(NH)+ν(CN) amide II –CO–NH– sec.", 1510.0, 1570.0, "bend", "", "#884EA0"),
            ("ν(C=O) amide I –CO–NR₂ tert.", 1610.0, 1670.0, "stretch", "", "#884EA0"),
            ("ν(C=O) β-lactam", 1730.0, 1790.0, "stretch", "", "#884EA0"),
            ("ν(C=O) γ-lactam", 1670.0, 1720.0, "stretch", "", "#884EA0"),
            ("ν(C=O) γ-lactone", 1755.0, 1800.0, "stretch", "", "#2471A3"),
            ("ν(C=O) β-lactone", 1810.0, 1850.0, "stretch", "", "#2471A3"),
            ("ν(C=O) carbonate", 1740.0, 1790.0, "stretch", "", "#1F618D"),
            ("νas(O–C–O) carbonate", 1210.0, 1290.0, "stretch", "", "#1F618D"),
            ("ν(C=O) cyclopentanone", 1735.0, 1760.0, "stretch", "", "#B9770E"),
            ("ν(C=O) cyclobutanone", 1770.0, 1795.0, "stretch", "", "#B9770E"),
            ("ν(C=S) thioamide/thiourea", 1050.0, 1250.0, "stretch", "", "#B7950B"),
            ("ν(CO) R₃C–OH tert.", 1100.0, 1210.0, "stretch", "", "#C0392B"),
            ("ν(CO) Ar–OH phenol", 1180.0, 1260.0, "stretch", "", "#C0392B"),
            ("ν(C–O–C) acetal/ketal", 1040.0, 1190.0, "stretch", "", "#117A65"),
            ("ν(COC) cyclic ether THF/THP", 1040.0, 1100.0, "stretch", "", "#117A65"),
            ("νs(CH₃) O–CH₃ methoxy", 2810.0, 2850.0, "stretch", "", "#117A65"),
            ("νs(COC) Ar–O–CH₃", 1010.0, 1060.0, "stretch", "", "#117A65"),
            ("νs(CH₃) N–CH₃", 2770.0, 2820.0, "stretch", "", "#D35400"),
            ("ν(CH) N–CH Bohlmann bands", 2700.0, 2800.0, "stretch", "", "#D35400"),
            ("ν(CN) tert. amine", 1020.0, 1250.0, "stretch", "", "#D35400"),
            ("ν(C=N) amidine/guanidine", 1600.0, 1690.0, "stretch", "", "#D35400"),
            ("νas(NO₂) –O–NO₂ nitrate", 1620.0, 1660.0, "stretch", "", "#A04000"),
            ("νs(NO₂) –O–NO₂ nitrate", 1270.0, 1290.0, "stretch", "", "#A04000"),
            ("ν(N–O) –O–NO₂ nitrate", 840.0, 870.0, "stretch", "", "#A04000"),
            ("ν(N=N) azo", 1400.0, 1450.0, "stretch", "", "#A04000"),
            ("νs(N₃) –N₃ azide", 1180.0, 1340.0, "stretch", "", "#A04000"),
            ("ν(N⁺–O⁻) N-oxide", 1200.0, 1300.0, "stretch", "", "#A04000"),
            ("ν(C–S) sulfide/thioether", 600.0, 720.0, "stretch", "", "#B7950B"),
            ("ν(NH) sulfonamide", 3200.0, 3350.0, "stretch", "", "#B7950B"),
            ("ν(P=O) phosphine oxide", 1140.0, 1200.0, "stretch", "", "#5D6D7E"),
            ("ν(P–O–Ar)", 1160.0, 1240.0, "stretch", "", "#5D6D7E"),
            ("ν(P=S)", 600.0, 750.0, "stretch", "", "#5D6D7E"),
            ("ν(OH) P–OH", 2300.0, 2800.0, "stretch", "", "#5D6D7E"),
            ("ν(Si–H)", 2100.0, 2260.0, "stretch", "", "#6D4C41"),
            ("νas(B–O) boronic acid/ester", 1310.0, 1390.0, "stretch", "", "#5D6D7E"),
            ("ν(C–O) pinacol boronate", 1130.0, 1150.0, "stretch", "", "#5D6D7E"),
            ("ν(OH) B(OH)₂", 3200.0, 3350.0, "stretch", "", "#5D6D7E"),
            ("ν(C–F)", 1000.0, 1400.0, "stretch", "", "#1E8449"),
            ("νas(CF₃)", 1100.0, 1350.0, "stretch", "", "#1E8449"),
            ("ν(C–Cl) alkyl", 600.0, 850.0, "stretch", "", "#1E8449"),
            ("ν(C–Cl) Ar–Cl", 1030.0, 1100.0, "stretch", "", "#1E8449"),
            ("ν(C–Br)", 500.0, 690.0, "stretch", "", "#1E8449"),
            ("ν(C–I)", 480.0, 600.0, "stretch", "", "#1E8449"),
            ("ν(CH) cyclopropane", 3040.0, 3100.0, "stretch", "", "#5E6B78"),
            ("ring δ cyclopropane", 1000.0, 1050.0, "bend", "", "#5E6B78"),
            ("ν(ring) pyridine ~1590", 1565.0, 1610.0, "stretch", "", "#2E86C1"),
            ("ν(ring) pyridine ~1440", 1420.0, 1480.0, "stretch", "", "#2E86C1"),
            ("ring breathing pyridine", 965.0, 1035.0, "stretch", "", "#2E86C1"),
            ("ν(ring) diazine", 1540.0, 1590.0, "stretch", "", "#2E86C1"),
            ("ν(ring) diazine ~1410", 1380.0, 1470.0, "stretch", "", "#2E86C1"),
            ("ν(NH) pyrrole/indole", 3200.0, 3480.0, "stretch", "", "#2874A6"),
            ("ν(ring) pyrrole/indole", 1450.0, 1560.0, "stretch", "", "#2874A6"),
            ("ν(NH) azole (H-bonded)", 2400.0, 3200.0, "stretch", "", "#2874A6"),
            ("ν(C=N) imidazole ring", 1480.0, 1600.0, "stretch", "", "#2874A6"),
            ("ν(C=N) pyrazole ring", 1500.0, 1600.0, "stretch", "", "#2874A6"),
            ("ν(CH) azole ring C–H", 3100.0, 3160.0, "stretch", "", "#2874A6"),
            ("ν(N=N) 1,2,3-triazole ring", 1410.0, 1470.0, "stretch", "", "#2874A6"),
            ("ν(ring) 1,2,3-triazole", 1200.0, 1260.0, "stretch", "", "#2874A6"),
            ("ring breathing triazole", 1030.0, 1060.0, "stretch", "", "#2874A6"),
            ("ν(C=N) 1,2,4-triazole ring", 1480.0, 1540.0, "stretch", "", "#2874A6"),
            ("ν(C=N) tetrazole ring", 1560.0, 1610.0, "stretch", "", "#2874A6"),
            ("ν(N=N) tetrazole ring", 1400.0, 1480.0, "stretch", "", "#2874A6"),
            ("ring δ tetrazole", 1000.0, 1110.0, "bend", "", "#2874A6"),
            ("ν(C=N) oxazole/isoxazole/oxadiazole", 1560.0, 1650.0, "stretch", "", "#2874A6"),
            ("ν(C–O–C) oxazole/oxadiazole ring", 1000.0, 1100.0, "stretch", "", "#2874A6"),
            ("ν(ring) thiazole", 1480.0, 1540.0, "stretch", "", "#2874A6"),
            ("ν(CH) furan/thiophene", 3080.0, 3160.0, "stretch", "", "#2874A6"),
            ("ν(ring) furan", 1480.0, 1610.0, "stretch", "", "#2874A6"),
            ("ring breathing furan", 1000.0, 1030.0, "stretch", "", "#2874A6"),
            ("γ(CH) furan", 730.0, 800.0, "oop", "", "#2874A6"),
            ("ν(ring) thiophene", 1400.0, 1530.0, "stretch", "", "#2874A6"),
            ("γ(CH) thiophene", 690.0, 750.0, "oop", "", "#2874A6"),
            # ── Seed version 3: bands from the laboratory's own evaluated
            # spectra (100 projects with structures), kept when assigned in at
            # least 3 spectra at a consistent position with the group present in
            # the structure. Each was then checked independently: against public
            # NIST/Coblentz reference spectra (is the band clearly more frequent
            # in compounds with the group than without?) and against the
            # literature. The description of each entry says whether a band is
            # confirmed by one of the two or supported by the laboratory spectra
            # alone. Bands the reference spectra or the literature contradicted
            # were dropped.
            (
                "δs(CH₃) –CH₃ umbrella",
                1360.0,
                1398.0,
                "bend",
                "Lab: 46 spectra; NIST: confirmed (x1.64, n=1551); Lit.: Socrates; Pavia (CH₃ sym. deformation ~1375)",
                "#B9770E",
            ),
            (
                "ν(NH) lactam cis-NH (2-pyrrolidone)",
                3195.0,
                3305.0,
                "stretch",
                "Lab: 16 spectra; NIST: no N–H lactams among its pyrrolidones; Lit.: H-bonded lactam N–H chains below the free 3450 band (Maiti et al., PCCP 2012)",
                "#6C3483",
            ),
            (
                "νas(NH₃⁺) R–NH₃⁺",
                3015.0,
                3220.0,
                "stretch",
                "Lab: 13 spectra; NIST: broad band, not resolvable as a peak; Lit.: NH₃⁺ stretch envelope 3200–2800 (Smith, Spectroscopy 2019)",
                "#E67E22",
            ),
            (
                "δas(NH₃⁺) R–NH₃⁺",
                1560.0,
                1650.0,
                "bend",
                "Lab: 17 spectra; NIST: weak support; Lit.: NH₃⁺ asym. bend 1625–1560 (Smith, Spectroscopy 2019)",
                "#E67E22",
            ),
            (
                "δs(NH₃⁺) R–NH₃⁺",
                1505.0,
                1525.0,
                "bend",
                "Lab: 6 spectra; NIST: weak support; Lit.: NH₃⁺ sym. bend 1550–1500 (Smith, Spectroscopy 2019)",
                "#E67E22",
            ),
            (
                "ν(NH⁺) ammonium salt broad",
                2480.0,
                2850.0,
                "stretch",
                "Lab: 18 spectra; NIST: confirmed (x2.64, n=112); Lit.: N–H⁺ stretch / Fermi bands 2800–2400 (Smith, Spectroscopy 2019)",
                "#E67E22",
            ),
            (
                "comb. R–NH₃⁺ salt indicator ~2030",
                2010.0,
                2060.0,
                "overtone",
                "Lab: 14 spectra; NIST: weak band, found in 10 % of salts vs 1 % of others; Lit.: amine-salt combination bands 2800–2000 (Smith, Spectroscopy 2019)",
                "#E67E22",
            ),
            (
                "ν(C–N) tert. amide ~1410",
                1398.0,
                1428.0,
                "stretch",
                "Lab: 15 spectra; NIST: present, not specific",
                "#884EA0",
            ),
            (
                "ν(C=O) 2-pyridone",
                1645.0,
                1690.0,
                "stretch",
                "Lab: 10 spectra; Lit.: mixed C=O/C=C band 1650–1685 (2-pyridone ¹⁸O studies)",
                "#1A5276",
            ),
            ("ν(C–N) 2-pyridone", 1042.0, 1072.0, "stretch", "Lab: 12 spectra", "#1A5276"),
            ("δ(CH) 2-pyridone", 1255.0, 1310.0, "bend", "Lab: 5 spectra", "#1A5276"),
            (
                "ω(CH₂) –CH₂– wagging",
                1350.0,
                1368.0,
                "wagging",
                "Lab: 7 spectra; NIST: weak support; Lit.: CH₂ wag 1350–1180 (Socrates)",
                "#5E6B78",
            ),
            (
                "νs(CF₃) Ar–CF₃",
                1320.0,
                1345.0,
                "stretch",
                "Lab: 5 spectra; NIST: weak support; Lit.: benzotrifluoride band 1328 (J. Chem. Phys. 27, 740, 1957)",
                "#1E8449",
            ),
            (
                "δs(CH₃) t-Bu doublet",
                1360.0,
                1398.0,
                "bend",
                "Lab: 6 spectra; NIST: confirmed (x1.57, n=64); Lit.: t-Bu doublet ~1390/1365 (Pavia; Socrates)",
                "#B9770E",
            ),
            (
                "ν(O–C(CH₃)₃) t-Bu ester/Boc",
                1150.0,
                1182.0,
                "stretch",
                "Lab: 3 spectra; Lit.: t-Bu ester / Boc C–O ~1150–1170 (Socrates)",
                "#8E44AD",
            ),
            (
                "νas(C–O) acetate ~1230",
                1205.0,
                1245.0,
                "stretch",
                "Lab: 4 spectra; NIST: confirmed (x1.61, n=38); Lit.: acetate C(=O)–O ~1240 (Pavia; Smith 2018)",
                "#2471A3",
            ),
            (
                "νs(O–C–C) acetate ~1045",
                1035.0,
                1060.0,
                "stretch",
                "Lab: 4 spectra; NIST: confirmed (x1.71, n=38); Lit.: acetate O–C–C ~1050 (Smith 2018)",
                "#2471A3",
            ),
            (
                "δ(O–C=O) acetate ~605",
                595.0,
                612.0,
                "bend",
                "Lab: 3 spectra; NIST: confirmed (x3.21, n=6); Lit.: acetate O–C=O deformation ~605 (Socrates)",
                "#2471A3",
            ),
            (
                "νas(SO₃⁻) sulfate/sulfonate anion",
                1200.0,
                1270.0,
                "stretch",
                "Lab: 4 spectra; NIST: present, not specific; Lit.: organosulfate SO₃ stretches ~1250/1065 (AMT 2023)",
                "#B7950B",
            ),
            (
                "δs(SO₃⁻)",
                580.0,
                630.0,
                "bend",
                "Lab: 3 spectra; NIST: present, not specific; Lit.: SO₃ deformation 550–650 (Socrates)",
                "#B7950B",
            ),
            ("ν(S–O–C) sulfate ester", 750.0, 770.0, "stretch", "Lab: 3 spectra", "#B7950B"),
            (
                "δ(SO₂) scissoring",
                495.0,
                590.0,
                "bend",
                "Lab: 5 spectra; NIST: confirmed (x1.49, n=32); Lit.: SO₂ scissoring 520–580 (Socrates)",
                "#B7950B",
            ),
            ("νas(Si–C₃) TIPS", 670.0, 682.0, "silyl", "Lab: 4 spectra", "#6D4C41"),
            ("νs(Si–C₃) TIPS", 640.0, 650.0, "silyl", "Lab: 4 spectra", "#6D4C41"),
            ("ρ(CH₃) TIPS ~995", 990.0, 1003.0, "silyl", "Lab: 3 spectra", "#6D4C41"),
            (
                "δs(CH₃) iPr TIPS doublet",
                1355.0,
                1400.0,
                "silyl",
                "Lab: 3 spectra",
                "#6D4C41",
            ),
            (
                "biphenyl ring ~1437",
                1429.0,
                1455.0,
                "ring",
                "Lab: 4 spectra; NIST: present, not specific",
                "#566573",
            ),
            (
                "biphenyl ring ~1159",
                1151.0,
                1175.0,
                "ring",
                "Lab: 5 spectra; NIST: present, not specific",
                "#566573",
            ),
            (
                "biphenyl ring ~1076",
                1068.0,
                1084.0,
                "ring",
                "Lab: 6 spectra; NIST: confirmed (x1.72, n=32)",
                "#566573",
            ),
            (
                "biphenyl ring ~1008",
                991.0,
                1016.0,
                "ring",
                "Lab: 6 spectra; NIST: confirmed (x1.78, n=32)",
                "#566573",
            ),
            (
                "biphenyl ring ~756",
                748.0,
                764.0,
                "ring",
                "Lab: 6 spectra; NIST: confirmed (x1.8, n=32)",
                "#566573",
            ),
            (
                "biphenyl ring ~697",
                689.0,
                705.0,
                "ring",
                "Lab: 6 spectra; NIST: confirmed (x1.98, n=32)",
                "#566573",
            ),
            ("indane ring ~1273", 1265.0, 1282.0, "ring", "Lab: 4 spectra", "#5D6D7E"),
            ("indane ring ~1022", 1013.0, 1032.0, "ring", "Lab: 4 spectra", "#5D6D7E"),
            ("indane ring ~925", 914.0, 933.0, "ring", "Lab: 3 spectra", "#5D6D7E"),
            ("indane ring ~831", 823.0, 839.0, "ring", "Lab: 5 spectra", "#5D6D7E"),
            ("indane ring ~754", 746.0, 762.0, "ring", "Lab: 3 spectra", "#5D6D7E"),
            (
                "ν(CH) isoxazole",
                3121.0,
                3152.0,
                "stretch",
                "Lab: 19 spectra; Lit.: heteroaromatic ring C–H 3100–3150",
                "#2E86C1",
            ),
            ("isoxazole ring ~1559", 1549.0, 1567.0, "ring", "Lab: 16 spectra", "#2E86C1"),
            ("isoxazole ring ~1270", 1262.0, 1278.0, "ring", "Lab: 3 spectra", "#2E86C1"),
            ("isoxazole ring ~1085", 1077.0, 1094.0, "ring", "Lab: 3 spectra", "#2E86C1"),
            ("isoxazole ring ~924", 910.0, 932.0, "ring", "Lab: 13 spectra", "#2E86C1"),
            (
                "naphthalene ring ~1390",
                1382.0,
                1402.0,
                "ring",
                "Lab: 5 spectra; NIST: weak support",
                "#4A235A",
            ),
            (
                "naphthalene ring ~1365",
                1349.0,
                1374.0,
                "ring",
                "Lab: 5 spectra; NIST: weak support",
                "#4A235A",
            ),
            (
                "naphthalene ring ~1145",
                1135.0,
                1162.0,
                "ring",
                "Lab: 3 spectra; NIST: confirmed (x1.32, n=116)",
                "#4A235A",
            ),
            (
                "naphthalene ring ~954",
                946.0,
                964.0,
                "ring",
                "Lab: 4 spectra; NIST: weak support",
                "#4A235A",
            ),
            (
                "naphthalene ring ~774",
                766.0,
                793.0,
                "ring",
                "Lab: 5 spectra; NIST: confirmed (x1.36, n=116)",
                "#4A235A",
            ),
            (
                "para-disubst. benzene ring ~1224",
                1214.0,
                1234.0,
                "ring",
                "Lab: 3 spectra; NIST: weak support",
                "#616A6B",
            ),
            (
                "para-disubst. benzene ring ~1182",
                1172.0,
                1192.0,
                "ring",
                "Lab: 4 spectra; NIST: confirmed (x1.81, n=258)",
                "#616A6B",
            ),
            (
                "para-disubst. benzene ring ~1107",
                1096.0,
                1115.0,
                "ring",
                "Lab: 4 spectra; NIST: weak support",
                "#616A6B",
            ),
            (
                "para-disubst. benzene ring ~816",
                808.0,
                824.0,
                "ring",
                "Lab: 4 spectra; NIST: weak support",
                "#616A6B",
            ),
            (
                "pyrazine ring ~1549",
                1541.0,
                1557.0,
                "ring",
                "Lab: 4 spectra; NIST: weak support",
                "#1B4F72",
            ),
            (
                "pyrazine ring ~1416",
                1408.0,
                1428.0,
                "ring",
                "Lab: 4 spectra; NIST: weak support",
                "#1B4F72",
            ),
            (
                "pyrazine ring ~1368",
                1360.0,
                1377.0,
                "ring",
                "Lab: 4 spectra; NIST: weak support",
                "#1B4F72",
            ),
            (
                "pyrazine ring ~1216",
                1201.0,
                1237.0,
                "ring",
                "Lab: 4 spectra; NIST: confirmed (x1.31, n=116)",
                "#1B4F72",
            ),
            (
                "pyrazine ring ~1082",
                1072.0,
                1090.0,
                "ring",
                "Lab: 3 spectra; NIST: confirmed (x1.72, n=116)",
                "#1B4F72",
            ),
            (
                "pyrazine ring ~1003",
                994.0,
                1011.0,
                "ring",
                "Lab: 4 spectra; NIST: weak support",
                "#1B4F72",
            ),
            (
                "pyrazine ring ~773",
                761.0,
                781.0,
                "ring",
                "Lab: 3 spectra; NIST: weak support",
                "#1B4F72",
            ),
            (
                "pyrazine ring ~723",
                711.0,
                732.0,
                "ring",
                "Lab: 4 spectra; NIST: weak support",
                "#1B4F72",
            ),
            (
                "pyrazine ring ~594",
                583.0,
                609.0,
                "ring",
                "Lab: 4 spectra; NIST: confirmed (x2.15, n=9)",
                "#1B4F72",
            ),
            (
                "pyridine ring ~1597",
                1572.0,
                1609.0,
                "ring",
                "Lab: 18 spectra; NIST: confirmed (x1.39, n=87)",
                "#2874A6",
            ),
            (
                "pyridine ring ~1372",
                1354.0,
                1382.0,
                "ring",
                "Lab: 16 spectra; NIST: present, not specific",
                "#2874A6",
            ),
            (
                "pyridine ring ~1146",
                1136.0,
                1164.0,
                "ring",
                "Lab: 4 spectra; NIST: weak support",
                "#2874A6",
            ),
            (
                "pyridine ring ~1078",
                1070.0,
                1093.0,
                "ring",
                "Lab: 10 spectra; NIST: weak support",
                "#2874A6",
            ),
            (
                "pyridine ring ~1049",
                1028.0,
                1059.0,
                "ring",
                "Lab: 16 spectra; NIST: confirmed (x1.41, n=87)",
                "#2874A6",
            ),
            (
                "pyridine ring ~972",
                962.0,
                992.0,
                "ring",
                "Lab: 10 spectra; NIST: weak support",
                "#2874A6",
            ),
            (
                "pyridine ring ~826",
                816.0,
                838.0,
                "ring",
                "Lab: 6 spectra; NIST: weak support",
                "#2874A6",
            ),
            (
                "pyridine ring ~786",
                777.0,
                804.0,
                "ring",
                "Lab: 14 spectra; NIST: present, not specific",
                "#2874A6",
            ),
            (
                "pyridine ring ~711",
                697.0,
                736.0,
                "ring",
                "Lab: 11 spectra; NIST: confirmed (x1.32, n=87)",
                "#2874A6",
            ),
            ("2-pyridone ring ~1359", 1351.0, 1384.0, "ring", "Lab: 20 spectra", "#1A5276"),
            ("2-pyridone ring ~1326", 1318.0, 1334.0, "ring", "Lab: 3 spectra", "#1A5276"),
            ("2-pyridone ring ~1236", 1228.0, 1244.0, "ring", "Lab: 15 spectra", "#1A5276"),
            ("2-pyridone ring ~1136", 1127.0, 1144.0, "ring", "Lab: 3 spectra", "#1A5276"),
            ("2-pyridone ring ~1052", 1043.0, 1067.0, "ring", "Lab: 5 spectra", "#1A5276"),
            ("2-pyridone ring ~876", 867.0, 884.0, "ring", "Lab: 12 spectra", "#1A5276"),
            ("2-pyridone ring ~768", 760.0, 776.0, "ring", "Lab: 6 spectra", "#1A5276"),
            ("2-pyridone ring ~752", 744.0, 760.0, "ring", "Lab: 4 spectra", "#1A5276"),
            ("2-pyridone ring ~559", 546.0, 567.0, "ring", "Lab: 14 spectra", "#1A5276"),
            ("2-pyridone ring ~458", 450.0, 468.0, "ring", "Lab: 7 spectra", "#1A5276"),
            (
                "quinoline ring ~1426",
                1417.0,
                1438.0,
                "ring",
                "Lab: 3 spectra; NIST: confirmed (x1.48, n=36)",
                "#21618C",
            ),
            (
                "quinoline ring ~1392",
                1381.0,
                1415.0,
                "ring",
                "Lab: 18 spectra; NIST: present, not specific",
                "#21618C",
            ),
            (
                "quinoline ring ~1330",
                1319.0,
                1341.0,
                "ring",
                "Lab: 7 spectra; NIST: weak support",
                "#21618C",
            ),
            (
                "quinoline ring ~1305",
                1290.0,
                1316.0,
                "ring",
                "Lab: 11 spectra; NIST: present, not specific",
                "#21618C",
            ),
            (
                "quinoline ring ~1098",
                1090.0,
                1106.0,
                "ring",
                "Lab: 5 spectra; NIST: weak support",
                "#21618C",
            ),
            (
                "quinoline ring ~789",
                777.0,
                802.0,
                "ring",
                "Lab: 8 spectra; NIST: confirmed (x1.78, n=36)",
                "#21618C",
            ),
            (
                "quinoline ring ~749",
                738.0,
                757.0,
                "ring",
                "Lab: 6 spectra; NIST: weak support",
                "#21618C",
            ),
        ]
        return presets

    def get_vibration_presets(self) -> list[dict]:
        """Return the vibration presets in use (removed built-ins left out)."""
        assert self._conn is not None
        rows = self._conn.execute(
            "SELECT * FROM vibration_presets WHERE is_hidden = 0 ORDER BY typical_range_max DESC"
        ).fetchall()
        return [dict(row) for row in rows]

    def add_vibration_preset(
        self,
        name: str,
        range_min: float,
        range_max: float,
        category: str = "",
        description: str = "",
        color: str = "#4A90D9",
    ) -> int:
        """Insert a user-defined vibration preset. Returns new row id."""
        assert self._conn is not None
        cursor = self._conn.cursor()
        cursor.execute(
            """INSERT INTO vibration_presets
               (name, typical_range_min, typical_range_max, category, description, color, is_builtin)
               VALUES (?, ?, ?, ?, ?, ?, 0)""",
            (name, range_min, range_max, category, description, color),
        )
        self._conn.commit()
        row_id = cursor.lastrowid
        if row_id is None:
            raise RuntimeError("SQLite did not return an id for the inserted vibration preset")
        return row_id

    def update_vibration_preset(
        self,
        preset_id: int,
        *,
        name: str,
        range_min: float,
        range_max: float,
        category: str = "",
        description: str = "",
        color: str | None = None,
    ) -> None:
        """Change a vibration preset, built-in or custom.

        A built-in entry keeps its ``seed_name``, so it can still be reset to
        what it shipped as and the functional-group knowledge base still finds
        it under its original name.

        Raises:
            ValueError: If the name is empty.
        """
        assert self._conn is not None
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("A vibration needs a name")
        low, high = sorted((float(range_min), float(range_max)))
        if color is None:
            self._conn.execute(
                """UPDATE vibration_presets
                   SET name = ?, typical_range_min = ?, typical_range_max = ?,
                       category = ?, description = ?
                   WHERE id = ?""",
                (clean_name, low, high, category, description, preset_id),
            )
        else:
            self._conn.execute(
                """UPDATE vibration_presets
                   SET name = ?, typical_range_min = ?, typical_range_max = ?,
                       category = ?, description = ?, color = ?
                   WHERE id = ?""",
                (clean_name, low, high, category, description, color, preset_id),
            )
        self._conn.commit()

    def delete_vibration_preset(self, preset_id: int) -> None:
        """Remove a vibration preset by id.

        A custom preset is deleted. A built-in one is only hidden, so
        :meth:`reset_builtin_vibration_presets` can bring it back and a later
        seed does not mistake it for a missing entry.
        """
        assert self._conn is not None
        self._conn.execute(
            "DELETE FROM vibration_presets WHERE id = ? AND is_builtin = 0",
            (preset_id,),
        )
        self._conn.execute(
            "UPDATE vibration_presets SET is_hidden = 1 WHERE id = ? AND is_builtin = 1",
            (preset_id,),
        )
        self._conn.commit()

    def reset_builtin_vibration_presets(self) -> int:
        """Put every built-in vibration back the way it shipped.

        Edited entries get their original name, range, category, description
        and colour; removed ones return. Row ids are kept, so assignments that
        refer to a built-in vibration stay valid. Custom vibrations are not
        touched. Returns how many built-in entries were changed or restored.
        """
        assert self._conn is not None
        cursor = self._conn.cursor()
        existing = {
            str(row["seed_name"]): row
            for row in cursor.execute(
                "SELECT * FROM vibration_presets WHERE is_builtin = 1 AND seed_name IS NOT NULL"
            ).fetchall()
        }
        changed = 0
        for (
            name,
            range_min,
            range_max,
            category,
            description,
            color,
        ) in self._builtin_vibration_catalog():
            row = existing.get(name)
            if row is None:
                cursor.execute(
                    """INSERT INTO vibration_presets
                       (name, typical_range_min, typical_range_max, category, description,
                        color, is_builtin, seed_name)
                       VALUES (?, ?, ?, ?, ?, ?, 1, ?)""",
                    (name, range_min, range_max, category, description, color, name),
                )
                changed += 1
                continue
            current = (
                row["name"],
                float(row["typical_range_min"]),
                float(row["typical_range_max"]),
                row["category"],
                row["description"],
                row["color"],
                int(row["is_hidden"]),
            )
            if current == (name, range_min, range_max, category, description, color, 0):
                continue
            cursor.execute(
                """UPDATE vibration_presets
                   SET name = ?, typical_range_min = ?, typical_range_max = ?, category = ?,
                       description = ?, color = ?, is_hidden = 0
                   WHERE id = ?""",
                (name, range_min, range_max, category, description, color, row["id"]),
            )
            changed += 1
        self._conn.commit()
        return changed

    def add_reference_spectrum(
        self,
        name: str,
        wavenumbers: np.ndarray,
        intensities: np.ndarray,
        description: str = "",
        source: str = "",
        y_unit: str = "Absorbance",
        *,
        source_provider: str = "local",
        external_id: str = "",
        sample_state: str = "",
        sampling_procedure: str = "",
        path_length: str = "",
        resolution: str = "",
        origin: str = "",
        owner: str = "",
        source_mtime_ns: int = 0,
        source_size: int = 0,
        commit: bool = True,
    ) -> int:
        """Insert a reference spectrum. Returns new row id."""
        assert self._conn is not None
        normalized_source = normalize_source_path(source) if source else ""
        cursor = self._conn.cursor()
        cursor.execute(
            """INSERT INTO reference_spectra
               (name, description, source, source_norm, source_provider, external_id,
                sample_state, sampling_procedure, path_length, resolution, origin, owner,
                source_mtime_ns, source_size, n_points, wavenumbers, intensities, y_unit)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                name,
                description,
                source,
                normalized_source,
                source_provider,
                external_id,
                sample_state,
                sampling_procedure,
                path_length,
                resolution,
                origin,
                owner,
                int(source_mtime_ns),
                int(source_size),
                int(len(wavenumbers)),
                wavenumbers.astype(np.float64).tobytes(),
                intensities.astype(np.float64).tobytes(),
                y_unit,
            ),
        )
        if commit:
            self._conn.commit()
        row_id = cursor.lastrowid
        if row_id is None:
            raise RuntimeError("SQLite did not return an id for the inserted reference spectrum")
        return row_id

    def update_reference_spectrum(
        self,
        ref_id: int,
        *,
        name: str,
        wavenumbers: np.ndarray,
        intensities: np.ndarray,
        description: str = "",
        source: str = "",
        y_unit: str = "Absorbance",
        source_mtime_ns: int = 0,
        source_size: int = 0,
        source_provider: str = "local",
        external_id: str = "",
        sample_state: str = "",
        sampling_procedure: str = "",
        path_length: str = "",
        resolution: str = "",
        origin: str = "",
        owner: str = "",
        commit: bool = True,
    ) -> None:
        """Replace a stored reference spectrum in-place."""
        assert self._conn is not None
        normalized_source = normalize_source_path(source) if source else ""
        self._conn.execute(
            """UPDATE reference_spectra
               SET name = ?, description = ?, source = ?, source_norm = ?,
                   source_provider = ?, external_id = ?, sample_state = ?,
                   sampling_procedure = ?, path_length = ?, resolution = ?,
                   origin = ?, owner = ?, source_mtime_ns = ?, source_size = ?,
                   n_points = ?, wavenumbers = ?, intensities = ?, y_unit = ?
               WHERE id = ?""",
            (
                name,
                description,
                source,
                normalized_source,
                source_provider,
                external_id,
                sample_state,
                sampling_procedure,
                path_length,
                resolution,
                origin,
                owner,
                int(source_mtime_ns),
                int(source_size),
                int(len(wavenumbers)),
                wavenumbers.astype(np.float64).tobytes(),
                intensities.astype(np.float64).tobytes(),
                y_unit,
                ref_id,
            ),
        )
        if commit:
            self._conn.commit()

    def get_reference_spectra(self) -> list[dict]:
        """Return all reference spectra as list of dicts (wavenumbers/intensities as ndarray)."""
        assert self._conn is not None
        rows = self._conn.execute("SELECT * FROM reference_spectra ORDER BY name").fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["wavenumbers"] = np.frombuffer(d["wavenumbers"], dtype=np.float64).copy()
            d["intensities"] = np.frombuffer(d["intensities"], dtype=np.float64).copy()
            result.append(d)
        return result

    def get_reference_metadata(
        self,
        *,
        source_prefix: str | None = None,
        include_web_refs: bool = False,
    ) -> list[dict]:
        """Return lightweight reference rows without loading spectral BLOB arrays."""
        assert self._conn is not None
        sql = """
            SELECT id, name, description, source, source_norm, source_provider, external_id,
                   sample_state, sampling_procedure, path_length, resolution, origin, owner,
                   source_mtime_ns, source_size, n_points, y_unit, created_at
            FROM reference_spectra
        """
        params: tuple[object, ...] = ()
        where_sql, params = self._reference_source_prefix_clause(
            source_prefix,
            include_web_refs=include_web_refs,
        )
        if where_sql:
            sql += f" WHERE {where_sql}"
        sql += " ORDER BY name"
        rows = self._conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def get_reference_identity_rows(self) -> list[dict]:
        """Return the metadata needed for duplicate detection and sync decisions."""
        assert self._conn is not None
        rows = self._conn.execute(
            """
            SELECT id, name, source, source_norm, source_provider, external_id,
                   source_mtime_ns, source_size
            FROM reference_spectra
            ORDER BY name
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def get_reference_spectrum_by_id(self, ref_id: int) -> dict | None:
        """Return one reference spectrum with decoded arrays, or None if missing."""
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT * FROM reference_spectra WHERE id = ?",
            (ref_id,),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["wavenumbers"] = np.frombuffer(result["wavenumbers"], dtype=np.float64).copy()
        result["intensities"] = np.frombuffer(result["intensities"], dtype=np.float64).copy()
        return result

    @staticmethod
    def _name_filter_clause(name_filter: str | None) -> tuple[str, tuple[object, ...]]:
        """Return SQL + params for a case-insensitive name-substring filter."""
        text = (name_filter or "").strip()
        if not text:
            return "", ()
        escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return "rs.name LIKE ? ESCAPE '\\'", (f"%{escaped}%",)

    def get_reference_search_rows(
        self,
        *,
        source_prefix: str | None = None,
        include_web_refs: bool = False,
        feature_version: int,
        name_filter: str | None = None,
    ) -> list[dict]:
        """Return metadata + stored feature vectors for similarity search."""
        assert self._conn is not None
        sql = """
            SELECT rs.id, rs.name, rs.description, rs.source, rs.source_provider,
                   rs.external_id, rs.sample_state, rs.sampling_procedure,
                   rs.path_length, rs.resolution, rs.origin, rs.owner,
                   rs.y_unit, rs.n_points, rf.feature_vector
            FROM reference_spectra rs
            JOIN reference_features rf
              ON rf.reference_id = rs.id
             AND rf.feature_version = ?
        """
        params_list: list[object] = [int(feature_version)]
        conditions: list[str] = []
        prefix_sql, prefix_params = self._reference_source_prefix_clause(
            source_prefix,
            alias="rs",
            include_web_refs=include_web_refs,
        )
        if prefix_sql:
            conditions.append(prefix_sql)
            params_list.extend(prefix_params)
        name_sql, name_params = self._name_filter_clause(name_filter)
        if name_sql:
            conditions.append(name_sql)
            params_list.extend(name_params)
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY rs.name"
        rows = self._conn.execute(sql, tuple(params_list)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["feature_vector"] = np.frombuffer(item["feature_vector"], dtype=np.float32).copy()
            result.append(item)
        return result

    def get_reference_library_state(
        self,
        *,
        source_prefix: str | None = None,
        include_web_refs: bool = False,
        feature_version: int,
        name_filter: str | None = None,
    ) -> tuple[int, int]:
        """Return a cheap (count, max_id) fingerprint of the searchable library.

        Used to skip re-fetching all feature BLOBs when the library has not
        changed between two searches — important for very large libraries.
        """
        assert self._conn is not None
        sql = """
            SELECT COUNT(*), COALESCE(MAX(rs.id), 0)
            FROM reference_spectra rs
            JOIN reference_features rf
              ON rf.reference_id = rs.id
             AND rf.feature_version = ?
        """
        params_list: list[object] = [int(feature_version)]
        conditions: list[str] = []
        prefix_sql, prefix_params = self._reference_source_prefix_clause(
            source_prefix,
            alias="rs",
            include_web_refs=include_web_refs,
        )
        if prefix_sql:
            conditions.append(prefix_sql)
            params_list.extend(prefix_params)
        name_sql, name_params = self._name_filter_clause(name_filter)
        if name_sql:
            conditions.append(name_sql)
            params_list.extend(name_params)
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        row = self._conn.execute(sql, tuple(params_list)).fetchone()
        return (int(row[0]), int(row[1]))

    def get_references_missing_features(
        self,
        *,
        source_prefix: str | None = None,
        include_web_refs: bool = False,
        feature_version: int,
    ) -> list[dict]:
        """Return stored spectra that do not yet have a cached search feature."""
        assert self._conn is not None
        sql = """
            SELECT rs.*
            FROM reference_spectra rs
            LEFT JOIN reference_features rf
              ON rf.reference_id = rs.id
             AND rf.feature_version = ?
            WHERE rf.reference_id IS NULL
        """
        params_list: list[object] = [int(feature_version)]
        where_sql, where_params = self._reference_source_prefix_clause(
            source_prefix,
            alias="rs",
            include_web_refs=include_web_refs,
        )
        if where_sql:
            sql += f" AND {where_sql}"
            params_list.extend(where_params)
        sql += " ORDER BY rs.name"
        rows = self._conn.execute(sql, tuple(params_list)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["wavenumbers"] = np.frombuffer(item["wavenumbers"], dtype=np.float64).copy()
            item["intensities"] = np.frombuffer(item["intensities"], dtype=np.float64).copy()
            result.append(item)
        return result

    def upsert_reference_feature(
        self,
        ref_id: int,
        *,
        feature_version: int,
        feature_vector: np.ndarray,
        commit: bool = True,
    ) -> None:
        """Insert or replace a cached search feature vector for a reference."""
        assert self._conn is not None
        self._conn.execute(
            """
            INSERT OR REPLACE INTO reference_features
            (reference_id, feature_version, feature_vector, created_at)
            VALUES (?, ?, ?, datetime('now'))
            """,
            (
                int(ref_id),
                int(feature_version),
                np.asarray(feature_vector, dtype=np.float32).tobytes(),
            ),
        )
        if commit:
            self._conn.commit()

    def delete_stale_reference_features(self, *, feature_version: int) -> int:
        """Drop cached vectors of superseded feature versions. Returns rows removed.

        A feature-version bump leaves the previous vectors behind; on a large
        library that is tens of megabytes of data nothing can read any more.
        """
        assert self._conn is not None
        cursor = self._conn.execute(
            "DELETE FROM reference_features WHERE feature_version != ?",
            (int(feature_version),),
        )
        self._conn.commit()
        return int(cursor.rowcount or 0)

    def delete_reference_spectrum(self, ref_id: int) -> None:
        """Delete a reference spectrum by id."""
        assert self._conn is not None
        self._conn.execute("DELETE FROM reference_features WHERE reference_id = ?", (ref_id,))
        self._conn.execute("DELETE FROM reference_spectra WHERE id = ?", (ref_id,))
        self._conn.commit()

    def clear_reference_spectra(self) -> int:
        """Delete every reference spectrum and its cached feature. Returns count removed."""
        assert self._conn is not None
        count = self._conn.execute("SELECT COUNT(*) FROM reference_spectra").fetchone()[0]
        self._conn.execute("DELETE FROM reference_features")
        self._conn.execute("DELETE FROM reference_spectra")
        self._conn.commit()
        return int(count)

    def rename_reference_spectrum(self, ref_id: int, new_name: str) -> None:
        """Rename a reference spectrum by id."""
        assert self._conn is not None
        self._conn.execute(
            "UPDATE reference_spectra SET name = ? WHERE id = ?",
            (new_name, ref_id),
        )
        self._conn.commit()

    def update_reference_description(self, ref_id: int, description: str) -> None:
        """Update the description field of a reference spectrum by id."""
        assert self._conn is not None
        self._conn.execute(
            "UPDATE reference_spectra SET description = ? WHERE id = ?",
            (description, ref_id),
        )
        self._conn.commit()

    @staticmethod
    def _reference_source_prefix_clause(
        source_prefix: str | None,
        *,
        alias: str = "",
        include_web_refs: bool = False,
    ) -> tuple[str, tuple[object, ...]]:
        """Return SQL + parameters for a folder-scoped `source_norm` filter."""
        if not source_prefix:
            return "", ()
        column = f"{alias}.source_norm" if alias else "source_norm"
        provider_column = f"{alias}.source_provider" if alias else "source_provider"
        prefix = source_prefix.rstrip("/\\")
        escaped_prefix = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        local_scope_clause = f"({column} = ? OR {column} LIKE ? ESCAPE '\\')"
        if include_web_refs:
            provider_expr = f"coalesce(nullif({provider_column}, ''), 'local')"
            return (
                f"({local_scope_clause} OR {provider_expr} != 'local')",
                (prefix, f"{escaped_prefix}/%"),
            )
        return (
            local_scope_clause,
            (prefix, f"{escaped_prefix}/%"),
        )

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
