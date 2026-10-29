"""Additive schema updates for databases created before the config tables existed."""

from __future__ import annotations

import uuid
from sqlalchemy import text
from sqlalchemy.engine import Connection

DEFAULT_GROUP_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
DEFAULT_GROUP_NAME = "default"

_AUTH_TABLES = [
    """
    CREATE TABLE IF NOT EXISTS groups (
      id UUID PRIMARY KEY,
      name VARCHAR(63) NOT NULL UNIQUE,
      description TEXT NOT NULL DEFAULT '',
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS users (
      id UUID PRIMARY KEY,
      issuer VARCHAR(300) NOT NULL,
      sub VARCHAR(200) NOT NULL,
      email VARCHAR(320) NOT NULL,
      display_name VARCHAR(200) NOT NULL DEFAULT '',
      status VARCHAR(20) NOT NULL DEFAULT 'pending',
      is_admin BOOLEAN NOT NULL DEFAULT false,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      last_login_at TIMESTAMPTZ,
      CONSTRAINT uq_user_issuer_sub UNIQUE (issuer, sub)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS group_memberships (
      id UUID PRIMARY KEY,
      user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      group_id UUID NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
      role VARCHAR(20) NOT NULL DEFAULT 'viewer',
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      CONSTRAINT uq_user_group_membership UNIQUE (user_id, group_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS auth_sessions (
      id UUID PRIMARY KEY,
      user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      token_hash VARCHAR(64) NOT NULL UNIQUE,
      csrf_token VARCHAR(64) NOT NULL,
      active_group_id UUID REFERENCES groups(id) ON DELETE SET NULL,
      id_token_hint TEXT NOT NULL DEFAULT '',
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      expires_at TIMESTAMPTZ NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_users_email ON users (email)",
    "CREATE INDEX IF NOT EXISTS ix_users_status ON users (status)",
    "CREATE INDEX IF NOT EXISTS ix_group_memberships_user_id ON group_memberships (user_id)",
    "CREATE INDEX IF NOT EXISTS ix_group_memberships_group_id ON group_memberships (group_id)",
    "CREATE INDEX IF NOT EXISTS ix_auth_sessions_user_id ON auth_sessions (user_id)",
    "CREATE INDEX IF NOT EXISTS ix_auth_sessions_expires_at ON auth_sessions (expires_at)",
]

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
    """
    CREATE TABLE IF NOT EXISTS chat_sessions (
        id UUID PRIMARY KEY,
        title VARCHAR(200) NOT NULL DEFAULT 'New conversation',
        datasource_name VARCHAR(120) NOT NULL,
        model_ref VARCHAR(120),
        owner_group_id UUID REFERENCES groups(id) ON DELETE SET NULL,
        created_by UUID REFERENCES users(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_chat_sessions_owner_group_id ON chat_sessions (owner_group_id)",
    "CREATE INDEX IF NOT EXISTS ix_chat_sessions_updated_at ON chat_sessions (updated_at)",
    """
    CREATE TABLE IF NOT EXISTS chat_messages (
        id UUID PRIMARY KEY,
        session_id UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
        ordinal INTEGER NOT NULL,
        role VARCHAR(20) NOT NULL,
        content TEXT NOT NULL DEFAULT '',
        sql TEXT,
        columns JSONB NOT NULL DEFAULT '[]'::jsonb,
        rows JSONB NOT NULL DEFAULT '[]'::jsonb,
        row_count INTEGER NOT NULL DEFAULT 0,
        latency_ms INTEGER,
        status VARCHAR(20) NOT NULL DEFAULT 'succeeded',
        error TEXT,
        guard_info JSONB NOT NULL DEFAULT '{}'::jsonb,
        follow_ups JSONB NOT NULL DEFAULT '[]'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_chat_messages_session_id ON chat_messages (session_id)",
    "CREATE INDEX IF NOT EXISTS ix_chat_messages_created_at ON chat_messages (created_at)",
]

_OWNERSHIP_COLUMNS = [
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS owner_group_id UUID REFERENCES groups(id) ON DELETE SET NULL",
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS created_by UUID REFERENCES users(id) ON DELETE SET NULL",
    "ALTER TABLE agent_versions ADD COLUMN IF NOT EXISTS owner_group_id UUID REFERENCES groups(id) ON DELETE SET NULL",
    "ALTER TABLE agent_versions ADD COLUMN IF NOT EXISTS created_by UUID REFERENCES users(id) ON DELETE SET NULL",
    "ALTER TABLE datasources ADD COLUMN IF NOT EXISTS owner_group_id UUID REFERENCES groups(id) ON DELETE SET NULL",
    "ALTER TABLE datasources ADD COLUMN IF NOT EXISTS created_by UUID REFERENCES users(id) ON DELETE SET NULL",
    "ALTER TABLE llm_providers ADD COLUMN IF NOT EXISTS owner_group_id UUID REFERENCES groups(id) ON DELETE SET NULL",
    "ALTER TABLE llm_providers ADD COLUMN IF NOT EXISTS created_by UUID REFERENCES users(id) ON DELETE SET NULL",
    "ALTER TABLE secret_providers ADD COLUMN IF NOT EXISTS owner_group_id UUID REFERENCES groups(id) ON DELETE SET NULL",
    "ALTER TABLE secret_providers ADD COLUMN IF NOT EXISTS created_by UUID REFERENCES users(id) ON DELETE SET NULL",
    "ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS owner_group_id UUID REFERENCES groups(id) ON DELETE SET NULL",
    "ALTER TABLE schedules ADD COLUMN IF NOT EXISTS owner_group_id UUID REFERENCES groups(id) ON DELETE SET NULL",
    "ALTER TABLE schedules ADD COLUMN IF NOT EXISTS created_by UUID REFERENCES users(id) ON DELETE SET NULL",
    "ALTER TABLE runs ADD COLUMN IF NOT EXISTS owner_group_id UUID REFERENCES groups(id) ON DELETE SET NULL",
    "ALTER TABLE runs ADD COLUMN IF NOT EXISTS created_by UUID REFERENCES users(id) ON DELETE SET NULL",
    "ALTER TABLE delivery_channels ADD COLUMN IF NOT EXISTS owner_group_id UUID REFERENCES groups(id) ON DELETE SET NULL",
    "ALTER TABLE delivery_channels ADD COLUMN IF NOT EXISTS created_by UUID REFERENCES users(id) ON DELETE SET NULL",
    "CREATE INDEX IF NOT EXISTS ix_agents_owner_group_id ON agents (owner_group_id)",
    "CREATE INDEX IF NOT EXISTS ix_datasources_owner_group_id ON datasources (owner_group_id)",
    "CREATE INDEX IF NOT EXISTS ix_llm_providers_owner_group_id ON llm_providers (owner_group_id)",
    "CREATE INDEX IF NOT EXISTS ix_secret_providers_owner_group_id ON secret_providers (owner_group_id)",
    "CREATE INDEX IF NOT EXISTS ix_runs_owner_group_id ON runs (owner_group_id)",
    "CREATE INDEX IF NOT EXISTS ix_delivery_channels_owner_group_id ON delivery_channels (owner_group_id)",
]

_OWNERSHIP_TABLES = (
    "agents",
    "agent_versions",
    "datasources",
    "llm_providers",
    "secret_providers",
    "llm_calls",
    "schedules",
    "runs",
    "delivery_channels",
)


def ensure_default_group_sql(conn: Connection | None = None) -> str | uuid.UUID:
    is_sqlite = conn is not None and conn.dialect.name == "sqlite"
    gid_literal = DEFAULT_GROUP_ID.hex if is_sqlite else str(DEFAULT_GROUP_ID)
    sql = (
        f"INSERT INTO groups (id, name, description, created_at) "
        f"VALUES ('{gid_literal}', '{DEFAULT_GROUP_NAME}', 'Default group for existing and initial resources', CURRENT_TIMESTAMP) "
        f"ON CONFLICT (name) DO NOTHING"
    )
    if conn is None:
        return sql
    conn.execute(text(sql))
    row = conn.execute(text("SELECT id FROM groups WHERE name = :name"), {"name": DEFAULT_GROUP_NAME}).fetchone()
    if row and row[0]:
        if isinstance(row[0], uuid.UUID):
            return row[0]
        raw = str(row[0]).strip()
        try:
            return uuid.UUID(raw)
        except ValueError:
            return DEFAULT_GROUP_ID
    return DEFAULT_GROUP_ID


def apply_migrations(conn: Connection) -> None:
    if conn.dialect.name == "postgresql":
        for statement in _AUTH_TABLES:
            conn.execute(text(statement))
        for statement in _COLUMNS:
            conn.execute(text(statement))
        conn.execute(text(_URL_LEGACY))
        for statement in _TABLES:
            conn.execute(text(statement))
        for statement in _OWNERSHIP_COLUMNS:
            conn.execute(text(statement))
    else:
        conn.execute(text(_URL_LEGACY))
    default_gid = ensure_default_group_sql(conn)
    assert isinstance(default_gid, uuid.UUID)
    gid_param = default_gid.hex if conn.dialect.name == "sqlite" else default_gid
    for table in _OWNERSHIP_TABLES:
        conn.execute(
            text(f"UPDATE {table} SET owner_group_id = :gid WHERE owner_group_id IS NULL"),
            {"gid": gid_param},
        )
