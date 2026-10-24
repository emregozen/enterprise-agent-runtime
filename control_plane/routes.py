from __future__ import annotations

import base64
import os
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from control_plane.db import get_db
from control_plane.models import Agent, AgentVersion, Artifact, AuditEvent, DataSourceRecord, Run, RunStep, Schedule, ToolCall
from control_plane.serialize import agent_out, run_out, schedule_out, spec_summary
from control_plane.service import (
    ServiceError,
    add_artifact,
    add_step,
    add_version,
    apply_self_schedule,
    complete_run,
    create_agent,
    hash_token,
    load_sources_for_spec,
    trigger_run,
)
from control_plane.tool_proxy import ToolError, invoke_tool
from datasources import open_source
from harness.loop import builder_messages
from shared.artifacts import build_store
from shared.config import get_settings
from shared.llm import make_llm, parse_json_response
from shared.spec import AgentSpec

public = APIRouter(prefix="/api")
internal = APIRouter(prefix="/api/internal")


class DatasourceIn(BaseModel):
    name: str
    dialect: str
    description: str = ""
    dsn_env: str
    allow_tables: list[str] = Field(min_length=1)
    sensitivity: str = "internal"
    k8s_secret_name: str | None = None
    k8s_secret_key: str | None = None


class DraftIn(BaseModel):
    description: str = Field(min_length=8)
    owner: str = "ekip"
    datasource_refs: list[str] = Field(min_length=1)


class AgentIn(BaseModel):
    spec: dict
    publish: bool = True


class RunIn(BaseModel):
    dry_run: bool = False


class PauseIn(BaseModel):
    paused: bool


class StepIn(BaseModel):
    name: str
    status: str = "succeeded"
    detail: dict = Field(default_factory=dict)


class ArtifactIn(BaseModel):
    name: str
    media_type: str = "application/octet-stream"
    sha256: str = ""
    b64: str


class CompleteIn(BaseModel):
    status: str
    summary: dict | None = None
    report_markdown: str | None = None
    error: str | None = None
    needs_review_reason: str | None = None


class ScheduleIn(BaseModel):
    at: str
    reason: str = ""


class ToolIn(BaseModel):
    arguments: dict = Field(default_factory=dict)


def _agent_or_404(db: Session, agent_id: uuid.UUID) -> Agent:
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(404, "ajan yok")
    return agent


def _run_or_404(db: Session, run_id: uuid.UUID) -> Run:
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "koşum yok")
    return run


def _auth_run(db: Session, run_id: uuid.UUID, authorization: str | None) -> Run:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "run token gerekli")
    token = authorization.split(" ", 1)[1].strip()
    run = _run_or_404(db, run_id)
    import secrets as pysecrets

    if not pysecrets.compare_digest(hash_token(token), run.run_token_hash):
        raise HTTPException(403, "run token geçersiz")
    return run


@public.get("/health")
def health(db: Session = Depends(get_db)):
    from sqlalchemy import text

    db.execute(text("SELECT 1"))
    settings = get_settings()
    return {"ok": True, "llm_mode": settings.llm_mode, "run_backend": settings.run_backend}


@public.get("/datasources")
def list_datasources(db: Session = Depends(get_db)):
    rows = db.query(DataSourceRecord).order_by(DataSourceRecord.name).all()
    return [_ds_out(row) for row in rows]


@public.post("/datasources", status_code=201)
def create_datasource(body: DatasourceIn, db: Session = Depends(get_db)):
    if body.sensitivity not in {"internal", "restricted"}:
        raise HTTPException(400, "sensitivity internal veya restricted olmalı")
    if body.dialect not in {"postgres", "postgresql", "oracle", "ansi"}:
        raise HTTPException(400, "dialect postgres, oracle veya ansi olmalı")
    if db.query(DataSourceRecord).filter(DataSourceRecord.name == body.name).first():
        raise HTTPException(409, "bu ada sahip bir veri kaynağı var")
    row = DataSourceRecord(
        name=body.name,
        dialect="postgres" if body.dialect == "postgresql" else body.dialect,
        description=body.description,
        dsn_env=body.dsn_env,
        allow_tables=body.allow_tables,
        sensitivity=body.sensitivity,
        k8s_secret_name=body.k8s_secret_name,
        k8s_secret_key=body.k8s_secret_key,
    )
    db.add(row)
    db.commit()
    return _ds_out(row)


@public.post("/datasources/{name}/introspect")
def introspect(name: str, db: Session = Depends(get_db)):
    row = db.query(DataSourceRecord).filter(DataSourceRecord.name == name).one_or_none()
    if row is None:
        raise HTTPException(404, "veri kaynağı yok")
    return {"catalog": _live_catalog(row)}


