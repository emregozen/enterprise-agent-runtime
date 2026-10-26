from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from control_plane.db import get_db
from control_plane.models import Agent, AgentVersion, Artifact, AuditEvent, DataSourceRecord, Run, RunStep, Schedule, ToolCall
from control_plane.serialize import agent_out, run_out, schedule_out, spec_summary
from control_plane.service import (
    ServiceError,
    add_step,
    add_version,
    apply_self_schedule,
    complete_run,
    create_agent,
    artifact_key,
    hash_token,
    load_sources_for_spec,
    record_uploaded_artifact,
    trigger_run,
)
from control_plane.tool_proxy import ToolError, invoke_tool
from datasources import open_source
from harness.loop import builder_messages
from shared.artifacts import ArtifactTooLarge, build_store
from shared.config import get_settings
from shared.llm import make_llm, parse_json_response
from shared.spec import AgentSpec

public = APIRouter(prefix="/api")
internal = APIRouter(prefix="/api/internal")


class DatasourceIn(BaseModel):
    name: str
    dialect: str
    description: str = ""
    dsn_env: str = ""
    allow_tables: list[str] = Field(min_length=1)
    sensitivity: str = "internal"
    k8s_secret_name: str | None = None
    k8s_secret_key: str | None = None
    host: str = ""
    port: int | None = None
    database_name: str = ""
    username: str = ""
    password: str | None = None
    options: dict = Field(default_factory=dict)
    read_only: bool = True
    enabled: bool = True


class DatasourceUpdate(BaseModel):
    dialect: str | None = None
    description: str | None = None
    dsn_env: str | None = None
    allow_tables: list[str] | None = None
    sensitivity: str | None = None
    k8s_secret_name: str | None = None
    k8s_secret_key: str | None = None
    host: str | None = None
    port: int | None = None
    database_name: str | None = None
    username: str | None = None
    password: str | None = None
    options: dict | None = None
    read_only: bool | None = None
    enabled: bool | None = None


class DraftIn(BaseModel):
    description: str = Field(min_length=8)
    owner: str = "ekip"
    datasource_refs: list[str] = Field(min_length=1)
    model_ref: str | None = None


class AgentIn(BaseModel):
    spec: dict
    publish: bool = True


class AgentPatch(BaseModel):
    description: str | None = None
    owner: str | None = None
    spec: dict | None = None
    publish: bool = True


class RunIn(BaseModel):
    dry_run: bool = False


class BulkDeleteIn(BaseModel):
    older_than_days: int = Field(ge=1, default=30)
    statuses: list[str] = Field(default_factory=lambda: ["succeeded", "failed", "cancelled", "needs_review"])


class LlmIn(BaseModel):
    name: str
    base_url: str
    model: str
    api_key: str | None = None
    k8s_secret_name: str | None = None
    k8s_secret_key: str | None = "api_key"
    temperature: float | None = None
    reasoning_effort: str = ""
    extra_params: dict = Field(default_factory=dict)
    is_default: bool = False
    enabled: bool = True


class LlmPatch(BaseModel):
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    k8s_secret_name: str | None = None
    k8s_secret_key: str | None = None
    temperature: float | None = None
    reasoning_effort: str | None = None
    extra_params: dict | None = None
    is_default: bool | None = None
    enabled: bool | None = None


class PauseIn(BaseModel):
    paused: bool


class StepIn(BaseModel):
    name: str
    status: str = "succeeded"
    detail: dict = Field(default_factory=dict)


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
    return {
        "ok": True,
        "llm_mode": settings.llm_mode,
        "run_backend": settings.run_backend,
        "artifact_store": settings.resolved_artifact_store(),
    }


@public.get("/datasources")
def list_datasources(db: Session = Depends(get_db)):
    from control_plane.catalog import datasource_out

    rows = db.query(DataSourceRecord).order_by(DataSourceRecord.name).all()
    return [datasource_out(row) for row in rows]


@public.post("/datasources", status_code=201)
def create_datasource(body: DatasourceIn, db: Session = Depends(get_db)):
    from control_plane.catalog import apply_datasource, datasource_out

    if db.query(DataSourceRecord).filter(DataSourceRecord.name == body.name).first():
        raise HTTPException(409, "bu ada sahip bir veri kaynağı var")
    row = DataSourceRecord(name=body.name, dialect="postgres", dsn_env="DS_PENDING", allow_tables=body.allow_tables)
    try:
        apply_datasource(row, body, creating=True)
    except ServiceError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    db.add(row)
    db.commit()
    return datasource_out(row)


@public.post("/datasources/{name}/introspect")
def introspect(name: str, db: Session = Depends(get_db)):
    from control_plane.catalog import find_datasource

    row = find_datasource(db, name)
    if row is None:
        raise HTTPException(404, "veri kaynağı yok")
    return {"catalog": _live_catalog(row)}


