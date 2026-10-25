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
from shared.crypto import decrypt_secret, encrypt_secret, redact, secret_hint


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


def datasource_out(row: DataSourceRecord) -> dict:
    import os

    configured = bool(row.password_ciphertext or row.k8s_secret_name or (row.dsn_env and os.environ.get(row.dsn_env)))
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
        "host": row.host or "",
        "port": row.port,
        "database_name": row.database_name or "",
        "username": row.username or "",
        "password_set": bool(row.password_ciphertext),
        "password_hint": row.password_hint or "",
        "options": row.options or {},
        "read_only": bool(row.read_only),
        "configured": configured,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def apply_datasource(row: DataSourceRecord, body, *, creating: bool) -> None:
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
    row.k8s_secret_name = body.k8s_secret_name or None
    row.k8s_secret_key = body.k8s_secret_key or None
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
    if body.password:
        row.password_ciphertext = encrypt_secret(body.password)
        row.password_hint = secret_hint(body.password)


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


def test_datasource(row: DataSourceRecord) -> dict:
    from control_plane.service import ServiceError

    started = time.monotonic()
    password = decrypt_secret(row.password_ciphertext) if row.password_ciphertext else ""
    try:
        dsn = datasource_dsn(row, require=True)
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
        message = redact(str(exc), [password, row.username or ""])
        raise ServiceError(f"bağlantı kurulamadı: {message}", 502) from exc
    return {"ok": True, "latency_ms": int((time.monotonic() - started) * 1000)}


def provider_out(row: LlmProvider) -> dict:
    return {
        "id": str(row.id),
        "name": row.name,
        "base_url": row.base_url,
        "model": row.model,
        "api_key_set": bool(row.api_key_ciphertext or row.k8s_secret_name),
        "api_key_hint": row.api_key_hint or "",
        "k8s_secret_name": row.k8s_secret_name,
        "k8s_secret_key": row.k8s_secret_key,
        "temperature": row.temperature,
        "reasoning_effort": row.reasoning_effort or "",
        "extra_params": row.extra_params or {},
        "is_default": row.is_default,
        "enabled": row.enabled,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def apply_provider(db: Session, row: LlmProvider, body, *, creating: bool) -> None:
    if creating:
        row.name = body.name.strip()
    row.base_url = body.base_url.strip().rstrip("/")
    row.model = body.model.strip()
    row.k8s_secret_name = body.k8s_secret_name or None
    row.k8s_secret_key = body.k8s_secret_key or "api_key"
    row.temperature = body.temperature
    row.reasoning_effort = (body.reasoning_effort or "").strip()
    row.extra_params = dict(body.extra_params or {})
    row.enabled = body.enabled
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
    api_key = decrypt_secret(provider.api_key_ciphertext) if provider.api_key_ciphertext else ""
    if not api_key and provider.k8s_secret_name:
        api_key = settings.llm_api_key
    return {
        "base_url": provider.base_url,
        "model": provider.model,
        "api_key": api_key,
        "k8s_secret_name": provider.k8s_secret_name or "",
        "k8s_secret_key": provider.k8s_secret_key or "api_key",
        "temperature": settings.llm_temperature if provider.temperature is None else provider.temperature,
        "reasoning_effort": provider.reasoning_effort or "",
        "name": provider.name,
    }


def test_provider(row: LlmProvider, settings) -> dict:
    from control_plane.service import ServiceError
    from shared.llm import OpenAICompatibleLLM

    api_key = decrypt_secret(row.api_key_ciphertext) if row.api_key_ciphertext else settings.llm_api_key
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