@public.post("/builder/draft")
def draft(body: DraftIn, db: Session = Depends(get_db)):
    settings = get_settings()
    sources = []
    for name in body.datasource_refs:
        row = db.query(DataSourceRecord).filter(DataSourceRecord.name == name, DataSourceRecord.enabled.is_(True)).one_or_none()
        if row is None:
            raise HTTPException(404, f"veri kaynağı yok: {name}")
        sources.append(
            {
                "name": row.name,
                "dialect": row.dialect,
                "allow_tables": row.allow_tables,
                "sensitivity": row.sensitivity,
                "catalog": _live_catalog(row),
            }
        )
    llm = make_llm(settings, "local-default")
    try:
        raw = parse_json_response(llm.complete(builder_messages({
            "description": body.description,
            "owner": body.owner,
            "datasources": sources,
        })))
        spec = AgentSpec.model_validate(raw).canonical()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, f"taslak üretilemedi: {exc}") from exc
    return {"spec": spec, "summary": spec_summary(spec)}


@public.get("/agents")
def list_agents(db: Session = Depends(get_db)):
    rows = db.query(Agent).order_by(Agent.created_at.desc()).all()
    payload = []
    for agent in rows:
        schedule = db.query(Schedule).filter(Schedule.agent_id == agent.id).one_or_none()
        payload.append(agent_out(agent, schedule))
    return payload


@public.post("/agents", status_code=201)
def post_agent(body: AgentIn, db: Session = Depends(get_db)):
    try:
        agent = create_agent(db, body.spec, publish=body.publish, actor="ui")
    except ServiceError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    schedule = db.query(Schedule).filter(Schedule.agent_id == agent.id).one_or_none()
    return agent_out(agent, schedule, goal=body.spec.get("spec", {}).get("goal"))


@public.get("/agents/{agent_id}")
def get_agent(agent_id: uuid.UUID, db: Session = Depends(get_db)):
    agent = _agent_or_404(db, agent_id)
    schedule = db.query(Schedule).filter(Schedule.agent_id == agent.id).one_or_none()
    versions = (
        db.query(AgentVersion).filter(AgentVersion.agent_id == agent.id).order_by(AgentVersion.version.desc()).all()
    )
    current = next((row.spec for row in versions if row.version == agent.current_version), None)
    return {
        **agent_out(agent, schedule, goal=(current or {}).get("spec", {}).get("goal", agent.description)),
        "spec": current,
        "versions": [
            {"version": row.version, "status": row.status, "created_at": row.created_at.isoformat(), "spec": row.spec}
            for row in versions
        ],
    }


@public.post("/agents/{agent_id}/versions", status_code=201)
def post_version(agent_id: uuid.UUID, body: AgentIn, db: Session = Depends(get_db)):
    agent = _agent_or_404(db, agent_id)
    try:
        row = add_version(db, agent, body.spec, publish=body.publish, actor="ui")
    except ServiceError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    return {"version": row.version, "status": row.status, "spec": row.spec}


@public.post("/agents/{agent_id}/pause")
def pause(agent_id: uuid.UUID, body: PauseIn, db: Session = Depends(get_db)):
    agent = _agent_or_404(db, agent_id)
    schedule = db.query(Schedule).filter(Schedule.agent_id == agent.id).one_or_none()
    if schedule is None:
        raise HTTPException(409, "yayınlanmış zamanlama yok")
    schedule.paused = body.paused
    db.commit()
    return schedule_out(schedule)


@public.post("/agents/{agent_id}/runs", status_code=202)
def post_run(agent_id: uuid.UUID, body: RunIn, db: Session = Depends(get_db)):
    agent = _agent_or_404(db, agent_id)
    try:
        run, _token = trigger_run(db, agent, trigger="manual", dry_run=body.dry_run, actor="ui")
    except ServiceError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    return run_out(run)


@public.get("/runs")
def list_runs(agent_id: uuid.UUID | None = None, status: str | None = None, limit: int = 50, db: Session = Depends(get_db)):
    query = db.query(Run).order_by(Run.created_at.desc())
    if agent_id:
        query = query.filter(Run.agent_id == agent_id)
    if status:
        query = query.filter(Run.status == status)
    return [run_out(row) for row in query.limit(min(limit, 200)).all()]


@public.get("/runs/{run_id}")
def get_run(run_id: uuid.UUID, db: Session = Depends(get_db)):
    run = _run_or_404(db, run_id)
    steps = db.query(RunStep).filter(RunStep.run_id == run.id).order_by(RunStep.ordinal).all()
    tools = db.query(ToolCall).filter(ToolCall.run_id == run.id).order_by(ToolCall.created_at).all()
    artifacts = db.query(Artifact).filter(Artifact.run_id == run.id).order_by(Artifact.created_at).all()
    audits = (
        db.query(AuditEvent)
        .filter(AuditEvent.entity_id == str(run.id))
        .order_by(AuditEvent.ts)
        .all()
    )
    return {
        **run_out(run),
        "report_markdown": run.report_markdown,
        "spec": run.spec_snapshot,
        "steps": [
            {"ordinal": step.ordinal, "name": step.name, "status": step.status, "detail": step.detail, "created_at": step.created_at.isoformat()}
            for step in steps
        ],
        "tool_calls": [
            {"tool": call.tool_name, "status": call.status, "request": call.request, "response": call.response, "created_at": call.created_at.isoformat()}
            for call in tools
        ],
        "artifacts": [
            {
                "id": str(item.id),
                "name": item.name,
                "media_type": item.media_type,
                "sha256": item.sha256,
                "size_bytes": item.size_bytes,
            }
            for item in artifacts
        ],
        "audit": [
            {"ts": event.ts.isoformat(), "actor": event.actor, "action": event.action, "detail": event.detail}
            for event in audits
        ],
    }


