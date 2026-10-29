"""Delivery channel API. The credential is stored, never returned."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from control_plane.auth import effective_write_group_id, ensure_record_access, require_permission
from control_plane.db import get_db
from control_plane.delivery_catalog import apply_channel, channel_out, probe_channel
from control_plane.models import DeliveryChannel, DeliveryLog, Run
from control_plane.rbac import Principal, scope_query
from control_plane.service import ServiceError, audit

delivery = APIRouter(prefix="/api")


class ChannelIn(BaseModel):
    name: str = ""
    kind: str
    enabled: bool = True
    from_address: str
    from_name: str = ""
    allow_domains: list[str] | str = Field(default_factory=list)
    max_attachment_bytes: int = 2_000_000
    config: dict = Field(default_factory=dict)
    password: str | None = None
    secret_backend: str = ""
    secret_provider_id: uuid.UUID | None = None
    secret_path: str = ""
    secret_ref: dict = Field(default_factory=dict)
    k8s_secret_name: str | None = None
    k8s_secret_key: str | None = None


@delivery.get("/delivery-channels")
def list_channels(
    principal: Principal = Depends(require_permission("delivery_channel:read")),
    db: Session = Depends(get_db),
):
    query = scope_query(db.query(DeliveryChannel), DeliveryChannel, principal, "delivery_channel:read")
    rows = query.order_by(DeliveryChannel.name).all()
    return [channel_out(row) for row in rows]


@delivery.post("/delivery-channels", status_code=201)
def create_channel(
    body: ChannelIn,
    principal: Principal = Depends(require_permission("delivery_channel:write")),
    db: Session = Depends(get_db),
):
    group_id = effective_write_group_id(principal, "delivery_channel:write")
    name = body.name.strip()
    _check_name(name)
    if db.query(DeliveryChannel).filter(DeliveryChannel.name == name).first():
        raise HTTPException(409, "bu ada sahip bir teslimat kanalı var")
    row = DeliveryChannel(
        name=name,
        kind="smtp",
        from_address="pending@example.com",
        owner_group_id=group_id,
        created_by=principal.user_id,
    )
    body.name = name
    try:
        apply_channel(db, row, body, creating=True)
    except ServiceError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    db.add(row)
    db.flush()
    audit(db, principal.actor, "delivery_channel.created", "delivery_channel", str(row.id), {"name": row.name, "kind": row.kind})
    db.commit()
    db.refresh(row)
    return channel_out(row)


@delivery.patch("/delivery-channels/{channel_id}")
def update_channel(
    channel_id: uuid.UUID,
    body: ChannelIn,
    principal: Principal = Depends(require_permission("delivery_channel:write")),
    db: Session = Depends(get_db),
):
    row = _channel_or_404(db, channel_id, principal, "delivery_channel:write")
    try:
        apply_channel(db, row, body, creating=False)
    except ServiceError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    audit(db, principal.actor, "delivery_channel.updated", "delivery_channel", str(row.id), {"name": row.name, "kind": row.kind})
    db.commit()
    db.refresh(row)
    return channel_out(row)


@delivery.delete("/delivery-channels/{channel_id}", status_code=204)
def delete_channel(
    channel_id: uuid.UUID,
    principal: Principal = Depends(require_permission("delivery_channel:delete")),
    db: Session = Depends(get_db),
):
    row = _channel_or_404(db, channel_id, principal, "delivery_channel:delete")
    audit(db, principal.actor, "delivery_channel.deleted", "delivery_channel", str(row.id), {"name": row.name})
    db.delete(row)
    db.commit()


@delivery.post("/delivery-channels/{channel_id}/test")
def test_channel(
    channel_id: uuid.UUID,
    principal: Principal = Depends(require_permission("delivery_channel:test")),
    db: Session = Depends(get_db),
):
    row = _channel_or_404(db, channel_id, principal, "delivery_channel:test")
    try:
        result = probe_channel(db, row)
    except ServiceError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    audit(
        db,
        principal.actor,
        "delivery_channel.tested",
        "delivery_channel",
        str(row.id),
        {"ok": True, "latency_ms": result.get("latency_ms")},
    )
    db.commit()
    return result


@delivery.post("/runs/{run_id}/deliveries/{log_id}/resend")
def resend_delivery(
    run_id: uuid.UUID,
    log_id: uuid.UUID,
    principal: Principal = Depends(require_permission("delivery:resend")),
    db: Session = Depends(get_db),
):
    from control_plane.delivery_catalog import log_out
    from delivery.send import resend

    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "koşum yok")
    ensure_record_access(principal, run.owner_group_id, "delivery:resend", "koşum yok")
    row = db.get(DeliveryLog, log_id)
    if row is None or row.run_id != run.id:
        raise HTTPException(404, "teslim kaydı yok")
    try:
        latest = resend(db, run, row)
    except ServiceError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    return log_out(latest)


def _channel_or_404(
    db: Session,
    channel_id: uuid.UUID,
    principal: Principal | None = None,
    action: str = "delivery_channel:read",
) -> DeliveryChannel:
    row = db.get(DeliveryChannel, channel_id)
    if row is None:
        raise HTTPException(404, "teslimat kanalı yok")
    if principal is not None:
        ensure_record_access(principal, row.owner_group_id, action, "teslimat kanalı yok")
    return row


def _check_name(name: str) -> None:
    if not name or len(name) > 63 or any(char.isspace() for char in name):
        raise HTTPException(400, "kanal adı geçersiz")
