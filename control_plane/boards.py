"""Personalised result boards: pin the latest output of one or more agents on a single screen."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from control_plane.auth import effective_write_group_id, require_permission
from control_plane.db import get_db
from control_plane.models import Agent, ResultBoard, Run, utcnow
from control_plane.rbac import Principal, can_access_record
from control_plane.serialize import iso, run_out

router = APIRouter(prefix="/api/boards")

ACTIVE = ("pending", "running")
FAILED = ("failed", "needs_review")
SIZES = ("sm", "md", "lg")
MAX_WIDGETS = 24


class WidgetIn(BaseModel):
    id: str | None = None
    agent_id: uuid.UUID
    size: str = "md"


class BoardIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    shared: bool = False
    widgets: list[WidgetIn] = Field(default_factory=list, max_length=MAX_WIDGETS)


class BoardPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    shared: bool | None = None
    widgets: list[WidgetIn] | None = Field(default=None, max_length=MAX_WIDGETS)


def _is_owner(principal: Principal, board: ResultBoard) -> bool:
    if principal.is_admin:
        return True
    return board.owner_user_id is not None and board.owner_user_id == principal.user_id


def _can_view(principal: Principal, board: ResultBoard) -> bool:
    if _is_owner(principal, board):
        return True
    return bool(board.shared) and can_access_record(principal, board.owner_group_id, "dashboard:read")


def _widgets(items: list[WidgetIn]) -> list[dict]:
    out, seen = [], set()
    for item in items:
        wid = item.id or uuid.uuid4().hex[:12]
        if wid in seen:
            wid = uuid.uuid4().hex[:12]
        seen.add(wid)
        out.append({"id": wid, "agent_id": str(item.agent_id), "size": item.size if item.size in SIZES else "md"})
    return out


def _board_out(board: ResultBoard, principal: Principal) -> dict:
    return {
        "id": str(board.id),
        "name": board.name,
        "shared": bool(board.shared),
        "owner_user_id": str(board.owner_user_id) if board.owner_user_id else None,
        "owned": _is_owner(principal, board),
        "widgets": board.widgets or [],
        "created_at": iso(board.created_at),
        "updated_at": iso(board.updated_at),
    }


def _board_or_404(db: Session, board_id: uuid.UUID, principal: Principal, *, write: bool = False) -> ResultBoard:
    board = db.get(ResultBoard, board_id)
    if board is None or not _can_view(principal, board):
        raise HTTPException(404, "pano yok")
    if write and not _is_owner(principal, board):
        raise HTTPException(403, "bu panoyu yalnızca sahibi değiştirebilir")
    return board


def _check_agents(db: Session, principal: Principal, widgets: list[dict]) -> None:
    for widget in widgets:
        agent = db.get(Agent, uuid.UUID(widget["agent_id"]))
        if agent is None or agent.status == "deleted" or not can_access_record(principal, agent.owner_group_id, "agent:read"):
            raise HTTPException(404, "ajan yok")


@router.get("")
def list_boards(
    principal: Principal = Depends(require_permission("dashboard:read")),
    db: Session = Depends(get_db),
):
    rows = db.query(ResultBoard).order_by(ResultBoard.created_at).all()
    return [_board_out(row, principal) for row in rows if _can_view(principal, row)]


@router.post("", status_code=201)
def create_board(
    body: BoardIn,
    principal: Principal = Depends(require_permission("dashboard:read")),
    db: Session = Depends(get_db),
):
    gid = effective_write_group_id(principal, "dashboard:read")
    widgets = _widgets(body.widgets)
    _check_agents(db, principal, widgets)
    board = ResultBoard(
        name=body.name.strip(),
        owner_user_id=principal.user_id,
        owner_group_id=gid,
        shared=body.shared,
        widgets=widgets,
    )
    db.add(board)
    db.commit()
    db.refresh(board)
    return _board_out(board, principal)


@router.get("/{board_id}")
def get_board(
    board_id: uuid.UUID,
    principal: Principal = Depends(require_permission("dashboard:read")),
    db: Session = Depends(get_db),
):
    return _board_out(_board_or_404(db, board_id, principal), principal)


@router.patch("/{board_id}")
def patch_board(
    board_id: uuid.UUID,
    body: BoardPatch,
    principal: Principal = Depends(require_permission("dashboard:read")),
    db: Session = Depends(get_db),
):
    board = _board_or_404(db, board_id, principal, write=True)
    if body.name is not None:
        board.name = body.name.strip()
    if body.shared is not None:
        board.shared = body.shared
    if body.widgets is not None:
        widgets = _widgets(body.widgets)
        _check_agents(db, principal, widgets)
        board.widgets = widgets
    board.updated_at = utcnow()
    db.commit()
    db.refresh(board)
    return _board_out(board, principal)


@router.delete("/{board_id}", status_code=204)
def delete_board(
    board_id: uuid.UUID,
    principal: Principal = Depends(require_permission("dashboard:read")),
    db: Session = Depends(get_db),
):
    board = _board_or_404(db, board_id, principal, write=True)
    db.delete(board)
    db.commit()


def _latest(db: Session, agent_id: uuid.UUID, *statuses: str) -> Run | None:
    query = db.query(Run).filter(Run.agent_id == agent_id, Run.dry_run.is_(False))
    if statuses:
        query = query.filter(Run.status.in_(statuses))
    return query.order_by(Run.created_at.desc()).first()


def widget_snapshot(db: Session, principal: Principal, widget: dict) -> dict:
    """Latest run state for one widget: what to show, whether it is stale, and whether a run is in flight."""
    base = {"id": widget["id"], "agent_id": widget["agent_id"], "size": widget.get("size", "md")}
    agent = db.get(Agent, uuid.UUID(widget["agent_id"]))
    if agent is None or agent.status == "deleted":
        return {**base, "state": "missing", "agent_name": None}
    if not can_access_record(principal, agent.owner_group_id, "agent:read"):
        return {**base, "state": "no_access", "agent_name": None}
    latest = _latest(db, agent.id)
    success = _latest(db, agent.id, "succeeded")
    active = _latest(db, agent.id, *ACTIVE)
    payload = {
        **base,
        "agent_name": agent.name,
        "agent_status": agent.status,
        "can_run": can_access_record(principal, agent.owner_group_id, "agent:run"),
        "active_run": run_out(active) if active else None,
        "latest_run": run_out(latest) if latest else None,
        "result": None,
        "stale": None,
    }
    if success is not None:
        payload["result"] = {**run_out(success), "report_markdown": success.report_markdown}
    if latest is None:
        payload["state"] = "empty"
    elif active is not None:
        payload["state"] = "running"
    elif latest.status in FAILED:
        payload["state"] = "failed"
        payload["stale"] = {
            "run_id": str(latest.id),
            "status": latest.status,
            "reason": latest.error or latest.needs_review_reason or "",
            "failed_at": iso(latest.finished_at or latest.created_at),
            "has_older_result": success is not None,
        }
    else:
        payload["state"] = "ok"
    return payload


@router.get("/{board_id}/snapshot")
def board_snapshot(
    board_id: uuid.UUID,
    principal: Principal = Depends(require_permission("dashboard:read")),
    db: Session = Depends(get_db),
):
    board = _board_or_404(db, board_id, principal)
    return {
        "board": _board_out(board, principal),
        "widgets": [widget_snapshot(db, principal, w) for w in board.widgets or []],
    }
