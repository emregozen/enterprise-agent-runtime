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
    "ALTER TABLE datasources ADD COLUMN IF NOT EXISTS secret_backend VARCHAR(32) NOT NULL DEFAULT 'db'",
    "ALTER TABLE datasources ADD COLUMN IF NOT EXISTS secret_provider_id UUID",
    "ALTER TABLE datasources ADD COLUMN IF NOT EXISTS secret_path TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE datasources ADD COLUMN IF NOT EXISTS secret_ref JSONB NOT NULL DEFAULT '{}'::jsonb",
    "ALTER TABLE llm_providers ADD COLUMN IF NOT EXISTS secret_backend VARCHAR(32) NOT NULL DEFAULT 'db'",
    "ALTER TABLE llm_providers ADD COLUMN IF NOT EXISTS secret_provider_id UUID",
    "ALTER TABLE llm_providers ADD COLUMN IF NOT EXISTS secret_path TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE llm_providers ADD COLUMN IF NOT EXISTS secret_ref JSONB NOT NULL DEFAULT '{}'::jsonb",
]


def apply_migrations(conn: Connection) -> None:
    for statement in _COLUMNS:
        conn.execute(text(statement))
