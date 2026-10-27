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
    "ALTER TABLE datasources ADD COLUMN IF NOT EXISTS secret_form VARCHAR(16) NOT NULL DEFAULT 'password'",
    "ALTER TABLE llm_providers ADD COLUMN IF NOT EXISTS secret_backend VARCHAR(32) NOT NULL DEFAULT 'db'",
    "ALTER TABLE llm_providers ADD COLUMN IF NOT EXISTS secret_provider_id UUID",
    "ALTER TABLE llm_providers ADD COLUMN IF NOT EXISTS secret_path TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE llm_providers ADD COLUMN IF NOT EXISTS secret_ref JSONB NOT NULL DEFAULT '{}'::jsonb",
]


# Rows that already stored a full URL in Conjur/CCP/Kubernetes had no host or user.
# Keep them working by marking that shape as url. A password-form row has both fields.
_URL_LEGACY = """
UPDATE datasources SET secret_form = 'url'
WHERE secret_form = 'password'
  AND COALESCE(host, '') = '' AND COALESCE(username, '') = ''
  AND (
    secret_backend IN ('conjur', 'ccp', 'vault', 'kubernetes')
    OR (
      COALESCE(secret_backend, 'db') = 'db'
      AND COALESCE(k8s_secret_name, '') <> ''
      AND COALESCE(password_ciphertext, '') = ''
    )
  )
"""


_TABLES = [
    """
    CREATE TABLE IF NOT EXISTS delivery_channels (
      id UUID PRIMARY KEY,
      name VARCHAR(63) NOT NULL UNIQUE,
      kind VARCHAR(16) NOT NULL,
      enabled BOOLEAN NOT NULL DEFAULT true,
      from_address VARCHAR(320) NOT NULL DEFAULT '',
      from_name VARCHAR(120) NOT NULL DEFAULT '',
      allow_domains JSONB NOT NULL DEFAULT '[]'::jsonb,
      max_attachment_bytes INTEGER NOT NULL DEFAULT 2000000,
      secret_backend VARCHAR(32) NOT NULL DEFAULT 'db',
      secret_provider_id UUID,
      secret_path TEXT NOT NULL DEFAULT '',
      secret_ref JSONB NOT NULL DEFAULT '{}'::jsonb,
      k8s_secret_name VARCHAR(253),
      k8s_secret_key VARCHAR(253),
      credential_ciphertext TEXT NOT NULL DEFAULT '',
      credential_hint VARCHAR(16) NOT NULL DEFAULT '',
      config JSONB NOT NULL DEFAULT '{}'::jsonb,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS delivery_logs (
      id UUID PRIMARY KEY,
      run_id UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
      channel_id UUID REFERENCES delivery_channels(id) ON DELETE SET NULL,
      channel_name VARCHAR(63) NOT NULL DEFAULT '',
      recipients JSONB NOT NULL DEFAULT '{}'::jsonb,
      subject VARCHAR(300) NOT NULL DEFAULT '',
      status VARCHAR(16) NOT NULL DEFAULT 'failed',
      error TEXT,
      detail JSONB NOT NULL DEFAULT '{}'::jsonb,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_delivery_logs_run_id ON delivery_logs (run_id)",
    "CREATE INDEX IF NOT EXISTS ix_delivery_logs_created_at ON delivery_logs (created_at)",
]


def apply_migrations(conn: Connection) -> None:
    for statement in _COLUMNS:
        conn.execute(text(statement))
    conn.execute(text(_URL_LEGACY))
    for statement in _TABLES:
        conn.execute(text(statement))
