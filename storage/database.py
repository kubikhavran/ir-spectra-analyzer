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
from pathlib import Path

from app.config import DB_PATH


class Database:
    """SQLite database manager for IR Spectra Analyzer."""

    SCHEMA_VERSION = 1

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def initialize(self) -> None:
        """Create data directory, open connection, apply schema, seed data."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._apply_schema()
        self._seed_vibration_presets()

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
        """)
        self._conn.commit()

    def _seed_vibration_presets(self) -> None:
        """Insert default vibration presets if table is empty."""
        assert self._conn is not None
        cursor = self._conn.cursor()
        count = cursor.execute("SELECT COUNT(*) FROM vibration_presets").fetchone()[0]
        if count > 0:
            return

        presets = [
            # (name, range_min, range_max, category, description, color)
            ("O-H stretch",           3200.0, 3600.0, "stretch",
             "Broad O-H stretching vibration (alcohols, phenols, carboxylic acids)", "#E74C3C"),
            ("N-H stretch",           3300.0, 3500.0, "stretch",
             "N-H stretching vibration (primary/secondary amines, amides)",          "#E67E22"),
            ("C-H stretch aromatic",  3000.0, 3100.0, "stretch",
             "Aromatic C-H stretching vibrations",                                   "#9B59B6"),
            ("C-H stretch aliphatic", 2850.0, 3000.0, "stretch",
             "Aliphatic C-H stretching (CH3, CH2, CH groups)",                       "#8E44AD"),
            ("C≡N stretch",           2200.0, 2260.0, "stretch",
             "Nitrile C≡N stretching vibration",                                     "#1ABC9C"),
            ("C=O stretch",           1680.0, 1750.0, "stretch",
             "Carbonyl C=O stretching (esters, ketones, aldehydes, carboxylic acids)", "#E74C3C"),
            ("C=C aromatic",          1450.0, 1600.0, "stretch",
             "Aromatic ring C=C stretching vibrations",                              "#3498DB"),
            ("C-H bend",              1350.0, 1470.0, "bend",
             "C-H in-plane bending vibrations",                                      "#27AE60"),
            ("C-O stretch",           1000.0, 1260.0, "stretch",
             "C-O stretching vibrations (ethers, esters, alcohols)",                 "#F39C12"),
            ("C-Cl stretch",           600.0,  800.0, "stretch",
             "C-Cl stretching vibration",                                            "#7F8C8D"),
            ("C-Br stretch",           500.0,  700.0, "stretch",
             "C-Br stretching vibration",                                            "#95A5A6"),
            ("Fingerprint region",     500.0, 1500.0, "region",
             "Complex fingerprint region with skeletal vibrations",                  "#BDC3C7"),
        ]

        cursor.executemany(
            """INSERT INTO vibration_presets
               (name, typical_range_min, typical_range_max, category, description, color)
               VALUES (?, ?, ?, ?, ?, ?)""",
            presets,
        )
        self._conn.commit()

    def get_vibration_presets(self) -> list[dict]:
        """Return all vibration presets as list of dicts."""
        assert self._conn is not None
        rows = self._conn.execute(
            "SELECT * FROM vibration_presets ORDER BY typical_range_max DESC"
        ).fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
