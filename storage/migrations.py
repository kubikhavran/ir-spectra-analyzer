"""
Migrations — Migrace databázového schématu.

Zodpovědnost:
- Verzování schématu SQLite
- Bezpečné in-place migrace při aktualizaci aplikace
- Tracking aplikované verze migrace v tabulce schema_version
"""

from __future__ import annotations

import sqlite3


def run_migrations(conn: sqlite3.Connection, current_version: int) -> int:
    """Apply all pending database migrations.

    Args:
        conn: Open SQLite connection.
        current_version: Currently applied schema version.

    Returns:
        New schema version after applying migrations.
    """
    migrations: dict[int, str] = {
        # Future migrations appended here:
        # 2: "ALTER TABLE peaks ADD COLUMN confidence REAL DEFAULT 0.0;"
    }

    for version, sql in sorted(migrations.items()):
        if version > current_version:
            conn.executescript(sql)
            conn.commit()
            current_version = version

    return current_version