@public.get("/runs/{run_id}/logs")
def run_logs(run_id: uuid.UUID, db: Session = Depends(get_db)):
    run = _run_or_404(db, run_id)
    from control_plane.backends import get_backend

    return {"text": get_backend().read_logs(run)}


@public.get("/runs/{run_id}/artifacts/{artifact_id}")
def download_artifact(run_id: uuid.UUID, artifact_id: uuid.UUID, db: Session = Depends(get_db)):
    artifact = db.get(Artifact, artifact_id)
    if artifact is None or artifact.run_id != run_id:
        raise HTTPException(404, "artefakt yok")
    data = build_store(get_settings()).get_bytes(artifact.storage_uri)
    return Response(
        content=data,
        media_type=artifact.media_type,
        headers={"Content-Disposition": f'attachment; filename="{artifact.name}"'},
    )


@internal.get("/runs/{run_id}/context")
def run_context(run_id: uuid.UUID, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    run = _auth_run(db, run_id, authorization)
    if run.status == "pending":
        run.status = "running"
        db.commit()
    rows = load_sources_for_spec(db, run.spec_snapshot)
    previous = (
        db.query(Run)
        .filter(Run.agent_id == run.agent_id, Run.id != run.id, Run.status.in_(["succeeded", "needs_review"]))
        .order_by(Run.created_at.desc())
        .first()
    )
    previous_summary = None
    if previous and previous.summary:
        previous_summary = {"status": previous.status, "summary": previous.summary, "finished_at": previous.finished_at.isoformat() if previous.finished_at else None}
    return {
        "run_id": str(run.id),
        "trigger": run.trigger,
        "dry_run": run.dry_run,
        "spec": run.spec_snapshot,
        "datasources": [
            {
                "name": row.name,
                "dialect": row.dialect,
                "dsn_env": row.dsn_env,
                "allow_tables": row.allow_tables,
                "sensitivity": row.sensitivity,
            }
            for row in rows
        ],
        "recipient_allowlist": get_settings().recipient_allowlist(),
        "previous_summary": previous_summary,
    }


@internal.post("/runs/{run_id}/steps", status_code=201)
def post_step(run_id: uuid.UUID, body: StepIn, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    run = _auth_run(db, run_id, authorization)
    step = add_step(db, run, body.model_dump())
    return {"ordinal": step.ordinal}


@internal.post("/runs/{run_id}/artifacts", status_code=201)
def post_artifact(run_id: uuid.UUID, body: ArtifactIn, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    run = _auth_run(db, run_id, authorization)
    try:
        data = base64.b64decode(body.b64, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, "artefakt base64 değil") from exc
    if len(data) > 20_000_000:
        raise HTTPException(413, "artefakt 20 MB sınırını aşıyor")
    try:
        row = add_artifact(db, run, name=body.name, media_type=body.media_type, data=data, claimed_sha=body.sha256)
    except ServiceError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    return {"id": str(row.id), "sha256": row.sha256}


@internal.post("/runs/{run_id}/tools/{tool_name}")
def post_tool(run_id: uuid.UUID, tool_name: str, body: ToolIn, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    run = _auth_run(db, run_id, authorization)
    try:
        return invoke_tool(db, run, tool_name, body.arguments)
    except ToolError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@internal.post("/runs/{run_id}/schedule-next")
def post_schedule(run_id: uuid.UUID, body: ScheduleIn, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    from datetime import datetime

    run = _auth_run(db, run_id, authorization)
    try:
        requested = datetime.fromisoformat(body.at)
    except ValueError as exc:
        raise HTTPException(400, "at ISO zaman olmalı") from exc
    if requested.tzinfo is None:
        raise HTTPException(400, "at zaman dilimi içermeli")
    try:
        return apply_self_schedule(db, run, requested, body.reason)
    except ServiceError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@internal.post("/runs/{run_id}/complete")
def post_complete(run_id: uuid.UUID, body: CompleteIn, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    run = _auth_run(db, run_id, authorization)
    try:
        complete_run(db, run, body.model_dump())
    except ServiceError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    return run_out(run)


def _ds_out(row: DataSourceRecord) -> dict:
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
        "configured": bool(os.environ.get(row.dsn_env)) or bool(row.k8s_secret_name),
    }


def _live_catalog(row: DataSourceRecord) -> dict:
    settings = get_settings()
    dsn = os.environ.get(row.dsn_env, "")
    if not dsn:
        raise HTTPException(500, f"{row.dsn_env} tanımlı değil")
    source = open_source(
        row.dialect,
        dsn,
        allow_tables=list(row.allow_tables),
        statement_timeout_ms=settings.sql_statement_timeout_ms,
        max_limit=settings.sql_max_limit,
    )
    try:
        return source.introspect(list(row.allow_tables)).as_dict()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"şema okunamadı: {exc}") from exc
    finally:
        source.close()

