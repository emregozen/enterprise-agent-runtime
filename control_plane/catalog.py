"""UI-managed data sources and LLM providers. Secrets stay encrypted and out of API responses."""

from __future__ import annotations

import difflib
import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from sqlalchemy.orm import Session

from control_plane.models import Agent, AgentVersion, Artifact, DataSourceRecord, LlmCall, LlmProvider, Run, RunStep, Schedule, ToolCall, utcnow
from control_plane.policy import local_day_start
from shared.crypto import decrypt_secret, encrypt_secret, public_hint, redact, secret_hint


def find_datasource(db: Session, ref: str) -> DataSourceRecord | None:
    row = db.query(DataSourceRecord).filter(DataSourceRecord.name == ref).one_or_none()
    if row is not None:
        return row
    try:
        key = uuid.UUID(str(ref))
    except ValueError:
        return None
    return db.get(DataSourceRecord, key)


def _dsn_env_for(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in name.upper())
    return f"DS_{cleaned[:40]}"


def _password_configured(row: DataSourceRecord) -> bool:
    from secret_sources.resolve import effective_backend

    backend = effective_backend(row, "password_ciphertext")
    if backend == "kubernetes":
        return bool(row.k8s_secret_name)
    if backend == "conjur":
        return bool(row.secret_provider_id and (row.secret_path or "").strip())
    if backend == "ccp":
        ref = row.secret_ref or {}
        return bool(row.secret_provider_id and (ref.get("object") or ref.get("query")))
    return bool(row.password_ciphertext)


