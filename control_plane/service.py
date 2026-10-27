from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from control_plane.models import (
    Agent,
    AgentVersion,
    Artifact,
    AuditEvent,
    DataSourceRecord,
    Run,
    RunStep,
    Schedule,
    utcnow,
)
from control_plane.policy import (
    advance_past_today,
    compute_next_cron,
    evaluate_self_schedule,
    local_day_start,
)
from shared.artifacts import build_store, safe_artifact_name, sha256_bytes
from shared.spec import AgentSpec, parse_duration


log = logging.getLogger("control-plane")


class ServiceError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def audit(db: Session, actor: str, action: str, entity_type: str, entity_id: str, detail: dict | None = None) -> None:
    db.add(
        AuditEvent(
            ts=utcnow(),
            actor=actor,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            detail=detail or {},
        )
    )


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def canonical_spec(payload: dict) -> dict:
    from pydantic import ValidationError

    try:
        model = AgentSpec.model_validate(payload)
    except ValidationError as exc:
        delivery = [err for err in exc.errors() if "delivery" in err.get("loc", ())]
        if not delivery:
            raise
        message = str(delivery[0].get("msg") or "teslimat hedefi geçersiz")
        prefix = "Value error, "
        if message.startswith(prefix):
            message = message[len(prefix):]
        raise ServiceError(message[:500], 400) from exc
    return model.canonical()


def create_agent(db: Session, spec: dict, *, publish: bool, actor: str) -> Agent:
    data = canonical_spec(spec)
    _assert_sources(db, data)
    _assert_delivery(db, data)
    name = data["metadata"]["name"]
    if db.query(Agent).filter(Agent.name == name).first():
        name = _unique_name(db, name)
        data["metadata"]["name"] = name
    agent = Agent(
        name=name,
        description=data["spec"]["goal"][:500],
        owner=data["metadata"]["owner"],
        status="published" if publish else "draft",
        current_version=1 if publish else None,
    )
    db.add(agent)
    db.flush()
    db.add(AgentVersion(agent_id=agent.id, version=1, spec=data, status="published" if publish else "draft"))
    if publish:
        _upsert_schedule(db, agent, data)
    audit(db, actor, "agent.created", "agent", str(agent.id), {"name": name, "publish": publish})
    db.commit()
    db.refresh(agent)
    return agent


def add_version(db: Session, agent: Agent, spec: dict, *, publish: bool, actor: str) -> AgentVersion:
    data = canonical_spec(spec)
    _assert_sources(db, data)
    _assert_delivery(db, data)
    data["metadata"]["name"] = agent.name
    current = db.query(AgentVersion).filter(AgentVersion.agent_id == agent.id).count()
    version_no = current + 1
    data["metadata"]["version"] = version_no
    row = AgentVersion(
        agent_id=agent.id,
        version=version_no,
        spec=data,
        status="published" if publish else "draft",
    )
    db.add(row)
    agent.updated_at = utcnow()
    if publish:
        agent.status = "published"
        agent.current_version = version_no
        agent.description = data["spec"]["goal"][:500]
        _upsert_schedule(db, agent, data)
        audit(db, actor, "agent.published", "agent", str(agent.id), {"version": version_no})
    db.commit()
    db.refresh(row)
    return row


def _assert_delivery(db: Session, spec: dict) -> None:
    from control_plane.delivery_catalog import assert_spec_delivery

    assert_spec_delivery(db, spec)


def _assert_sources(db: Session, spec: dict) -> None:
    refs = spec["spec"]["datasources"]
    sensitivities = []
    from control_plane.catalog import find_datasource

    for ref in refs:
        row = find_datasource(db, ref["ref"])
        if row is None or not row.enabled:
            raise ServiceError(f"veri kaynağı yok: {ref['ref']}", 400)
        allowed = {str(table).lower() for table in row.allow_tables}
        unknown = [table for table in ref["allowTables"] if str(table).lower() not in allowed]
        if unknown:
            raise ServiceError(f"{ref['ref']} için tablo izinli değil: {', '.join(unknown)}", 400)
        sensitivities.append(row.sensitivity)
    model_class = spec["spec"]["model"]["class"]
    if any(item == "restricted" for item in sensitivities) and str(model_class).startswith("cloud"):
        raise ServiceError("kısıtlı veri kaynağı yalnızca local model sınıfıyla kullanılır", 400)


def _unique_name(db: Session, name: str) -> str:
    stem = name[:50]
    for index in range(2, 50):
        candidate = f"{stem}-{index}"[:63].strip("-")
        if not db.query(Agent).filter(Agent.name == candidate).first():
            return candidate
    raise ServiceError("ajan adı üretilemedi", 409)


