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

import numpy as np

from app.config import DB_PATH
from utils.file_utils import normalize_source_path


class Database:
    """SQLite database manager for IR Spectra Analyzer."""

    SCHEMA_VERSION = 1

    def __init__(self, db_path: str | Path = DB_PATH) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def initialize(self) -> None:
        """Create data directory, open connection, apply schema, seed data."""
        db_path = str(self._db_path)
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._apply_schema()
        self._seed_vibration_presets()

    def commit(self) -> None:
        """Commit the current transaction."""
        assert self._conn is not None
        self._conn.commit()

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
                reference_id     INTEGER NOT NULL,
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

        for column_sql in (
            "ALTER TABLE reference_spectra ADD COLUMN source_norm TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE reference_spectra ADD COLUMN source_mtime_ns INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE reference_spectra ADD COLUMN source_size INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE reference_spectra ADD COLUMN n_points INTEGER NOT NULL DEFAULT 0",
        ):
            try:
                cursor.execute(column_sql)
                self._conn.commit()
            except sqlite3.OperationalError:
                pass

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
        self._conn.commit()

    def _seed_vibration_presets(self) -> None:
        """Insert the builtin IR vibration preset library.

        The library started from the original VŠCHT Praha table and is extended
        with additional sourced diagnostic bands used by the functional-group
        scoring assistant. Re-seeds when the builtin library is outdated.
        """
        assert self._conn is not None
        cursor = self._conn.cursor()
        count_builtin = cursor.execute(
            "SELECT COUNT(*) FROM vibration_presets WHERE is_builtin = 1"
        ).fetchone()[0]
        has_second_wave = cursor.execute(
            "SELECT 1 FROM vibration_presets WHERE is_builtin = 1 AND name = ? LIMIT 1",
            ("ν(N=C=N) carbodiimide",),
        ).fetchone()
        # Re-seed if the builtin library does not contain the current sourced expansion.
        if count_builtin == 145 and has_second_wave:
            return
        cursor.execute("DELETE FROM vibration_presets WHERE is_builtin = 1")

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
        ]

        cursor.executemany(
            """INSERT INTO vibration_presets
               (name, typical_range_min, typical_range_max, category, description, color, is_builtin)
               VALUES (?, ?, ?, ?, ?, ?, 1)""",
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
        return cursor.lastrowid

    def delete_vibration_preset(self, preset_id: int) -> None:
        """Delete a custom (non-builtin) vibration preset by id."""
        assert self._conn is not None
        self._conn.execute(
            "DELETE FROM vibration_presets WHERE id = ? AND is_builtin = 0",
            (preset_id,),
        )
        self._conn.commit()

    def add_reference_spectrum(
        self,
        name: str,
        wavenumbers: np.ndarray,
        intensities: np.ndarray,
        description: str = "",
        source: str = "",
        y_unit: str = "Absorbance",
        *,
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
               (name, description, source, source_norm, source_mtime_ns, source_size,
                n_points, wavenumbers, intensities, y_unit)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                name,
                description,
                source,
                normalized_source,
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
        return cursor.lastrowid

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
        commit: bool = True,
    ) -> None:
        """Replace a stored reference spectrum in-place."""
        assert self._conn is not None
        normalized_source = normalize_source_path(source) if source else ""
        self._conn.execute(
            """UPDATE reference_spectra
               SET name = ?, description = ?, source = ?, source_norm = ?,
                   source_mtime_ns = ?, source_size = ?, n_points = ?,
                   wavenumbers = ?, intensities = ?, y_unit = ?
               WHERE id = ?""",
            (
                name,
                description,
                source,
                normalized_source,
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

    def get_reference_metadata(self, *, source_prefix: str | None = None) -> list[dict]:
        """Return lightweight reference rows without loading spectral BLOB arrays."""
        assert self._conn is not None
        sql = """
            SELECT id, name, description, source, source_norm, source_mtime_ns, source_size,
                   n_points, y_unit, created_at
            FROM reference_spectra
        """
        params: tuple[object, ...] = ()
        where_sql, params = self._reference_source_prefix_clause(source_prefix)
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
            SELECT id, name, source, source_norm, source_mtime_ns, source_size
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

    def get_reference_search_rows(
        self,
        *,
        source_prefix: str | None = None,
        feature_version: int,
    ) -> list[dict]:
        """Return metadata + stored feature vectors for similarity search."""
        assert self._conn is not None
        sql = """
            SELECT rs.id, rs.name, rs.description, rs.source, rs.y_unit, rs.n_points,
                   rf.feature_vector
            FROM reference_spectra rs
            JOIN reference_features rf
              ON rf.reference_id = rs.id
             AND rf.feature_version = ?
        """
        params_list: list[object] = [int(feature_version)]
        where_sql, where_params = self._reference_source_prefix_clause(source_prefix, alias="rs")
        if where_sql:
            sql += f" WHERE {where_sql}"
            params_list.extend(where_params)
        sql += " ORDER BY rs.name"
        rows = self._conn.execute(sql, tuple(params_list)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["feature_vector"] = np.frombuffer(item["feature_vector"], dtype=np.float32).copy()
            result.append(item)
        return result

    def get_references_missing_features(
        self,
        *,
        source_prefix: str | None = None,
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
        where_sql, where_params = self._reference_source_prefix_clause(source_prefix, alias="rs")
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

    def delete_reference_spectrum(self, ref_id: int) -> None:
        """Delete a reference spectrum by id."""
        assert self._conn is not None
        self._conn.execute("DELETE FROM reference_features WHERE reference_id = ?", (ref_id,))
        self._conn.execute("DELETE FROM reference_spectra WHERE id = ?", (ref_id,))
        self._conn.commit()

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
    ) -> tuple[str, tuple[object, ...]]:
        """Return SQL + parameters for a folder-scoped `source_norm` filter."""
        if not source_prefix:
            return "", ()
        column = f"{alias}.source_norm" if alias else "source_norm"
        prefix = source_prefix.rstrip("/\\")
        return (
            f"({column} = ? OR {column} LIKE ?)",
            (prefix, f"{prefix}/%"),
        )

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
