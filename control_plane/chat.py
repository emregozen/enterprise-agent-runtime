"""Interactive 'Ask Data' chat service and routes.

Provides a fast-path, multi-turn conversational interface over governed datasources:
- Enforces the exact same AST SQL guard (`guard_sql`), read-only session settings,
  table allowlists, Conjur secret resolution, RBAC, and group isolation as agent runs.
- Protects control-plane memory and CPU under concurrent load via:
  1. Hard 100-row result cap (`CHAT_MAX_ROWS = 100`) and 5-second query timeout (`CHAT_TIMEOUT_MS = 5000`)
  2. 60-second in-memory TTL cache for Conjur DSN resolution and schema introspection
  3. Bounded concurrency semaphore (`MAX_CONCURRENT_CHAT_QUERIES = 10`)
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from typing import Any

log = logging.getLogger("control-plane.chat")

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from control_plane.auth import effective_write_group_id, ensure_record_access, require_permission
from control_plane.catalog import connection_material, find_datasource, find_provider, persist_llm_calls, resolve_llm
from control_plane.db import get_db
from control_plane.models import ChatMessage, ChatSession, DataSourceRecord, utcnow
from control_plane.rbac import Principal, allowed_group_ids_for, scope_query
from control_plane.service import ServiceError, audit
from datasources import open_source
from shared.config import get_settings
from shared.crypto import redact
from shared.llm import make_llm, parse_json_response
from sqlguard import guard_sql

router = APIRouter(prefix="/api/chat", tags=["chat"])

CHAT_MAX_ROWS = 100
CHAT_TIMEOUT_MS = 5000
CACHE_TTL_SECONDS = 60.0
MAX_CONCURRENT_CHAT_QUERIES = 10

_CHAT_SEMAPHORE = threading.BoundedSemaphore(MAX_CONCURRENT_CHAT_QUERIES)
_CACHE_LOCK = threading.Lock()
_SOURCE_CACHE: dict[str, tuple[float, str, list[str], dict]] = {}

CHAT_SQL_SYSTEM = """You are an enterprise SQL analyst assistant.
Return ONE JSON object and nothing else:
{
  "title": "short 3-6 word conversation title",
  "reasoning": "one sentence explaining the query",
  "sql": "single read-only SELECT statement"
}
Rules:
1. Write a SINGLE read-only SELECT statement using ONLY the tables and columns in `catalog`.
2. Never use INSERT, UPDATE, DELETE, DROP, CREATE, ALTER, TRUNCATE, GRANT, or SELECT INTO.
3. Push aggregations (SUM, AVG, COUNT, MIN, MAX, GROUP BY, ORDER BY) into SQL whenever possible instead of dumping raw rows.
4. Every non-aggregated SELECT MUST include a row limit at most 100 (`LIMIT 100` for postgres, `FETCH FIRST 100 ROWS ONLY` for oracle).
5. Use `history` to resolve follow-up questions (e.g. "break that down by month", "only top 5", "filter for a specific region").
6. If `repair` is present, fix the SQL error reported in `repair.error`.
"""

CHAT_ANSWER_SYSTEM = """You are a concise, insightful enterprise data analyst.
Return ONE JSON object and nothing else:
{
  "answer_markdown": "clear markdown answer summarizing the findings from `rows`",
  "follow_ups": ["short follow-up question 1", "short follow-up question 2", "short follow-up question 3"]
}
Rules:
1. Base every number strictly on `rows`. Never invent figures.
2. Keep `answer_markdown` crisp and executive-ready: highlight key takeaways, comparisons, or outliers using bullet points or bold figures. Do not repeat a huge markdown table if there are many rows, since the UI already renders an interactive data table below your message.
3. Write `answer_markdown` and `follow_ups` in the same language as the user's `question` (Turkish if the question is in Turkish, English if in English).
"""


class ChatAskIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    datasource: str = Field(min_length=1, max_length=120)
    session_id: uuid.UUID | None = None
    model_ref: str | None = None


def clear_chat_cache() -> None:
    with _CACHE_LOCK:
        _SOURCE_CACHE.clear()


def _cached_material_and_catalog(db: Session, row: DataSourceRecord) -> tuple[str, list[str], dict]:
    cache_key = f"{row.id}:{row.password_hint}:{row.secret_backend}:{row.secret_path}:{','.join(row.allow_tables or [])}"
    now = time.monotonic()
    with _CACHE_LOCK:
        cached = _SOURCE_CACHE.get(cache_key)
        if cached and cached[0] > now:
            return cached[1], cached[2], cached[3]

    try:
        dsn, redactions = connection_material(db, row)
    except ServiceError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    if not dsn:
        raise HTTPException(400, f"{row.name} veri kaynağının adresi tanımlı değil")

    source = None
    try:
        source = open_source(
            row.dialect,
            dsn,
            allow_tables=list(row.allow_tables),
            statement_timeout_ms=CHAT_TIMEOUT_MS,
            max_limit=CHAT_MAX_ROWS,
        )
        catalog = source.introspect(list(row.allow_tables)).as_dict()
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"{row.name} veri kaynağına ulaşılamadı.") from exc
    finally:
        if source is not None:
            try:
                source.close()
            except Exception:
                pass

    with _CACHE_LOCK:
        _SOURCE_CACHE[cache_key] = (now + CACHE_TTL_SECONDS, dsn, redactions, catalog)
    return dsn, redactions, catalog


def _resolve_chat_llm(db: Session, settings, model_ref: str | None, allowed_group_ids: set[uuid.UUID] | None):
    resolved = resolve_llm(db, settings, model_ref or "local-default", allowed_group_ids=allowed_group_ids)
    if settings.llm_mode != "fake" and not resolved.get("api_key") and resolved.get("k8s_secret_name"):
        from secret_sources.errors import SecretProviderError
        from secret_sources.resolve import resolve_kubernetes_value

        try:
            resolved["api_key"] = resolve_kubernetes_value(
                resolved["k8s_secret_name"],
                resolved.get("k8s_secret_key") or "api_key",
                [settings.run_namespace, settings.secret_namespace],
            )
        except SecretProviderError as exc:
            raise HTTPException(502, str(exc)) from exc
    return make_llm(settings, resolved.get("name") or "local-default", provider=resolved), resolved


def _session_out(session: ChatSession, message_count: int | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": str(session.id),
        "title": session.title,
        "datasource_name": session.datasource_name,
        "model_ref": session.model_ref,
        "owner_group_id": str(session.owner_group_id) if session.owner_group_id else None,
        "created_by": str(session.created_by) if session.created_by else None,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "updated_at": session.updated_at.isoformat() if session.updated_at else None,
    }
    if message_count is not None:
        out["message_count"] = message_count
    return out


def _message_out(msg: ChatMessage) -> dict[str, Any]:
    return {
        "id": str(msg.id),
        "session_id": str(msg.session_id),
        "ordinal": msg.ordinal,
        "role": msg.role,
        "content": msg.content,
        "sql": msg.sql,
        "columns": msg.columns or [],
        "rows": msg.rows or [],
        "row_count": msg.row_count or 0,
        "latency_ms": msg.latency_ms,
        "status": msg.status,
        "error": msg.error,
        "guard_info": msg.guard_info or {},
        "follow_ups": msg.follow_ups or [],
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }


def _HistorySummary(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    history: list[dict[str, Any]] = []
    for item in messages[-6:]:
        entry: dict[str, Any] = {"role": item.role, "content": item.content[:600]}
        if item.sql:
            entry["sql"] = item.sql[:1000]
        if item.rows:
            entry["sample_rows"] = item.rows[:5]
        history.append(entry)
    return history


@router.get("/sessions")
def list_sessions(
    limit: int = 25,
    principal: Principal = Depends(require_permission("chat:read")),
    db: Session = Depends(get_db),
):
    query = scope_query(db.query(ChatSession), ChatSession, principal, "chat:read").order_by(
        ChatSession.updated_at.desc()
    )
    rows = query.limit(min(max(limit, 1), 100)).all()
    return [_session_out(row) for row in rows]


@router.get("/sessions/{session_id}")
def get_session(
    session_id: uuid.UUID,
    principal: Principal = Depends(require_permission("chat:read")),
    db: Session = Depends(get_db),
):
    session = db.get(ChatSession, session_id)
    if session is None:
        raise HTTPException(404, "sohbet oturumu bulunamadı")
    ensure_record_access(principal, session.owner_group_id, "chat:read", "sohbet oturumu bulunamadı")
    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session.id)
        .order_by(ChatMessage.ordinal.asc())
        .all()
    )
    return {
        **_session_out(session, len(messages)),
        "messages": [_message_out(m) for m in messages],
    }


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(
    session_id: uuid.UUID,
    principal: Principal = Depends(require_permission("chat:delete")),
    db: Session = Depends(get_db),
):
    session = db.get(ChatSession, session_id)
    if session is None:
        raise HTTPException(404, "sohbet oturumu bulunamadı")
    ensure_record_access(principal, session.owner_group_id, "chat:delete", "sohbet oturumu bulunamadı")
    audit(db, principal.actor, "chat.session_deleted", "chat_session", str(session.id), {"title": session.title})
    db.delete(session)
    db.commit()


@router.post("/ask")
def ask_data(
    body: ChatAskIn,
    principal: Principal = Depends(require_permission("chat:ask")),
    db: Session = Depends(get_db),
):
    question = body.question.strip()
    if not question:
        raise HTTPException(400, "soru boş olamaz")

    allowed_ds_groups = None if principal.is_admin else allowed_group_ids_for(principal, "datasource:read")
    ds = find_datasource(db, body.datasource, allowed_group_ids=allowed_ds_groups)
    if ds is None or not ds.enabled:
        raise HTTPException(404, f"veri kaynağı yok: {body.datasource}")

    settings = get_settings()
    if ds.sensitivity == "restricted" and (body.model_ref or "").startswith("cloud"):
        raise HTTPException(403, "kısıtlı veri bulut modeline gönderilemez")

    if body.session_id:
        session = db.get(ChatSession, body.session_id)
        if session is None:
            raise HTTPException(404, "sohbet oturumu bulunamadı")
        ensure_record_access(principal, session.owner_group_id, "chat:ask", "sohbet oturumu bulunamadı")
        session.datasource_name = ds.name
        if body.model_ref:
            session.model_ref = body.model_ref
    else:
        group_id = ds.owner_group_id or effective_write_group_id(principal, "chat:ask")
        session = ChatSession(
            title=question[:80],
            datasource_name=ds.name,
            model_ref=body.model_ref,
            owner_group_id=group_id,
            created_by=principal.user_id,
        )
        db.add(session)
        db.flush()

    prior_messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session.id)
        .order_by(ChatMessage.ordinal.asc())
        .all()
    )
    next_ordinal = (prior_messages[-1].ordinal + 1) if prior_messages else 1

    user_msg = ChatMessage(
        session_id=session.id,
        ordinal=next_ordinal,
        role="user",
        content=question,
        status="succeeded",
    )
    db.add(user_msg)
    db.commit()
    db.refresh(session)
    db.refresh(user_msg)

    log.info("chat.ask actor=%s datasource=%s session=%s question=%s", principal.actor, ds.name, session.id, question[:120])

    acquired = _CHAT_SEMAPHORE.acquire(timeout=15.0)
    if not acquired:
        raise HTTPException(429, "Sorgu yoğunluğu sınırı aşıldı, lütfen birkaç saniye sonra tekrar deneyin.")

    started = time.monotonic()
    try:
        try:
            dsn, redactions, catalog = _cached_material_and_catalog(db, ds)
            llm, _resolved_meta = _resolve_chat_llm(db, settings, body.model_ref or session.model_ref, allowed_ds_groups)
        except HTTPException as exc:
            latency_ms = int((time.monotonic() - started) * 1000)
            reason = str(exc.detail)
            assistant_msg = ChatMessage(
                session_id=session.id,
                ordinal=next_ordinal + 1,
                role="assistant",
                content=f"**{ds.name}** veri kaynağına bağlanılamadı: {reason}",
                sql=None,
                columns=[],
                rows=[],
                row_count=0,
                latency_ms=latency_ms,
                status="failed",
                error=reason,
                guard_info={"dialect": ds.dialect, "allowed_tables": list(ds.allow_tables), "blocked": False},
                follow_ups=[],
            )
            session.updated_at = utcnow()
            db.add(assistant_msg)
            db.commit()
            return {
                "session": _session_out(session, next_ordinal + 1),
                "user_message": _message_out(user_msg),
                "assistant_message": _message_out(assistant_msg),
            }

        history = _HistorySummary(prior_messages)

        sql_plan: dict[str, Any] = {}
        guarded = None
        columns: list[str] = []
        rows: list[dict] = []
        explained_cost: float | None = None
        last_error: str | None = None

        source = open_source(
            ds.dialect,
            dsn,
            allow_tables=list(ds.allow_tables),
            statement_timeout_ms=CHAT_TIMEOUT_MS,
            max_limit=CHAT_MAX_ROWS,
        )
        try:
            for attempt in range(2):
                payload: dict[str, Any] = {
                    "role": "chat_sql",
                    "question": question,
                    "dialect": ds.dialect,
                    "catalog": catalog,
                    "max_rows": CHAT_MAX_ROWS,
                    "history": history,
                    "repair": {"error": last_error, "previous_sql": sql_plan.get("sql")} if last_error else None,
                }
                try:
                    raw_plan = llm.complete(
                        [
                            {"role": "system", "content": CHAT_SQL_SYSTEM},
                            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
                        ]
                    )
                    sql_plan = parse_json_response(raw_plan)
                except Exception as exc:  # noqa: BLE001
                    last_error = f"Model SQL planı üretemedi: { redact(str(exc), redactions)[:300] }"
                    if attempt == 0:
                        continue
                    break
                candidate_sql = str(sql_plan.get("sql") or "").strip()
                guarded = guard_sql(
                    candidate_sql,
                    dialect=ds.dialect,
                    allow_tables=list(ds.allow_tables),
                    max_limit=CHAT_MAX_ROWS,
                )
                if not guarded.ok:
                    last_error = guarded.reason or "SQL güvenlik kontrolünden geçemedi"
                    if attempt == 0:
                        continue
                    audit(
                        db,
                        principal.actor,
                        "chat.rejected",
                        "chat_session",
                        str(session.id),
                        {"datasource": ds.name, "reason": last_error, "sql": candidate_sql[:500]},
                    )
                    break

                try:
                    explained = source.explain(guarded.sql)
                    if explained.supported and explained.cost is not None:
                        explained_cost = explained.cost
                        if explained.cost > settings.sql_max_cost:
                            last_error = f"Sorgu maliyeti eşiği aştı ({explained.cost})"
                            guarded = None
                            break
                    columns, rows = source.query_rows(guarded.sql, max_rows=CHAT_MAX_ROWS)
                    last_error = None
                    break
                except Exception as exc:  # noqa: BLE001
                    last_error = redact(str(exc), redactions)[:400]
                    guarded = None
                    if attempt == 0:
                        continue
        finally:
            try:
                source.close()
            except Exception:
                pass

        latency_ms = int((time.monotonic() - started) * 1000)

        if last_error or guarded is None or not guarded.ok:
            reason = last_error or "Sorgu çalıştırılamadı"
            assistant_msg = ChatMessage(
                session_id=session.id,
                ordinal=next_ordinal + 1,
                role="assistant",
                content=f"Sorgu güvenlik veya veritabanı kuralı nedeniyle çalıştırılamadı: **{reason}**",
                sql=str(sql_plan.get("sql") or "")[:2000] or None,
                columns=[],
                rows=[],
                row_count=0,
                latency_ms=latency_ms,
                status="failed",
                error=reason,
                guard_info={"dialect": ds.dialect, "allowed_tables": list(ds.allow_tables), "blocked": True},
                follow_ups=[
                    f"Show summary of {', '.join(ds.allow_tables[:2])}",
                    "What columns are available in this data source?",
                ],
            )
            session.updated_at = utcnow()
            db.add(assistant_msg)
            persist_llm_calls(db, None, getattr(llm, "calls", []), "chat", owner_group_id=session.owner_group_id)
            db.commit()
            return {
                "session": _session_out(session, next_ordinal + 1),
                "user_message": _message_out(user_msg),
                "assistant_message": _message_out(assistant_msg),
            }

        answer_payload = {
            "role": "chat_answer",
            "question": question,
            "datasource": ds.name,
            "dialect": ds.dialect,
            "sql": guarded.sql,
            "columns": columns,
            "rows": rows[:50],
            "row_count": len(rows),
        }
        try:
            raw_answer = llm.complete(
                [
                    {"role": "system", "content": CHAT_ANSWER_SYSTEM},
                    {"role": "user", "content": json.dumps(answer_payload, ensure_ascii=False, default=str)},
                ]
            )
            parsed_answer = parse_json_response(raw_answer)
            answer_md = str(parsed_answer.get("answer_markdown") or "").strip()
            follow_ups = [str(item) for item in (parsed_answer.get("follow_ups") or []) if str(item).strip()][:3]
        except Exception:
            answer_md = f"Query executed cleanly against **{ds.name}** and returned **{len(rows)}** rows."
            follow_ups = []

        if not answer_md:
            answer_md = f"Query executed against **{ds.name}** ({len(rows)} rows)."

        if not prior_messages and sql_plan.get("title"):
            session.title = str(sql_plan["title"]).strip()[:180] or session.title
        session.updated_at = utcnow()

        guard_info = {
            "dialect": ds.dialect,
            "tables": guarded.tables,
            "aggregate": guarded.aggregate,
            "cost": explained_cost,
            "read_only": True,
            "max_rows": CHAT_MAX_ROWS,
        }
        assistant_msg = ChatMessage(
            session_id=session.id,
            ordinal=next_ordinal + 1,
            role="assistant",
            content=answer_md,
            sql=guarded.sql,
            columns=columns,
            rows=rows,
            row_count=len(rows),
            latency_ms=latency_ms,
            status="succeeded",
            error=None,
            guard_info=guard_info,
            follow_ups=follow_ups,
        )
        db.add(assistant_msg)
        persist_llm_calls(db, None, getattr(llm, "calls", []), "chat", owner_group_id=session.owner_group_id)
        audit(
            db,
            principal.actor,
            "chat.query",
            "chat_session",
            str(session.id),
            {
                "datasource": ds.name,
                "tables": guarded.tables,
                "row_count": len(rows),
                "latency_ms": latency_ms,
            },
        )
        db.commit()
        return {
            "session": _session_out(session, next_ordinal + 1),
            "user_message": _message_out(user_msg),
            "assistant_message": _message_out(assistant_msg),
        }
    finally:
        _CHAT_SEMAPHORE.release()