def _upsert_schedule(db: Session, agent: Agent, spec: dict) -> Schedule:
    body = spec["spec"]["schedule"]
    row = db.query(Schedule).filter(Schedule.agent_id == agent.id).one_or_none()
    if row is None:
        row = Schedule(agent_id=agent.id)
        db.add(row)
    row.mode = body["mode"]
    row.cron = body.get("cron")
    row.timezone = body.get("timeZone") or "Europe/Istanbul"
    self_sched = body.get("selfScheduling") or {}
    row.min_interval_seconds = parse_duration(self_sched.get("minInterval", "1h")) if body["mode"] != "manual" else 3600
    row.max_interval_seconds = parse_duration(self_sched.get("maxInterval", "7d")) if body["mode"] != "manual" else 7 * 86400
    row.max_runs_per_day = int(self_sched.get("maxRunsPerDay", 4))
    row.window = self_sched.get("window", "always")
    row.paused = False
    now = datetime.now(timezone.utc)
    if row.mode in {"cron", "hybrid"} and row.cron:
        row.next_run_at = compute_next_cron(row.cron, row.timezone, now)
    else:
        row.next_run_at = None
    return row


def published_spec(db: Session, agent: Agent) -> tuple[int, dict]:
    if agent.current_version is None:
        raise ServiceError("ajan henüz yayınlanmadı", 409)
    row = (
        db.query(AgentVersion)
        .filter(AgentVersion.agent_id == agent.id, AgentVersion.version == agent.current_version)
        .one()
    )
    return row.version, row.spec


def trigger_run(db: Session, agent: Agent, *, trigger: str, dry_run: bool, actor: str) -> tuple[Run, str]:
    if agent.status == "deleted":
        raise ServiceError("silinmiş ajan çalıştırılamaz", 409)
    if dry_run:
        version_row = (
            db.query(AgentVersion).filter(AgentVersion.agent_id == agent.id).order_by(AgentVersion.version.desc()).first()
        )
        if version_row is None:
            raise ServiceError("yayınlanacak spec yok", 409)
        version, spec = version_row.version, version_row.spec
    else:
        version, spec = published_spec(db, agent)
    schedule = db.query(Schedule).filter(Schedule.agent_id == agent.id).one_or_none()
    if not dry_run and schedule is not None:
        running = (
            db.query(Run)
            .filter(Run.agent_id == agent.id, Run.status.in_(["pending", "running"]))
            .count()
        )
        if running and schedule.concurrency == "forbid":
            raise ServiceError("bu ajanın çalışan bir koşumu var", 409)
        runs_today = _runs_today(db, agent.id, schedule.timezone)
        if runs_today >= schedule.max_runs_per_day:
            raise ServiceError("günlük koşum limiti doldu", 429)
    token = secrets.token_urlsafe(32)
    run = Run(
        agent_id=agent.id,
        agent_name=agent.name,
        spec_version=version,
        spec_snapshot=spec,
        trigger="dry_run" if dry_run else trigger,
        status="pending",
        dry_run=dry_run,
        run_token_hash=hash_token(token),
    )
    db.add(run)
    audit(db, actor, "run.requested", "run", str(run.id), {"trigger": run.trigger, "version": version})
    db.commit()
    db.refresh(run)
    from control_plane.backends import get_backend

    try:
        get_backend().submit(run.id, token)
    except Exception as exc:
        db.refresh(run)
        run.status = "failed"
        run.error = str(exc)
        run.finished_at = utcnow()
        db.commit()
        raise ServiceError(f"koşum başlatılamadı: {exc}", 502) from exc
    db.refresh(run)
    return run, token


