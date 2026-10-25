"""Additive schema updates for databases created before the config tables existed."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection


_COLUMNS = [
    "ALTER TABLE datasources ADD COLUMN IF NOT EXISTS host VARCHAR(255) NOT NULL DEFAULT ''",
    "ALTER TABLE datasources ADD COLUMN IF NOT EXISTS port INTEGER NOT NULL DEFAULT 5432",
    "ALTER TABLE datasources ADD COLUMN IF NOT EXISTS database_name VARCHAR(128) NOT NULL DEFAULT ''",
    "ALTER TABLE datasources ADD COLUMN IF NOT EXISTS username VARCHAR(128) NOT NULL DEFAULT ''",
    "ALTER TABLE datasources ADD COLUMN IF NOT EXISTS password_ciphertext TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE datasources ADD COLUMN IF NOT EXISTS password_hint VARCHAR(16) NOT NULL DEFAULT ''",
    "ALTER TABLE datasources ADD COLUMN IF NOT EXISTS options JSONB NOT NULL DEFAULT '{}'::jsonb",
    "ALTER TABLE datasources ADD COLUMN IF NOT EXISTS read_only BOOLEAN NOT NULL DEFAULT true",
]


def apply_migrations(conn: Connection) -> None:
    for statement in _COLUMNS:
        conn.execute(text(statement))
