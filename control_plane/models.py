from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from control_plane.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(63), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    owner: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(20), default="draft")
    current_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AgentVersion(Base):
    __tablename__ = "agent_versions"
    __table_args__ = (UniqueConstraint("agent_id", "version", name="uq_agent_version"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    spec: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DataSourceRecord(Base):
    __tablename__ = "datasources"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(63), unique=True, index=True)
    dialect: Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(Text, default="")
    dsn_env: Mapped[str] = mapped_column(String(120))
    allow_tables: Mapped[list] = mapped_column(JSONB)
    sensitivity: Mapped[str] = mapped_column(String(32), default="internal")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    k8s_secret_name: Mapped[str | None] = mapped_column(String(253), nullable=True)
    k8s_secret_key: Mapped[str | None] = mapped_column(String(253), nullable=True)
    host: Mapped[str] = mapped_column(String(255), default="")
    port: Mapped[int] = mapped_column(Integer, default=5432)
    database_name: Mapped[str] = mapped_column(String(128), default="")
    username: Mapped[str] = mapped_column(String(128), default="")
    password_ciphertext: Mapped[str] = mapped_column(Text, default="")
    password_hint: Mapped[str] = mapped_column(String(16), default="")
    # db | kubernetes | conjur | ccp. External backends store a reference, never the value.
    secret_backend: Mapped[str] = mapped_column(String(32), default="db")
    secret_provider_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("secret_providers.id"), nullable=True
    )
    secret_path: Mapped[str] = mapped_column(Text, default="")
    secret_ref: Mapped[dict] = mapped_column(JSONB, default=dict)
    # password: the reference is only the password. url: the reference is the full connection URL.
    secret_form: Mapped[str] = mapped_column(String(16), default="password")
    options: Mapped[dict] = mapped_column(JSONB, default=dict)
    read_only: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LlmProvider(Base):
    __tablename__ = "llm_providers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(63), unique=True, index=True)
    base_url: Mapped[str] = mapped_column(String(300))
    model: Mapped[str] = mapped_column(String(120))
    api_key_ciphertext: Mapped[str] = mapped_column(Text, default="")
    api_key_hint: Mapped[str] = mapped_column(String(16), default="")
    k8s_secret_name: Mapped[str | None] = mapped_column(String(253), nullable=True)
    k8s_secret_key: Mapped[str | None] = mapped_column(String(253), nullable=True)
    secret_backend: Mapped[str] = mapped_column(String(32), default="db")
    secret_provider_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("secret_providers.id"), nullable=True
    )
    secret_path: Mapped[str] = mapped_column(Text, default="")
    secret_ref: Mapped[dict] = mapped_column(JSONB, default=dict)
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    reasoning_effort: Mapped[str] = mapped_column(String(32), default="")
    extra_params: Mapped[dict] = mapped_column(JSONB, default=dict)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SecretProvider(Base):
    """A Conjur, CCP, or future Vault/OpenBao endpoint. Credentials are a Kubernetes Secret reference."""

    __tablename__ = "secret_providers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(63), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(32))
    base_url: Mapped[str] = mapped_column(String(300))
    account: Mapped[str] = mapped_column(String(128), default="")
    auth_method: Mapped[str] = mapped_column(String(32), default="api-key")
    ca_bundle: Mapped[str] = mapped_column(Text, default="")
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    credential_secret_name: Mapped[str] = mapped_column(String(253), default="")
    credential_secret_key: Mapped[str] = mapped_column(String(253), default="api_key")
    tls_cert_key: Mapped[str] = mapped_column(String(253), default="")
    tls_key_key: Mapped[str] = mapped_column(String(253), default="")
    credential_namespace: Mapped[str] = mapped_column(String(63), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LlmCall(Base):
    __tablename__ = "llm_calls"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("runs.id"), nullable=True, index=True)
    provider_name: Mapped[str] = mapped_column(String(63), default="")
    model: Mapped[str] = mapped_column(String(120), default="")
    purpose: Mapped[str] = mapped_column(String(32), default="plan")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Schedule(Base):
    __tablename__ = "schedules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id"), unique=True, index=True)
    mode: Mapped[str] = mapped_column(String(16), default="manual")
    cron: Mapped[str | None] = mapped_column(String(120), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Istanbul")
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    min_interval_seconds: Mapped[int] = mapped_column(Integer, default=3600)
    max_interval_seconds: Mapped[int] = mapped_column(Integer, default=7 * 86400)
    max_runs_per_day: Mapped[int] = mapped_column(Integer, default=4)
    window: Mapped[str] = mapped_column(String(32), default="07:00-20:00")
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    concurrency: Mapped[str] = mapped_column(String(16), default="forbid")
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id"), index=True)
    agent_name: Mapped[str] = mapped_column(String(63))
    spec_version: Mapped[int] = mapped_column(Integer)
    spec_snapshot: Mapped[dict] = mapped_column(JSONB)
    trigger: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)
    job_name: Mapped[str | None] = mapped_column(String(63), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), unique=True, nullable=True)
    run_token_hash: Mapped[str] = mapped_column(String(64))
    summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    report_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    needs_review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    log_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RunStep(Base):
    __tablename__ = "run_steps"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20))
    detail: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ToolCall(Base):
    __tablename__ = "tool_calls"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id"), index=True)
    tool_name: Mapped[str] = mapped_column(String(64))
    request: Mapped[dict] = mapped_column(JSONB)
    response: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(120))
    action: Mapped[str] = mapped_column(String(80))
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str] = mapped_column(String(80))
    detail: Mapped[dict] = mapped_column(JSONB)


class DeliveryChannel(Base):
    """SMTP or HTTP delivery. The credential is a secret reference, never returned by the API."""

    __tablename__ = "delivery_channels"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(63), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(16))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    from_address: Mapped[str] = mapped_column(String(320), default="")
    from_name: Mapped[str] = mapped_column(String(120), default="")
    allow_domains: Mapped[list] = mapped_column(JSONB, default=list)
    max_attachment_bytes: Mapped[int] = mapped_column(Integer, default=2_000_000)
    secret_backend: Mapped[str] = mapped_column(String(32), default="db")
    secret_provider_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("secret_providers.id"), nullable=True
    )
    secret_path: Mapped[str] = mapped_column(Text, default="")
    secret_ref: Mapped[dict] = mapped_column(JSONB, default=dict)
    k8s_secret_name: Mapped[str | None] = mapped_column(String(253), nullable=True)
    k8s_secret_key: Mapped[str | None] = mapped_column(String(253), nullable=True)
    credential_ciphertext: Mapped[str] = mapped_column(Text, default="")
    credential_hint: Mapped[str] = mapped_column(String(16), default="")
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DeliveryLog(Base):
    __tablename__ = "delivery_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("delivery_channels.id", ondelete="SET NULL"), nullable=True
    )
    channel_name: Mapped[str] = mapped_column(String(63), default="")
    recipients: Mapped[dict] = mapped_column(JSONB, default=dict)
    subject: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(16), default="failed")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    media_type: Mapped[str] = mapped_column(String(120))
    storage_uri: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