def datasource_out(row: DataSourceRecord) -> dict:
    import os

    from secret_sources.resolve import effective_backend

    backend = effective_backend(row, "password_ciphertext")
    password_set = _password_configured(row)
    hint = public_hint(row.password_ciphertext, row.password_hint)
    if password_set and not hint:
        hint = "••••"
    configured = bool(password_set or (row.dsn_env and os.environ.get(row.dsn_env)))
    return {
        "id": str(row.id),
        "name": row.name,
        "dialect": row.dialect,
        "description": row.description,
        "dsn_env": row.dsn_env,
        "allow_tables": row.allow_tables,
        "sensitivity": row.sensitivity,
        "enabled": row.enabled,
        "k8s_secret_name": row.k8s_secret_name,
        "k8s_secret_key": row.k8s_secret_key,
        "secret_backend": backend,
        "secret_provider_id": str(row.secret_provider_id) if row.secret_provider_id else None,
        "secret_path": row.secret_path or "",
        "secret_ref": row.secret_ref or {},
        "host": row.host or "",
        "port": row.port,
        "database_name": row.database_name or "",
        "username": row.username or "",
        "password_set": password_set,
        "password_hint": hint,
        "options": row.options or {},
        "read_only": bool(row.read_only),
        "configured": configured,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def apply_datasource(db: Session, row: DataSourceRecord, body, *, creating: bool, reset_secret_source: bool = False) -> None:
    from control_plane.service import ServiceError

    dialect = body.dialect
    if dialect == "postgresql":
        dialect = "postgres"
    if dialect not in {"postgres", "oracle", "ansi"}:
        raise ServiceError("dialect postgres, oracle veya ansi olmalı", 400)
    if body.sensitivity not in {"internal", "restricted"}:
        raise ServiceError("sensitivity internal veya restricted olmalı", 400)
    tables = list(body.allow_tables or [])
    if not tables:
        raise ServiceError("en az bir tablo gerekli", 400)
    row.dialect = dialect
    row.description = body.description or ""
    row.allow_tables = tables
    row.sensitivity = body.sensitivity
    row.enabled = body.enabled
    row.host = (body.host or "").strip()
    row.port = int(body.port or (1521 if dialect == "oracle" else 5432))
    row.database_name = (body.database_name or "").strip()
    row.username = (body.username or "").strip()
    row.options = dict(body.options or {})
    row.read_only = bool(body.read_only)
    if creating:
        row.name = body.name.strip()
        row.dsn_env = (body.dsn_env or "").strip() or _dsn_env_for(row.name)
    elif body.dsn_env:
        row.dsn_env = body.dsn_env.strip()
    if reset_secret_source or creating:
        _assign_secret_source(db, row, body, kind="password")
    else:
        row.k8s_secret_name = body.k8s_secret_name or None
        row.k8s_secret_key = body.k8s_secret_key or None
        if body.password:
            row.password_ciphertext = encrypt_secret(body.password)
            row.password_hint = secret_hint(body.password)


def _assign_secret_source(db: Session, row, body, *, kind: str) -> None:
    """Store a reference. A non-db backend never keeps the secret value."""
    from control_plane.service import ServiceError

    incoming = getattr(body, "password", None) if kind == "password" else getattr(body, "api_key", None)
    raw_backend = (getattr(body, "secret_backend", None) or "").strip()
    if not raw_backend:
        backend = "kubernetes" if (getattr(body, "k8s_secret_name", None) or "").strip() and not incoming else "db"
    else:
        backend = raw_backend
    if backend not in {"db", "kubernetes", "conjur", "ccp"}:
        raise ServiceError("parola kaynağı platform, kubernetes, conjur veya ccp olmalı", 400)
    row.secret_backend = backend
    if backend == "db":
        row.secret_provider_id = None
        row.secret_path = ""
        row.secret_ref = {}
        row.k8s_secret_name = None
        row.k8s_secret_key = None
        password = getattr(body, "password", None) if kind == "password" else getattr(body, "api_key", None)
        if password:
            if kind == "password":
                row.password_ciphertext = encrypt_secret(password)
                row.password_hint = secret_hint(password)
            else:
                row.api_key_ciphertext = encrypt_secret(password)
                row.api_key_hint = secret_hint(password)
        return
    if kind == "password":
        row.password_ciphertext = ""
        row.password_hint = ""
    else:
        row.api_key_ciphertext = ""
        row.api_key_hint = ""
    row.k8s_secret_name = None
    row.k8s_secret_key = None
    row.secret_provider_id = None
    row.secret_path = ""
    row.secret_ref = {}
    if backend == "kubernetes":
        name = (body.k8s_secret_name or "").strip()
        key = (body.k8s_secret_key or "").strip() or ("dsn" if kind == "password" else "api_key")
        if not name:
            raise ServiceError("Kubernetes Secret adı gerekli", 400)
        row.k8s_secret_name = name
        row.k8s_secret_key = key
        return
    provider = _provider_or_error(db, body.secret_provider_id, backend)
    row.secret_provider_id = provider.id
    if backend == "conjur":
        path = (body.secret_path or "").strip()
        if not path:
            raise ServiceError("Conjur değişken yolu gerekli", 400)
        row.secret_path = path
        return
    ref = dict(body.secret_ref or {})
    app_id = str(ref.get("app_id") or (provider.config or {}).get("app_id") or "").strip()
    if not app_id:
        raise ServiceError("CCP AppID gerekli", 400)
    if not str(ref.get("object") or "").strip() and not str(ref.get("query") or "").strip():
        raise ServiceError("CCP Object veya Query gerekli", 400)
    row.secret_ref = {
        "app_id": str(ref.get("app_id") or "").strip(),
        "safe": str(ref.get("safe") or "").strip(),
        "object": str(ref.get("object") or "").strip(),
        "query": str(ref.get("query") or "").strip(),
    }


def _provider_or_error(db: Session, provider_id, kind: str):
    from control_plane.models import SecretProvider
    from control_plane.service import ServiceError

    if not provider_id:
        raise ServiceError("gizli bilgi kaynağı seçilmedi", 400)
    try:
        key = provider_id if isinstance(provider_id, uuid.UUID) else uuid.UUID(str(provider_id))
    except ValueError as exc:
        raise ServiceError("gizli bilgi kaynağı yok", 400) from exc
    provider = db.get(SecretProvider, key)
    if provider is None:
        raise ServiceError("gizli bilgi kaynağı yok", 400)
    if provider.kind != kind:
        raise ServiceError("seçilen kaynak bu parola türü ile uyuşmuyor", 400)
    if not provider.enabled:
        raise ServiceError("gizli bilgi kaynağı kapalı", 400)
    return provider


def datasource_dsn(row: DataSourceRecord, *, require: bool) -> str:
    import os

    from control_plane.service import ServiceError

    if row.host and row.username:
        password = decrypt_secret(row.password_ciphertext) if row.password_ciphertext else ""
        return _build_dsn(row, password)
    env = os.environ.get(row.dsn_env or "", "")
    if env:
        return env
    if require and not row.k8s_secret_name:
        raise ServiceError("bağlantı bilgisi yok", 400)
    return ""


def _build_dsn(row: DataSourceRecord, password: str) -> str:
    user = quote(row.username, safe="")
    secret = quote(password, safe="")
    host = row.host
    if row.dialect == "oracle":
        port = row.port or 1521
        service = row.database_name or "FREEPDB1"
        return f"oracle://{user}:{secret}@{host}:{port}/{service}"
    port = row.port or 5432
    database = row.database_name or "postgres"
    query = dict(row.options or {})
    if row.read_only and "options" not in query:
        query["options"] = "-c default_transaction_read_only=on"
    base = f"postgresql+psycopg://{user}:{secret}@{host}:{port}/{database}"
    if not query:
        return base
    rendered = "&".join(f"{quote(str(key), safe='')}={quote(str(value), safe='')}" for key, value in query.items())
    return base + "?" + rendered


def connection_material(db: Session, row: DataSourceRecord) -> tuple[str, list[str]]:
    """Live DSN plus values that must be stripped from errors."""
    from control_plane.service import ServiceError
    from secret_sources.errors import SecretProviderError
    from secret_sources.resolve import effective_backend, fetch_provider_secret, resolve_kubernetes_value

    backend = effective_backend(row, "password_ciphertext")
    if backend == "db":
        password = decrypt_secret(row.password_ciphertext) if row.password_ciphertext else ""
        return datasource_dsn(row, require=True), [password, row.username or ""]
    try:
        if backend == "kubernetes":
            from shared.config import get_settings

            settings = get_settings()
            value = resolve_kubernetes_value(
                row.k8s_secret_name or "",
                row.k8s_secret_key or "dsn",
                [settings.run_namespace, settings.secret_namespace],
            )
        else:
            value = fetch_provider_secret(db, row.secret_provider_id, row.secret_path or "", row.secret_ref or {})
    except SecretProviderError as exc:
        raise ServiceError(str(exc), 502) from exc
    if row.host and row.username and "://" not in value:
        return _build_dsn(row, value), [value, row.username or ""]
    return value, [value, row.username or ""]


def materialized_source(db: Session, row: DataSourceRecord) -> dict:
    from control_plane.service import ServiceError
    from secret_sources.errors import SecretProviderError
    from secret_sources.resolve import effective_backend, fetch_provider_secret

    backend = effective_backend(row, "password_ciphertext")
    payload = {
        "name": row.name,
        "dialect": row.dialect,
        "dsn_env": row.dsn_env,
        "allow_tables": list(row.allow_tables),
        "sensitivity": row.sensitivity,
    }
    if backend == "kubernetes":
        if not row.k8s_secret_name:
            raise ServiceError(f"{row.name} için Kubernetes Secret adı yok", 400)
        return {
            **payload,
            "dsn": "",
            "k8s_secret_name": row.k8s_secret_name,
            "k8s_secret_key": row.k8s_secret_key or "dsn",
        }
    if backend in {"conjur", "ccp", "vault"}:
        try:
            value = fetch_provider_secret(db, row.secret_provider_id, row.secret_path or "", row.secret_ref or {})
        except SecretProviderError as exc:
            raise ServiceError(str(exc), 502) from exc
        dsn = _build_dsn(row, value) if row.host and row.username else value
        return {**payload, "dsn": dsn, "k8s_secret_name": None, "k8s_secret_key": None}
    dsn = datasource_dsn(row, require=False)
    if not dsn and not row.k8s_secret_name:
        raise ServiceError(f"{row.dsn_env} kontrol düzlemi ortamında yok", 500)
    return {
        **payload,
        "dsn": dsn,
        "k8s_secret_name": row.k8s_secret_name,
        "k8s_secret_key": row.k8s_secret_key,
    }


def test_datasource(db: Session, row: DataSourceRecord) -> dict:
    from control_plane.service import ServiceError

    started = time.monotonic()
    try:
        dsn, redactions = connection_material(db, row)
        if row.dialect == "oracle":
            import oracledb

            from datasources.oracle import _parse_oracle_dsn

            user, secret, connect = _parse_oracle_dsn(dsn)
            conn = oracledb.connect(user=user, password=secret, dsn=connect)
            try:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT 1 FROM dual")
                    cursor.fetchone()
            finally:
                conn.close()
        elif row.dialect in {"postgres", "ansi"}:
            import psycopg

            from datasources.base import normalize_pg_dsn

            with psycopg.connect(normalize_pg_dsn(dsn), connect_timeout=5) as conn:
                conn.execute("SELECT 1")
        else:
            raise ServiceError("bu tür için deneme bağlantısı yok", 400)
    except ServiceError:
        raise
    except Exception as exc:  # noqa: BLE001
        message = redact(str(exc), redactions)
        raise ServiceError(f"bağlantı kurulamadı: {message}", 502) from exc
    return {"ok": True, "latency_ms": int((time.monotonic() - started) * 1000)}


def provider_out(row: LlmProvider) -> dict:
    from secret_sources.resolve import effective_backend

    backend = effective_backend(row, "api_key_ciphertext")
    api_key_set = bool(row.api_key_ciphertext) or backend in {"kubernetes", "conjur", "ccp"}
    if backend == "conjur":
        api_key_set = bool(row.secret_provider_id and (row.secret_path or "").strip())
    elif backend == "ccp":
        ref = row.secret_ref or {}
        api_key_set = bool(row.secret_provider_id and (ref.get("object") or ref.get("query")))
    elif backend == "kubernetes":
        api_key_set = bool(row.k8s_secret_name)
    hint = public_hint(row.api_key_ciphertext, row.api_key_hint)
    if api_key_set and not hint:
        hint = "••••"
    return {
        "id": str(row.id),
        "name": row.name,
        "base_url": row.base_url,
        "model": row.model,
        "api_key_set": api_key_set,
        "api_key_hint": hint,
        "k8s_secret_name": row.k8s_secret_name,
        "k8s_secret_key": row.k8s_secret_key,
        "secret_backend": backend,
        "secret_provider_id": str(row.secret_provider_id) if row.secret_provider_id else None,
        "secret_path": row.secret_path or "",
        "secret_ref": row.secret_ref or {},
        "temperature": row.temperature,
        "reasoning_effort": row.reasoning_effort or "",
        "extra_params": row.extra_params or {},
        "is_default": row.is_default,
        "enabled": row.enabled,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def apply_provider(db: Session, row: LlmProvider, body, *, creating: bool, reset_secret_source: bool = False) -> None:
    if creating:
        row.name = body.name.strip()
    row.base_url = body.base_url.strip().rstrip("/")
    row.model = body.model.strip()
    row.temperature = body.temperature
    row.reasoning_effort = (body.reasoning_effort or "").strip()
    row.extra_params = dict(body.extra_params or {})
    row.enabled = body.enabled
    if reset_secret_source or creating:
        _assign_secret_source(db, row, body, kind="api_key")
    else:
        row.k8s_secret_name = body.k8s_secret_name or None
        row.k8s_secret_key = body.k8s_secret_key or row.k8s_secret_key or "api_key"
        if body.api_key:
            row.api_key_ciphertext = encrypt_secret(body.api_key)
            row.api_key_hint = secret_hint(body.api_key)
    if body.is_default:
        db.query(LlmProvider).filter(LlmProvider.id != row.id).update({LlmProvider.is_default: False})
        row.is_default = True
    elif creating:
        row.is_default = False


def find_provider(db: Session, ref: str | None) -> LlmProvider | None:
    if ref:
        row = db.query(LlmProvider).filter(LlmProvider.name == ref, LlmProvider.enabled.is_(True)).one_or_none()
        if row is not None:
            return row
        try:
            key = uuid.UUID(str(ref))
        except ValueError:
            key = None
        if key is not None:
            found = db.get(LlmProvider, key)
            if found is not None and found.enabled:
                return found
    return (
        db.query(LlmProvider)
        .filter(LlmProvider.enabled.is_(True), LlmProvider.is_default.is_(True))
        .one_or_none()
    )


def resolve_llm(db: Session, settings, model_class: str | None) -> dict:
    """Resolve a model for a run. The API key stays in this dict and must not be logged."""
    fallback = settings.resolve_model(model_class or "local-default")
    base = {
        "base_url": fallback["base_url"],
        "model": fallback["model"],
        "api_key": fallback.get("api_key") or "",
        "k8s_secret_name": settings.llm_k8s_secret_name or "",
        "k8s_secret_key": settings.llm_k8s_secret_key or "api_key",
        "temperature": settings.llm_temperature,
        "reasoning_effort": settings.llm_reasoning_effort or "",
        "name": model_class or "local-default",
    }
    if settings.llm_mode == "fake":
        return base
    provider = find_provider(db, model_class)
    if provider is None:
        return base
    from control_plane.service import ServiceError
    from secret_sources.errors import SecretProviderError
    from secret_sources.resolve import effective_backend, fetch_provider_secret

    backend = effective_backend(provider, "api_key_ciphertext")
    shared = {
        "base_url": provider.base_url,
        "model": provider.model,
        "temperature": settings.llm_temperature if provider.temperature is None else provider.temperature,
        "reasoning_effort": provider.reasoning_effort or "",
        "name": provider.name,
    }
    if backend == "kubernetes":
        return {
            **shared,
            "api_key": "",
            "k8s_secret_name": provider.k8s_secret_name or "",
            "k8s_secret_key": provider.k8s_secret_key or "api_key",
        }
    if backend in {"conjur", "ccp", "vault"}:
        try:
            api_key = fetch_provider_secret(db, provider.secret_provider_id, provider.secret_path or "", provider.secret_ref or {})
        except SecretProviderError as exc:
            raise ServiceError(str(exc), 502) from exc
        return {**shared, "api_key": api_key, "k8s_secret_name": "", "k8s_secret_key": "api_key"}
    api_key = decrypt_secret(provider.api_key_ciphertext) if provider.api_key_ciphertext else ""
    if not api_key and provider.k8s_secret_name:
        return {
            **shared,
            "api_key": "",
            "k8s_secret_name": provider.k8s_secret_name or "",
            "k8s_secret_key": provider.k8s_secret_key or "api_key",
        }
    return {**shared, "api_key": api_key, "k8s_secret_name": "", "k8s_secret_key": "api_key"}


def _live_api_key(db: Session, row: LlmProvider, settings) -> str:
    from control_plane.service import ServiceError
    from secret_sources.errors import SecretProviderError
    from secret_sources.resolve import effective_backend, fetch_provider_secret, resolve_kubernetes_value

    backend = effective_backend(row, "api_key_ciphertext")
    try:
        if backend == "kubernetes":
            return resolve_kubernetes_value(
                row.k8s_secret_name or "",
                row.k8s_secret_key or "api_key",
                [settings.run_namespace, settings.secret_namespace],
            )
        if backend in {"conjur", "ccp", "vault"}:
            return fetch_provider_secret(db, row.secret_provider_id, row.secret_path or "", row.secret_ref or {})
    except SecretProviderError as exc:
        raise ServiceError(str(exc), 502) from exc
    return decrypt_secret(row.api_key_ciphertext) if row.api_key_ciphertext else settings.llm_api_key


def test_provider(db: Session, row: LlmProvider, settings) -> dict:
    from control_plane.service import ServiceError
    from shared.llm import OpenAICompatibleLLM

    api_key = _live_api_key(db, row, settings)
    if not api_key or api_key == "not-set":
        raise ServiceError("API anahtarı yok", 400)
    llm = OpenAICompatibleLLM(
        base_url=row.base_url,
        api_key=api_key,
        model=row.model,
        timeout=min(settings.llm_timeout_seconds, 30),
        temperature=0 if row.temperature is None else row.temperature,
        reasoning_effort=row.reasoning_effort or "",
    )
    try:
        text = llm.complete([{"role": "user", "content": "Reply with the single word OK."}])
    except Exception as exc:  # noqa: BLE001
        raise ServiceError(f"model yanıt vermedi: {redact(str(exc), [api_key])}", 502) from exc
    call = llm.calls[-1] if llm.calls else {}
    return {"ok": True, "latency_ms": call.get("latency_ms"), "sample": (text or "")[:80]}


def seed_llm_from_env(db: Session, settings) -> None:
    if settings.llm_mode == "fake":
        return
    if db.query(LlmProvider).count():
        return
    if not (settings.llm_base_url and settings.llm_model):
        return
    row = LlmProvider(
        name=(settings.llm_model or "default")[:63],
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        is_default=True,
        enabled=True,
        k8s_secret_name=settings.llm_k8s_secret_name or None,
        k8s_secret_key=settings.llm_k8s_secret_key or "api_key",
        reasoning_effort=settings.llm_reasoning_effort or "",
        temperature=settings.llm_temperature,
    )
    key = settings.llm_api_key or ""
    if key and key != "not-set" and not settings.llm_k8s_secret_name:
        row.api_key_ciphertext = encrypt_secret(key)
        row.api_key_hint = secret_hint(key)
    db.add(row)
    db.commit()


def persist_llm_calls(db: Session, run: Run | None, calls: list, purpose: str) -> None:
    for item in calls or []:
        if not isinstance(item, dict):
            continue
        db.add(
            LlmCall(
                run_id=run.id if run is not None else None,
                provider_name=str(item.get("provider") or "")[:63],
                model=str(item.get("model") or "")[:120],
                purpose=purpose[:32],
                latency_ms=int(item.get("latency_ms") or 0),
                prompt_tokens=int(item.get("prompt_tokens") or 0),
                completion_tokens=int(item.get("completion_tokens") or 0),
                total_tokens=int(item.get("total_tokens") or 0),
            )
        )


def spec_diff(db: Session, agent: Agent, left: int, right: int) -> str:
    from control_plane.service import ServiceError

    rows = {
        row.version: row.spec
        for row in db.query(AgentVersion).filter(AgentVersion.agent_id == agent.id, AgentVersion.version.in_([left, right]))
    }
    if left not in rows or right not in rows:
        raise ServiceError("sürüm yok", 404)
    before = json.dumps(rows[left], ensure_ascii=False, indent=2, sort_keys=True).splitlines(keepends=True)
    after = json.dumps(rows[right], ensure_ascii=False, indent=2, sort_keys=True).splitlines(keepends=True)
    return "".join(difflib.unified_diff(before, after, fromfile=f"v{left}", tofile=f"v{right}"))


def duplicate_agent(db: Session, agent: Agent, actor: str) -> Agent:
    from control_plane.service import ServiceError, audit, create_agent

    current = (
        db.query(AgentVersion)
        .filter(AgentVersion.agent_id == agent.id, AgentVersion.version == agent.current_version)
        .one_or_none()
    )
    if current is None:
        current = db.query(AgentVersion).filter(AgentVersion.agent_id == agent.id).order_by(AgentVersion.version.desc()).first()
    if current is None:
        raise ServiceError("kopyalanacak spec yok", 409)
    spec = json.loads(json.dumps(current.spec))
    spec["metadata"]["name"] = f"{agent.name}-kopya"[:55]
    created = create_agent(db, spec, publish=True, actor=actor)
    schedule = db.query(Schedule).filter(Schedule.agent_id == created.id).one_or_none()
    if schedule is not None:
        schedule.paused = True
        schedule.next_run_at = None
        db.commit()
    audit(db, actor, "agent.duplicated", "agent", str(created.id), {"from": str(agent.id)})
    db.commit()
    return created


def delete_agent(db: Session, agent: Agent, actor: str) -> None:
    from control_plane.service import audit

    schedule = db.query(Schedule).filter(Schedule.agent_id == agent.id).one_or_none()
    if schedule is not None:
        schedule.paused = True
        schedule.next_run_at = None
    agent.status = "deleted"
    suffix = agent.id.hex[:6]
    renamed = f"{agent.name[:40]}--silindi-{suffix}"
    agent.name = renamed[:63]
    agent.updated_at = utcnow()
    audit(db, actor, "agent.deleted", "agent", str(agent.id), {"soft": True})
    db.commit()


def cancel_run(db: Session, run: Run, actor: str) -> Run:
    from control_plane.service import ServiceError, audit

    if run.status not in {"pending", "running"}:
        raise ServiceError("yalnızca bekleyen veya çalışan koşum iptal edilir", 409)
    run.status = "cancelled"
    run.finished_at = utcnow()
    run.error = run.error or "kullanıcı iptal etti"
    audit(db, actor, "run.cancelled", "run", str(run.id), {})
    db.commit()
    from control_plane.backends import get_backend

    try:
        get_backend().stop(run)
    except Exception as exc:  # noqa: BLE001
        run.error = f"iptal edildi; kaynak silinemedi: {exc}"
        db.commit()
    return run


def delete_run(db: Session, run: Run, actor: str) -> None:
    from control_plane.service import audit

    if run.status in {"pending", "running"}:
        cancel_run(db, run, actor)
        db.refresh(run)
    from shared.artifacts import build_store
    from shared.config import get_settings

    store = build_store(get_settings())
    for artifact in db.query(Artifact).filter(Artifact.run_id == run.id).all():
        try:
            store.delete(artifact.storage_uri)
        except Exception:
            pass
        db.delete(artifact)
    db.query(LlmCall).filter(LlmCall.run_id == run.id).delete()
    db.query(RunStep).filter(RunStep.run_id == run.id).delete()
    db.query(ToolCall).filter(ToolCall.run_id == run.id).delete()
    audit(db, actor, "run.deleted", "run", str(run.id), {"agent": run.agent_name})
    db.delete(run)
    db.commit()


def bulk_delete_runs(db: Session, *, older_than_days: int, statuses: list[str], actor: str) -> int:
    from control_plane.service import ServiceError

    if older_than_days < 1:
        raise ServiceError("en az 1 gün", 400)
    allowed = {"succeeded", "failed", "needs_review", "cancelled"}
    chosen = [item for item in statuses if item in allowed]
    if not chosen:
        raise ServiceError("silinecek durum seçilmedi", 400)
    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    rows = (
        db.query(Run)
        .filter(Run.created_at < cutoff, Run.status.in_(chosen))
        .all()
    )
    for row in rows:
        delete_run(db, row, actor)
    return len(rows)


def rerun(db: Session, run: Run, actor: str) -> tuple[Run, str]:
    from control_plane.service import ServiceError, trigger_run

    agent = db.get(Agent, run.agent_id)
    if agent is None or agent.status == "deleted":
        raise ServiceError("ajan yok", 404)
    return trigger_run(db, agent, trigger="manual", dry_run=run.dry_run, actor=actor)


def dashboard(db: Session, days: int = 14) -> dict:
    days = max(1, min(days, 90))
    now = datetime.now(timezone.utc)
    today = local_day_start(now, "Europe/Istanbul")
    window = now - timedelta(days=days)
    active_agents = db.query(Agent).filter(Agent.status == "published").count()
    runs_today_rows = db.query(Run).filter(Run.created_at >= today, Run.dry_run.is_(False)).all()
    recent = db.query(Run).filter(Run.created_at >= window, Run.dry_run.is_(False)).all()
    finished = [row for row in recent if row.status in {"succeeded", "failed", "needs_review"}]
    succeeded = [row for row in finished if row.status == "succeeded"]
    success_rate = round(100 * len(succeeded) / len(finished), 1) if finished else None
    durations = []
    for row in succeeded:
        if row.started_at and row.finished_at:
            durations.append((row.finished_at - row.started_at).total_seconds())
    avg_duration = round(sum(durations) / len(durations), 1) if durations else None
    needs_review = db.query(Run).filter(Run.status == "needs_review").count()
    token_rows = db.query(LlmCall).filter(LlmCall.created_at >= today).all()
    tokens_today = sum(row.total_tokens or 0 for row in token_rows)
    by_day: dict[str, dict[str, int]] = {}
    duration_by_day: dict[str, list[float]] = {}
    for row in recent:
        key = row.created_at.astimezone(timezone(timedelta(hours=3))).date().isoformat()
        bucket = by_day.setdefault(key, {"succeeded": 0, "failed": 0, "needs_review": 0, "cancelled": 0, "running": 0})
        status = row.status if row.status in bucket else "running"
        bucket[status] = bucket.get(status, 0) + 1
        if row.started_at and row.finished_at and row.status == "succeeded":
            duration_by_day.setdefault(key, []).append((row.finished_at - row.started_at).total_seconds())
    series = []
    for offset in range(days - 1, -1, -1):
        day = (now.astimezone(timezone(timedelta(hours=3))).date() - timedelta(days=offset)).isoformat()
        counts = by_day.get(day, {})
        samples = duration_by_day.get(day) or []
        series.append(
            {
                "day": day,
                "succeeded": counts.get("succeeded", 0),
                "failed": counts.get("failed", 0),
                "needs_review": counts.get("needs_review", 0),
                "cancelled": counts.get("cancelled", 0),
                "running": counts.get("running", 0),
                "avg_duration": round(sum(samples) / len(samples), 1) if samples else None,
            }
        )
    latest = db.query(Run).order_by(Run.created_at.desc()).limit(8).all()
    alerts = (
        db.query(Run)
        .filter(Run.status.in_(["needs_review", "failed"]))
        .order_by(Run.created_at.desc())
        .limit(6)
        .all()
    )
    return {
        "active_agents": active_agents,
        "runs_today": len(runs_today_rows),
        "success_rate": success_rate,
        "avg_duration_seconds": avg_duration,
        "needs_review": needs_review,
        "tokens_today": tokens_today,
        "series": series,
        "recent_runs": [
            {
                "id": str(row.id),
                "agent_name": row.agent_name,
                "status": row.status,
                "created_at": row.created_at.isoformat(),
            }
            for row in latest
        ],
        "alerts": [
            {
                "id": str(row.id),
                "agent_name": row.agent_name,
                "status": row.status,
                "reason": row.needs_review_reason or row.error or "",
                "created_at": row.created_at.isoformat(),
            }
            for row in alerts
        ],
    }


def public_settings(settings) -> dict:
    return {
        "llm_mode": settings.llm_mode,
        "artifact_store": settings.resolved_artifact_store(),
        "run_backend": settings.run_backend,
        "encryption_configured": bool((settings.config_master_key or "").strip()),
        "egress": {
            "mode": "networkpolicy",
            "note": (
                "PoC: koşum podları yalnızca DNS, kontrol düzlemi, Postgres ve "
                "Helm extraEgress kurallarına çıkar. Ağ politikası DNS adını seçemez. "
                "Kurumsal kurulumda EgressFirewall veya bir çıkış vekili kullanın. "
                "Örnek: deploy/openshift/egressfirewall.example.yaml."
            ),
        },
    }