@public.post("/builder/draft")
def draft(body: DraftIn, db: Session = Depends(get_db)):
    from control_plane.catalog import find_datasource

    settings = get_settings()
    sources = []
    for name in body.datasource_refs:
        row = find_datasource(db, name)
        if row is None or not row.enabled:
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
    from control_plane.catalog import persist_llm_calls, resolve_llm

    payload = {
        "description": body.description,
        "owner": body.owner,
        "datasources": sources,
        "agentspec_schema": AgentSpec.model_json_schema(),
    }
    resolved = resolve_llm(db, settings, body.model_ref or "local-default")
    llm = make_llm(settings, resolved.get("name") or "local-default", provider=resolved)
    spec = None
    last_error: Exception | None = None
    for _ in range(2):
        try:
            raw = parse_json_response(llm.complete(builder_messages(payload)))
            spec = AgentSpec.model_validate(raw).canonical()
            break
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            payload = {**payload, "validation_error": str(exc)[:2000]}
    persist_llm_calls(db, None, getattr(llm, "calls", []), "builder")
    db.commit()
    if spec is None:
        raise HTTPException(422, f"taslak üretilemedi: {last_error}")
    if body.model_ref and not any(item["sensitivity"] == "restricted" for item in sources):
        spec["spec"]["model"]["class"] = body.model_ref
        spec = AgentSpec.model_validate(spec).canonical()
    return {"spec": spec, "summary": spec_summary(spec)}


@public.get("/agents")
def list_agents(include_deleted: bool = False, db: Session = Depends(get_db)):
    query = db.query(Agent).order_by(Agent.created_at.desc())
    if not include_deleted:
        query = query.filter(Agent.status != "deleted")
    rows = query.all()
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


def _agent_detail(db: Session, agent: Agent) -> dict:
    db.refresh(agent)
    schedule = db.query(Schedule).filter(Schedule.agent_id == agent.id).one_or_none()
    versions = (
        db.query(AgentVersion).filter(AgentVersion.agent_id == agent.id).order_by(AgentVersion.version.desc()).all()
    )
    current = next((row.spec for row in versions if row.version == agent.current_version), None)
    return {
        **agent_out(agent, schedule, goal=(current or {}).get("spec", {}).get("goal", agent.description)),
        "spec": current,
        "version": agent.current_version,
        "versions": [
            {"version": row.version, "status": row.status, "created_at": row.created_at.isoformat(), "spec": row.spec}
            for row in versions
        ],
    }