def claim_due(db: Session) -> list[tuple[uuid.UUID, str]]:
    now = datetime.now(timezone.utc)
    locked = db.execute(text("SELECT pg_try_advisory_xact_lock(8242001)")).scalar()
    if not locked:
        return []
    rows = db.execute(
        text(
            """
            SELECT id FROM schedules
            WHERE paused = false
              AND next_run_at IS NOT NULL
              AND next_run_at <= :now
            ORDER BY next_run_at
            FOR UPDATE SKIP LOCKED
            LIMIT 5
            """
        ),
        {"now": now},
    ).fetchall()
    created: list[tuple[uuid.UUID, str]] = []
    for (schedule_id,) in rows:
        schedule = db.get(Schedule, schedule_id)
        if schedule is None:
            continue
        agent = db.get(Agent, schedule.agent_id)
        if agent is None or agent.status != "published":
            schedule.next_run_at = _skip_forward(schedule, now)
            continue
        running = db.query(Run).filter(Run.agent_id == agent.id, Run.status.in_(["pending", "running"])).count()
        if running and schedule.concurrency == "forbid":
            schedule.next_run_at = now + __import__("datetime").timedelta(seconds=60)
            audit(db, "scheduler", "schedule.deferred", "schedule", str(schedule.id), {"reason": "concurrency"})
            continue
        if _runs_today(db, agent.id, schedule.timezone) >= schedule.max_runs_per_day:
            schedule.next_run_at = (
                advance_past_today(schedule.cron, schedule.timezone, now) if schedule.cron else _skip_forward(schedule, now)
            )
            audit(db, "scheduler", "schedule.deferred", "schedule", str(schedule.id), {"reason": "daily_limit"})
            continue
        try:
            version, spec = published_spec(db, agent)
        except ServiceError:
            schedule.next_run_at = _skip_forward(schedule, now)
            continue
        token = secrets.token_urlsafe(32)
        idem = f"{schedule.id}:{schedule.next_run_at.isoformat()}"
        run = Run(
            agent_id=agent.id,
            agent_name=agent.name,
            spec_version=version,
            spec_snapshot=spec,
            trigger="cron" if schedule.mode in {"cron", "hybrid"} else "self",
            status="pending",
            dry_run=False,
            idempotency_key=idem,
            run_token_hash=hash_token(token),
        )
        db.add(run)
        try:
            with db.begin_nested():
                db.flush()
        except IntegrityError:
            db.expunge(run)
            continue
        schedule.last_fired_at = now
        if schedule.mode in {"cron", "hybrid"} and schedule.cron:
            schedule.next_run_at = compute_next_cron(schedule.cron, schedule.timezone, now)
        else:
            schedule.next_run_at = None
        audit(db, "scheduler", "run.requested", "run", str(run.id), {"trigger": run.trigger})
        created.append((run.id, token))
    return created


def _skip_forward(schedule: Schedule, now: datetime):
    if schedule.cron:
        return compute_next_cron(schedule.cron, schedule.timezone, now)
    return now + timedelta(hours=1)


def _runs_today(db: Session, agent_id: uuid.UUID, tz_name: str) -> int:
    start = local_day_start(datetime.now(timezone.utc), tz_name)
    return (
        db.query(Run)
        .filter(
            Run.agent_id == agent_id,
            Run.dry_run.is_(False),
            Run.created_at >= start,
            Run.status != "cancelled",
            # Job creation can fail before the pod starts (HTTP 502). Those rows
            # never ran, so they must not fill max_runs_per_day.
            ~((Run.status == "failed") & (Run.started_at.is_(None))),
        )
        .count()
    )


def apply_self_schedule(db: Session, run: Run, requested: datetime, reason: str) -> dict:
    schedule = db.query(Schedule).filter(Schedule.agent_id == run.agent_id).one_or_none()
    if schedule is None or schedule.mode not in {"self", "hybrid"}:
        raise ServiceError("bu ajan kendi zamanını kuramaz", 409)
    if run.dry_run:
        raise ServiceError("deneme koşusu zamanlama kuramaz", 409)
    last = (
        db.query(Run)
        .filter(Run.agent_id == run.agent_id, Run.dry_run.is_(False))
        .order_by(Run.created_at.desc())
        .first()
    )
    decision = evaluate_self_schedule(
        now=datetime.now(timezone.utc),
        requested=requested,
        min_interval_seconds=schedule.min_interval_seconds,
        max_interval_seconds=schedule.max_interval_seconds,
        window=schedule.window,
        tz_name=schedule.timezone,
        last_run_at=last.created_at if last else None,
        runs_today=_runs_today(db, run.agent_id, schedule.timezone),
        max_runs_per_day=schedule.max_runs_per_day,
    )
    detail = {
        "requested": requested.isoformat(),
        "reason": reason,
        "accepted": decision.accepted,
        "adjustments": decision.adjustments,
        "rejection": decision.rejection,
        "at": decision.at.isoformat() if decision.at else None,
    }
    if not decision.accepted or decision.at is None:
        audit(db, f"run:{run.id}", "schedule.rejected", "schedule", str(schedule.id), detail)
        db.commit()
        raise ServiceError(decision.rejection or "zamanlama reddedildi", 409)
    schedule.next_run_at = decision.at
    audit(db, f"run:{run.id}", "schedule.self_adjusted", "schedule", str(schedule.id), detail)
    db.commit()
    return detail


def complete_run(db: Session, run: Run, payload: dict) -> Run:
    if run.status not in {"pending", "running"}:
        return run
    status = payload["status"]
    if status not in {"succeeded", "failed", "needs_review"}:
        raise ServiceError("geçersiz koşum durumu", 400)
    run.status = status
    run.summary = payload.get("summary")
    run.report_markdown = payload.get("report_markdown")
    run.error = payload.get("error")
    run.needs_review_reason = payload.get("needs_review_reason")
    run.finished_at = utcnow()
    action = "run.needs_review" if status == "needs_review" else "run.completed"
    from control_plane.catalog import persist_llm_calls

    persist_llm_calls(db, run, (run.summary or {}).get("llm_calls"), "plan")
    audit(db, f"run:{run.id}", action, "run", str(run.id), {"status": status})
    if status == "needs_review":
        audit(
            db,
            f"run:{run.id}",
            "notification.suppressed",
            "run",
            str(run.id),
            {"reason": run.needs_review_reason},
        )
    db.commit()
    try:
        from delivery.send import deliver_run

        deliver_run(db, run)
    except Exception:
        logging.getLogger("control-plane").warning("delivery hook failed for run %s", run.id)
        db.rollback()
    return run


def add_step(db: Session, run: Run, item: dict) -> RunStep:
    ordinal = db.query(RunStep).filter(RunStep.run_id == run.id).count() + 1
    step = RunStep(
        run_id=run.id,
        ordinal=ordinal,
        name=item["name"][:64],
        status=item.get("status") or "succeeded",
        detail=item.get("detail") or {},
    )
    db.add(step)
    if run.status == "pending":
        run.status = "running"
        run.started_at = run.started_at or utcnow()
    db.commit()
    return step


def artifact_key(run: Run, name: str) -> str:
    safe = safe_artifact_name(name)
    return f"runs/{run.agent_name}/{run.id}/{safe}"


def add_artifact(db: Session, run: Run, *, name: str, media_type: str, data: bytes, claimed_sha: str) -> Artifact:
    settings = get_settings_safe()
    if len(data) > settings.artifact_max_bytes:
        raise ServiceError(f"artefakt {settings.artifact_max_bytes} bayt sınırını aşıyor", 413)
    safe = safe_artifact_name(name)
    digest = sha256_bytes(data)
    if claimed_sha and claimed_sha != digest:
        raise ServiceError("artefakt özeti uyuşmuyor", 400)
    store = build_store(settings)
    uri = store.put_bytes(artifact_key(run, safe), data, media_type)
    try:
        return _insert_artifact(db, run, name=safe, media_type=media_type, uri=uri, digest=digest, size=len(data))
    except Exception:
        store.delete(uri)
        raise


def record_uploaded_artifact(
    db: Session,
    run: Run,
    *,
    name: str,
    media_type: str,
    uri: str,
    digest: str,
    size: int,
    claimed_sha: str,
) -> Artifact:
    safe = safe_artifact_name(name)
    store = build_store(get_settings_safe())
    if claimed_sha and claimed_sha != digest:
        store.delete(uri)
        raise ServiceError("artefakt özeti uyuşmuyor", 400)
    try:
        return _insert_artifact(db, run, name=safe, media_type=media_type, uri=uri, digest=digest, size=size)
    except Exception:
        store.delete(uri)
        raise


def _insert_artifact(db: Session, run: Run, *, name: str, media_type: str, uri: str, digest: str, size: int) -> Artifact:
    row = Artifact(
        run_id=run.id,
        name=name,
        media_type=media_type[:120],
        storage_uri=uri,
        sha256=digest,
        size_bytes=size,
    )
    db.add(row)
    db.commit()
    return row


def purge_expired_artifacts(db: Session, *, now: datetime | None = None, retention_days: int | None = None) -> int:
    settings = get_settings_safe()
    store = build_store(settings)
    days = settings.artifact_retention_days if retention_days is None else retention_days
    removed = 0
    if days > 0:
        moment = now or utcnow()
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        cutoff = moment - timedelta(days=days)
        rows = (
            db.query(Artifact)
            .join(Run, Artifact.run_id == Run.id)
            .filter(Artifact.created_at < cutoff)
            .filter(Run.status.notin_(["pending", "running"]))
            .all()
        )
        for row in rows:
            try:
                store.delete(row.storage_uri)
            except FileNotFoundError:
                pass
            except Exception:
                log.warning("artefakt dosyası silinemedi: %s", row.storage_uri)
                continue
            audit(
                db,
                "system",
                "artifact.purged",
                "artifact",
                str(row.id),
                {"name": row.name, "run_id": str(row.run_id), "size_bytes": row.size_bytes},
            )
            db.delete(row)
            removed += 1
        if removed:
            db.commit()
    store.sweep_partials(86400)
    return removed


def get_settings_safe():
    from shared.config import get_settings

    return get_settings()


def load_sources_for_spec(db: Session, spec: dict) -> list[DataSourceRecord]:
    from control_plane.catalog import find_datasource

    ordered = []
    for item in spec["spec"]["datasources"]:
        row = find_datasource(db, item["ref"])
        if row is None:
            raise ServiceError(f"veri kaynağı yok: {item['ref']}", 400)
        ordered.append(row)
    return ordered


def materialize_sources(db: Session, rows: list[DataSourceRecord]) -> list[dict]:
    from control_plane.catalog import materialized_source

    return [materialized_source(db, row) for row in rows]