@public.get("/agents/{agent_id}")
def get_agent(agent_id: uuid.UUID, db: Session = Depends(get_db)):
    return _agent_detail(db, _agent_or_404(db, agent_id))


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
def list_runs(
    response: Response,
    agent_id: uuid.UUID | None = None,
    status: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    query = db.query(Run).order_by(Run.created_at.desc())
    if agent_id:
        query = query.filter(Run.agent_id == agent_id)
    if status:
        query = query.filter(Run.status == status)
    if q:
        query = query.filter(Run.agent_name.ilike(f"%{q}%"))
    total = query.count()
    response.headers["X-Total-Count"] = str(total)
    return [run_out(row) for row in query.offset(max(offset, 0)).limit(min(limit, 200)).all()]


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
    store = build_store(get_settings())
    try:
        chunks = store.iter_chunks(artifact.storage_uri)
        first = next(chunks, None)
    except FileNotFoundError as exc:
        raise HTTPException(404, "artefakt dosyası yok") from exc
    except ValueError as exc:
        raise HTTPException(404, "artefakt dosyası yok") from exc

    def body():
        if first is not None:
            yield first
        yield from chunks

    return StreamingResponse(
        body(),
        media_type=artifact.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{artifact.name}"',
            "Content-Length": str(artifact.size_bytes),
        },
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
async def post_artifact(
    run_id: uuid.UUID,
    request: Request,
    authorization: str | None = Header(default=None),
    x_artifact_name: str | None = Header(default=None),
    x_artifact_sha256: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    run = _auth_run(db, run_id, authorization)
    settings = get_settings()
    try:
        key = artifact_key(run, x_artifact_name or "")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    media = (request.headers.get("content-type") or "application/octet-stream").split(";", 1)[0].strip()
    if not media or len(media) > 120:
        media = "application/octet-stream"
    declared = request.headers.get("content-length")
    if declared:
        try:
            announced = int(declared)
        except ValueError as exc:
            raise HTTPException(400, "Content-Length sayı olmalı") from exc
        if announced > settings.artifact_max_bytes:
            raise HTTPException(413, f"artefakt {settings.artifact_max_bytes} bayt sınırını aşıyor")
    store = build_store(settings)
    upload = store.start_upload(key, media, settings.artifact_max_bytes)
    try:
        async for chunk in request.stream():
            upload.write(chunk)
        uri, size, digest = upload.finish()
    except ArtifactTooLarge as exc:
        upload.abort()
        raise HTTPException(413, str(exc)) from exc
    except Exception:
        upload.abort()
        raise
    try:
        row = record_uploaded_artifact(
            db,
            run,
            name=x_artifact_name or "",
            media_type=media,
            uri=uri,
            digest=digest,
            size=size,
            claimed_sha=(x_artifact_sha256 or "").strip(),
        )
    except ServiceError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    return {"id": str(row.id), "sha256": row.sha256, "size_bytes": row.size_bytes}


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
    from control_plane.catalog import datasource_out

    return datasource_out(row)


def _live_catalog(row: DataSourceRecord) -> dict:
    from control_plane.catalog import datasource_dsn

    settings = get_settings()
    try:
        dsn = datasource_dsn(row, require=True)
    except ServiceError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
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


def _source_or_404(db: Session, datasource_id: uuid.UUID) -> DataSourceRecord:
    row = db.get(DataSourceRecord, datasource_id)
    if row is None:
        raise HTTPException(404, "veri kaynağı yok")
    return row


@public.get("/datasources/{datasource_id}")
def get_datasource(datasource_id: uuid.UUID, db: Session = Depends(get_db)):
    return _ds_out(_source_or_404(db, datasource_id))


@public.patch("/datasources/{datasource_id}")
def patch_datasource(datasource_id: uuid.UUID, body: DatasourceUpdate, db: Session = Depends(get_db)):
    from control_plane.catalog import apply_datasource

    row = _source_or_404(db, datasource_id)
    merged = DatasourceIn(
        name=row.name,
        dialect=body.dialect or row.dialect,
        description=row.description if body.description is None else body.description,
        dsn_env=row.dsn_env if body.dsn_env is None else body.dsn_env,
        allow_tables=row.allow_tables if body.allow_tables is None else body.allow_tables,
        sensitivity=body.sensitivity or row.sensitivity,
        k8s_secret_name=row.k8s_secret_name if body.k8s_secret_name is None else body.k8s_secret_name,
        k8s_secret_key=row.k8s_secret_key if body.k8s_secret_key is None else body.k8s_secret_key,
        host=row.host if body.host is None else body.host,
        port=row.port if body.port is None else body.port,
        database_name=row.database_name if body.database_name is None else body.database_name,
        username=row.username if body.username is None else body.username,
        password=body.password,
        options=row.options if body.options is None else body.options,
        read_only=row.read_only if body.read_only is None else body.read_only,
        enabled=row.enabled if body.enabled is None else body.enabled,
    )
    try:
        apply_datasource(row, merged, creating=False)
    except ServiceError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    db.commit()
    return _ds_out(row)


@public.delete("/datasources/{datasource_id}", status_code=204)
def delete_datasource(datasource_id: uuid.UUID, db: Session = Depends(get_db)):
    row = _source_or_404(db, datasource_id)
    db.delete(row)
    db.commit()


@public.post("/datasources/{datasource_id}/test")
def test_datasource_route(datasource_id: uuid.UUID, db: Session = Depends(get_db)):
    from control_plane.catalog import test_datasource

    try:
        return test_datasource(_source_or_404(db, datasource_id))
    except ServiceError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@public.get("/llm/providers")
def list_providers(db: Session = Depends(get_db)):
    from control_plane.catalog import provider_out
    from control_plane.models import LlmProvider

    rows = db.query(LlmProvider).order_by(LlmProvider.name).all()
    return [provider_out(row) for row in rows]


@public.post("/llm/providers", status_code=201)
def create_provider(body: LlmIn, db: Session = Depends(get_db)):
    from control_plane.catalog import apply_provider, provider_out
    from control_plane.models import LlmProvider

    if db.query(LlmProvider).filter(LlmProvider.name == body.name).first():
        raise HTTPException(409, "bu ada sahip bir model var")
    row = LlmProvider(name=body.name, base_url=body.base_url, model=body.model)
    apply_provider(db, row, body, creating=True)
    db.add(row)
    db.commit()
    return provider_out(row)


@public.patch("/llm/providers/{provider_id}")
def patch_provider(provider_id: uuid.UUID, body: LlmPatch, db: Session = Depends(get_db)):
    from control_plane.catalog import apply_provider, provider_out
    from control_plane.models import LlmProvider

    row = db.get(LlmProvider, provider_id)
    if row is None:
        raise HTTPException(404, "model yok")
    merged = LlmIn(
        name=row.name,
        base_url=body.base_url or row.base_url,
        model=body.model or row.model,
        api_key=body.api_key,
        k8s_secret_name=row.k8s_secret_name if body.k8s_secret_name is None else body.k8s_secret_name,
        k8s_secret_key=body.k8s_secret_key or row.k8s_secret_key,
        temperature=row.temperature if body.temperature is None else body.temperature,
        reasoning_effort=row.reasoning_effort if body.reasoning_effort is None else body.reasoning_effort,
        extra_params=row.extra_params if body.extra_params is None else body.extra_params,
        is_default=row.is_default if body.is_default is None else body.is_default,
        enabled=row.enabled if body.enabled is None else body.enabled,
    )
    apply_provider(db, row, merged, creating=False)
    db.commit()
    return provider_out(row)


@public.delete("/llm/providers/{provider_id}", status_code=204)
def delete_provider(provider_id: uuid.UUID, db: Session = Depends(get_db)):
    from control_plane.models import LlmProvider

    row = db.get(LlmProvider, provider_id)
    if row is None:
        raise HTTPException(404, "model yok")
    db.delete(row)
    db.commit()


@public.post("/llm/providers/{provider_id}/test")
def test_provider_route(provider_id: uuid.UUID, db: Session = Depends(get_db)):
    from control_plane.catalog import test_provider
    from control_plane.models import LlmProvider

    row = db.get(LlmProvider, provider_id)
    if row is None:
        raise HTTPException(404, "model yok")
    try:
        return test_provider(row, get_settings())
    except ServiceError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@public.get("/dashboard")
def get_dashboard(days: int = 14, db: Session = Depends(get_db)):
    from control_plane.catalog import dashboard

    return dashboard(db, days)


@public.get("/settings")
def get_public_settings():
    from control_plane.catalog import public_settings

    return public_settings(get_settings())


@public.patch("/agents/{agent_id}")
def patch_agent(agent_id: uuid.UUID, body: AgentPatch, db: Session = Depends(get_db)):
    agent = _agent_or_404(db, agent_id)
    if agent.status == "deleted":
        raise HTTPException(409, "silinmiş ajan düzenlenemez")
    if body.description is not None:
        agent.description = body.description
    if body.owner is not None:
        agent.owner = body.owner
    if body.spec is None:
        db.commit()
        return _agent_detail(db, agent)
    try:
        add_version(db, agent, body.spec, publish=body.publish, actor="ui")
    except ServiceError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    return _agent_detail(db, agent)


@public.post("/agents/{agent_id}/duplicate", status_code=201)
def post_duplicate(agent_id: uuid.UUID, db: Session = Depends(get_db)):
    from control_plane.catalog import duplicate_agent

    agent = _agent_or_404(db, agent_id)
    try:
        created = duplicate_agent(db, agent, "ui")
    except ServiceError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    schedule = db.query(Schedule).filter(Schedule.agent_id == created.id).one_or_none()
    return agent_out(created, schedule)


@public.delete("/agents/{agent_id}", status_code=204)
def delete_agent_route(agent_id: uuid.UUID, db: Session = Depends(get_db)):
    from control_plane.catalog import delete_agent

    delete_agent(db, _agent_or_404(db, agent_id), "ui")


@public.get("/agents/{agent_id}/diff")
def agent_diff(agent_id: uuid.UUID, left: int, right: int, db: Session = Depends(get_db)):
    from control_plane.catalog import spec_diff

    try:
        text = spec_diff(db, _agent_or_404(db, agent_id), left, right)
    except ServiceError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    return {"diff": text}


@public.post("/runs/bulk-delete")
def post_bulk_delete(body: BulkDeleteIn, db: Session = Depends(get_db)):
    from control_plane.catalog import bulk_delete_runs

    try:
        removed = bulk_delete_runs(db, older_than_days=body.older_than_days, statuses=body.statuses, actor="ui")
    except ServiceError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    return {"deleted": removed}


@public.post("/runs/{run_id}/cancel")
def post_cancel(run_id: uuid.UUID, db: Session = Depends(get_db)):
    from control_plane.catalog import cancel_run

    try:
        run = cancel_run(db, _run_or_404(db, run_id), "ui")
    except ServiceError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    return run_out(run)


@public.post("/runs/{run_id}/rerun", status_code=202)
def post_rerun(run_id: uuid.UUID, db: Session = Depends(get_db)):
    from control_plane.catalog import rerun

    try:
        run, _token = rerun(db, _run_or_404(db, run_id), "ui")
    except ServiceError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    return run_out(run)


@public.delete("/runs/{run_id}", status_code=204)
def delete_run_route(run_id: uuid.UUID, db: Session = Depends(get_db)):
    from control_plane.catalog import delete_run

    try:
        delete_run(db, _run_or_404(db, run_id), "ui")
    except ServiceError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc

