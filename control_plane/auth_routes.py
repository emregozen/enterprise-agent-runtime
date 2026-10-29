"""Authentication and platform administration API routes."""

from __future__ import annotations

import hmac
import secrets
import time
import urllib.parse
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from control_plane.auth import (
    FLOW_COOKIE,
    SESSION_COOKIE,
    OidcError,
    authenticate_request,
    build_authorization_url,
    build_principal_for_user,
    create_user_session,
    ensure_default_group,
    exchange_code_for_tokens,
    fetch_discovery,
    generate_pkce_pair,
    provision_or_update_user,
    require_permission,
    serialize_principal,
    sign_flow_cookie,
    verify_flow_cookie,
    verify_jwt_token,
)
from control_plane.db import get_db
from control_plane.models import AuditEvent, AuthSession, Group, GroupMembership, User
from control_plane.rbac import VALID_ROLES, VALID_STATUSES, Principal
from control_plane.service import audit, hash_token
from shared.config import Settings, get_settings

auth_router = APIRouter(prefix="/api")


class SwitchGroupIn(BaseModel):
    group_id: uuid.UUID


class ApproveUserIn(BaseModel):
    group_id: uuid.UUID | None = None
    role: str = "viewer"
    is_admin: bool = False


class RejectUserIn(BaseModel):
    reason: str = ""


class UserPatchIn(BaseModel):
    status: str | None = None
    is_admin: bool | None = None
    display_name: str | None = None


class GroupIn(BaseModel):
    name: str
    description: str = ""


class GroupPatchIn(BaseModel):
    description: str | None = None


class MembershipIn(BaseModel):
    user_id: uuid.UUID
    role: str = "viewer"


def _callback_url(request: Request, settings: Settings) -> str:
    forwarded_proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip()
    forwarded_host = (request.headers.get("x-forwarded-host") or "").split(",")[0].strip()
    host = forwarded_host or request.headers.get("host") or ""
    scheme = forwarded_proto or request.url.scheme or "http"
    if host:
        # When proxied through UI /backend/api/auth/callback, keep /backend prefix if Referer/Origin indicates UI
        prefix = "/backend" if _is_proxied_from_ui(request) else ""
        return f"{scheme}://{host}{prefix}/api/auth/callback"
    base = (settings.control_plane_public_url or "http://127.0.0.1:8841").rstrip("/")
    return f"{base}/api/auth/callback"


def _is_proxied_from_ui(request: Request) -> bool:
    if (request.headers.get("x-forwarded-prefix") or "").strip() == "/backend":
        return True
    # UI server.mjs proxies /backend/api/... to /api/...; check if request has referer or host on UI port
    referer = request.headers.get("referer") or ""
    if referer and "/backend/" not in referer:
        # Browser is talking to UI root, which proxies /backend/api/...
        return True
    return False


def _cookie_secure(request: Request, settings: Settings) -> bool:
    if settings.auth_cookie_secure:
        return True
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "").lower()
    return proto == "https"


def _safe_return_to(return_to: str | None) -> str:
    target = (return_to or "/").strip()
    if not target.startswith("/") or target.startswith("//") or "://" in target:
        return "/"
    return target


@auth_router.get("/auth/login")
def login(
    request: Request,
    return_to: str = "/",
    next: str | None = None,
    redirect: bool = True,
):
    settings = get_settings()
    target_path = _safe_return_to(next if next is not None else return_to)
    if (settings.auth_mode or "disabled").strip().lower() == "disabled":
        if redirect:
            return RedirectResponse(url=target_path, status_code=302)
        return {"auth_mode": "disabled", "authorization_url": target_path}

    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    code_verifier, code_challenge = generate_pkce_pair()
    redirect_uri = (request.query_params.get("redirect_uri") or "").strip() or _callback_url(request, settings)
    try:
        auth_url = build_authorization_url(
            settings,
            redirect_uri=redirect_uri,
            state=state,
            nonce=nonce,
            code_challenge=code_challenge,
        )
    except OidcError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc

    flow_payload = {
        "state": state,
        "nonce": nonce,
        "cv": code_verifier,
        "redirect_uri": redirect_uri,
        "return_to": target_path,
        "iat": int(time.time()),
    }
    signed = sign_flow_cookie(flow_payload, settings)
    secure = _cookie_secure(request, settings)
    if redirect:
        resp: Response = RedirectResponse(url=auth_url, status_code=302)
    else:
        resp = Response(
            content=__import__("json").dumps({"authorization_url": auth_url, "state": state}),
            media_type="application/json",
        )
    resp.set_cookie(
        key=FLOW_COOKIE,
        value=signed,
        max_age=600,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    return resp


@auth_router.get("/auth/callback")
def callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    db: Session = Depends(get_db),
):
    settings = get_settings()
    if error:
        raise HTTPException(401, f"OIDC sağlayıcı hatası: {error}")
    if not code or not state:
        raise HTTPException(400, "OIDC code ve state parametreleri gerekli")

    raw_flow = request.cookies.get(FLOW_COOKIE) or ""
    try:
        flow = verify_flow_cookie(raw_flow, settings)
    except OidcError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc

    if not hmac.compare_digest(str(flow.get("state") or ""), state):
        raise HTTPException(400, "OIDC state parametresi uyuşmuyor")

    redirect_uri = str(flow.get("redirect_uri") or _callback_url(request, settings))
    code_verifier = str(flow.get("cv") or "")
    nonce = str(flow.get("nonce") or "")
    return_to = _safe_return_to(flow.get("return_to"))

    try:
        tokens = exchange_code_for_tokens(
            settings,
            code=code,
            redirect_uri=redirect_uri,
            code_verifier=code_verifier,
        )
        id_token = str(tokens.get("id_token") or tokens.get("access_token") or "")
        if not id_token:
            raise OidcError("OIDC yanıtında id_token bulunamadı", 401)
        claims = verify_jwt_token(
            id_token,
            settings,
            expected_nonce=nonce if "id_token" in tokens else None,
        )
    except OidcError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc

    user = provision_or_update_user(db, claims, settings)
    raw_session_token, session = create_user_session(
        db,
        user,
        settings,
        id_token_hint=str(tokens.get("id_token") or ""),
    )
    secure = _cookie_secure(request, settings)
    ttl = max(300, int(settings.auth_session_ttl_seconds or 28800))
    resp = RedirectResponse(url=return_to, status_code=302)
    resp.delete_cookie(FLOW_COOKIE, path="/")
    resp.set_cookie(
        key=SESSION_COOKIE,
        value=raw_session_token,
        max_age=ttl,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    return resp


@auth_router.post("/auth/logout")
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    settings = get_settings()
    raw_cookie = (request.cookies.get(SESSION_COOKIE) or "").strip()
    end_session_url: str | None = None
    if raw_cookie:
        session = (
            db.query(AuthSession)
            .filter(AuthSession.token_hash == hash_token(raw_cookie))
            .one_or_none()
        )
        if session is not None:
            user = db.get(User, session.user_id)
            actor = user.email if user else f"user:{session.user_id}"
            audit(db, actor, "auth.logout", "user", str(session.user_id), {})
            id_token_hint = session.id_token_hint
            db.delete(session)
            db.commit()
            if (settings.auth_mode or "disabled").strip().lower() != "disabled":
                try:
                    doc = fetch_discovery(settings)
                    raw_end = str(doc.get("end_session_endpoint") or "").strip()
                    if raw_end:
                        pub = (settings.oidc_public_issuer_url or "").strip().rstrip("/")
                        internal = (settings.oidc_issuer_url or "").strip().rstrip("/")
                        if pub and internal and raw_end.startswith(internal):
                            raw_end = pub + raw_end[len(internal) :]
                        params = {}
                        if id_token_hint:
                            params["id_token_hint"] = id_token_hint
                            forwarded_proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip()
                            forwarded_host = (request.headers.get("x-forwarded-host") or "").split(",")[0].strip()
                            host = forwarded_host or request.headers.get("host") or ""
                            scheme = forwarded_proto or request.url.scheme or "http"
                            if host:
                                params["post_logout_redirect_uri"] = f"{scheme}://{host}/"
                        end_session_url = f"{raw_end}?{urllib.parse.urlencode(params)}" if params else raw_end
                except Exception:
                    end_session_url = None
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(FLOW_COOKIE, path="/")
    return {"ok": True, "end_session_url": end_session_url}


@auth_router.get("/auth/me")
def get_me(
    auth: tuple[Principal, AuthSession | None] = Depends(authenticate_request),
    db: Session = Depends(get_db),
):
    principal, session = auth
    return serialize_principal(db, principal, session, get_settings())


@auth_router.post("/auth/active-group")
def switch_active_group(
    body: SwitchGroupIn,
    auth: tuple[Principal, AuthSession | None] = Depends(authenticate_request),
    db: Session = Depends(get_db),
):
    principal, session = auth
    group = db.get(Group, body.group_id)
    if group is None:
        raise HTTPException(404, "grup yok")
    if not principal.is_admin and body.group_id not in principal.group_ids:
        raise HTTPException(403, "bu gruba erişim yetkiniz yok")
    if session is not None:
        session.active_group_id = group.id
        db.commit()
    user = db.get(User, principal.user_id) if principal.user_id else None
    if user is not None:
        updated = build_principal_for_user(db, user, active_group_id=group.id, auth_method=principal.auth_method)
    else:
        updated = Principal(
            user_id=principal.user_id,
            email=principal.email,
            display_name=principal.display_name,
            status=principal.status,
            is_admin=principal.is_admin,
            memberships=principal.memberships,
            active_group_id=group.id,
            auth_method=principal.auth_method,
        )
    return serialize_principal(db, updated, session, get_settings())


def _user_out(db: Session, row: User) -> dict:
    memberships = (
        db.query(GroupMembership, Group)
        .join(Group, GroupMembership.group_id == Group.id)
        .filter(GroupMembership.user_id == row.id)
        .order_by(Group.name)
        .all()
    )
    items = [
        {
            "membership_id": str(mem.id),
            "group_id": str(grp.id),
            "group_name": grp.name,
            "role": mem.role,
        }
        for mem, grp in memberships
    ]
    return {
        "id": str(row.id),
        "issuer": row.issuer,
        "sub": row.sub,
        "email": row.email,
        "display_name": row.display_name,
        "status": row.status,
        "is_admin": bool(row.is_admin),
        "groups": items,
        "memberships": items,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "last_login_at": row.last_login_at.isoformat() if row.last_login_at else None,
    }


def _group_out(db: Session, group: Group) -> dict:
    members = (
        db.query(GroupMembership, User)
        .join(User, GroupMembership.user_id == User.id)
        .filter(GroupMembership.group_id == group.id)
        .order_by(User.email)
        .all()
    )
    return {
        "id": str(group.id),
        "name": group.name,
        "description": group.description,
        "created_at": group.created_at.isoformat() if group.created_at else None,
        "member_count": len(members),
        "members": [
            {
                "membership_id": str(mem.id),
                "user_id": str(usr.id),
                "email": usr.email,
                "display_name": usr.display_name,
                "status": usr.status,
                "role": mem.role,
            }
            for mem, usr in members
        ],
    }


@auth_router.get("/admin/users")
def list_users(
    status: str | None = None,
    principal: Principal = Depends(require_permission("admin:users")),
    db: Session = Depends(get_db),
):
    query = db.query(User).order_by(User.created_at.desc())
    if status:
        query = query.filter(User.status == status)
    return [_user_out(db, row) for row in query.all()]


@auth_router.post("/admin/users/{user_id}/approve")
def approve_user(
    user_id: uuid.UUID,
    body: ApproveUserIn,
    principal: Principal = Depends(require_permission("admin:users")),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "kullanıcı yok")
    if body.role not in VALID_ROLES:
        raise HTTPException(400, "rol viewer, operator veya editor olmalı")
    group: Group | None = None
    if body.group_id is not None:
        group = db.get(Group, body.group_id)
        if group is None:
            raise HTTPException(404, "grup yok")
    else:
        group = ensure_default_group(db)

    user.status = "active"
    if body.is_admin:
        user.is_admin = True
    membership = (
        db.query(GroupMembership)
        .filter(GroupMembership.user_id == user.id, GroupMembership.group_id == group.id)
        .one_or_none()
    )
    if membership is None:
        membership = GroupMembership(user_id=user.id, group_id=group.id, role=body.role)
        db.add(membership)
    else:
        membership.role = body.role

    # Update any active sessions without an active_group_id
    db.query(AuthSession).filter(
        AuthSession.user_id == user.id,
        AuthSession.active_group_id.is_(None),
    ).update({AuthSession.active_group_id: group.id})

    audit(
        db,
        principal.actor,
        "user.approved",
        "user",
        str(user.id),
        {"email": user.email, "group": group.name, "role": body.role, "is_admin": user.is_admin},
    )
    db.commit()
    db.refresh(user)
    return _user_out(db, user)


@auth_router.post("/admin/users/{user_id}/reject")
def reject_user(
    user_id: uuid.UUID,
    body: RejectUserIn | None = None,
    principal: Principal = Depends(require_permission("admin:users")),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "kullanıcı yok")
    user.status = "rejected"
    db.query(AuthSession).filter(AuthSession.user_id == user.id).delete()
    audit(
        db,
        principal.actor,
        "user.rejected",
        "user",
        str(user.id),
        {"email": user.email, "reason": (body.reason if body else "")[:200]},
    )
    db.commit()
    db.refresh(user)
    return _user_out(db, user)


@auth_router.patch("/admin/users/{user_id}")
def patch_user(
    user_id: uuid.UUID,
    body: UserPatchIn,
    principal: Principal = Depends(require_permission("admin:users")),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "kullanıcı yok")
    changes: dict = {}
    if body.status is not None:
        if body.status not in VALID_STATUSES:
            raise HTTPException(400, "kullanıcı durumu pending, active, rejected veya disabled olmalı")
        user.status = body.status
        changes["status"] = body.status
        if body.status in {"rejected", "disabled"}:
            db.query(AuthSession).filter(AuthSession.user_id == user.id).delete()
    if body.is_admin is not None:
        user.is_admin = bool(body.is_admin)
        changes["is_admin"] = user.is_admin
    if body.display_name is not None:
        user.display_name = body.display_name.strip()[:200]
        changes["display_name"] = user.display_name
    audit(db, principal.actor, "user.updated", "user", str(user.id), {"email": user.email, **changes})
    db.commit()
    db.refresh(user)
    return _user_out(db, user)


@auth_router.get("/admin/groups")
def list_groups(
    principal: Principal = Depends(require_permission("admin:groups")),
    db: Session = Depends(get_db),
):
    ensure_default_group(db)
    db.commit()
    rows = db.query(Group).order_by(Group.name).all()
    return [_group_out(db, row) for row in rows]


@auth_router.post("/admin/groups", status_code=201)
def create_group(
    body: GroupIn,
    principal: Principal = Depends(require_permission("admin:groups")),
    db: Session = Depends(get_db),
):
    name = (body.name or "").strip()
    if not name or len(name) > 63 or any(ch.isspace() for ch in name):
        raise HTTPException(400, "grup adı 1-63 karakter olmalı ve boşluk içermemeli")
    if db.query(Group).filter(Group.name == name).first():
        raise HTTPException(409, "bu ada sahip bir grup var")
    group = Group(name=name, description=(body.description or "").strip()[:500])
    db.add(group)
    db.flush()
    audit(db, principal.actor, "group.created", "group", str(group.id), {"name": group.name})
    db.commit()
    db.refresh(group)
    return _group_out(db, group)


@auth_router.patch("/admin/groups/{group_id}")
def patch_group(
    group_id: uuid.UUID,
    body: GroupPatchIn,
    principal: Principal = Depends(require_permission("admin:groups")),
    db: Session = Depends(get_db),
):
    group = db.get(Group, group_id)
    if group is None:
        raise HTTPException(404, "grup yok")
    if body.description is not None:
        group.description = body.description.strip()[:500]
    audit(db, principal.actor, "group.updated", "group", str(group.id), {"name": group.name})
    db.commit()
    db.refresh(group)
    return _group_out(db, group)


@auth_router.delete("/admin/groups/{group_id}", status_code=204)
def delete_group(
    group_id: uuid.UUID,
    principal: Principal = Depends(require_permission("admin:groups")),
    db: Session = Depends(get_db),
):
    group = db.get(Group, group_id)
    if group is None:
        raise HTTPException(404, "grup yok")
    if group.name == "default":
        raise HTTPException(409, "varsayılan grup silinemez")
    audit(db, principal.actor, "group.deleted", "group", str(group.id), {"name": group.name})
    db.delete(group)
    db.commit()


@auth_router.post("/admin/groups/{group_id}/members", status_code=201)
def upsert_group_member(
    group_id: uuid.UUID,
    body: MembershipIn,
    principal: Principal = Depends(require_permission("admin:groups")),
    db: Session = Depends(get_db),
):
    group = db.get(Group, group_id)
    if group is None:
        raise HTTPException(404, "grup yok")
    user = db.get(User, body.user_id)
    if user is None:
        raise HTTPException(404, "kullanıcı yok")
    if body.role not in VALID_ROLES:
        raise HTTPException(400, "rol viewer, operator veya editor olmalı")
    membership = (
        db.query(GroupMembership)
        .filter(GroupMembership.user_id == user.id, GroupMembership.group_id == group.id)
        .one_or_none()
    )
    if membership is None:
        membership = GroupMembership(user_id=user.id, group_id=group.id, role=body.role)
        db.add(membership)
        action = "membership.added"
    else:
        membership.role = body.role
        action = "membership.updated"
    audit(
        db,
        principal.actor,
        action,
        "group",
        str(group.id),
        {"group": group.name, "user_id": str(user.id), "email": user.email, "role": body.role},
    )
    db.commit()
    db.refresh(group)
    return _group_out(db, group)


@auth_router.delete("/admin/groups/{group_id}/members/{user_id}", status_code=204)
def remove_group_member(
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    principal: Principal = Depends(require_permission("admin:groups")),
    db: Session = Depends(get_db),
):
    group = db.get(Group, group_id)
    if group is None:
        raise HTTPException(404, "grup yok")
    membership = (
        db.query(GroupMembership)
        .filter(GroupMembership.group_id == group.id, GroupMembership.user_id == user_id)
        .one_or_none()
    )
    if membership is None:
        raise HTTPException(404, "üyelik bulunamadı")
    user = db.get(User, user_id)
    audit(
        db,
        principal.actor,
        "membership.removed",
        "group",
        str(group.id),
        {"group": group.name, "user_id": str(user_id), "email": user.email if user else ""},
    )
    db.delete(membership)
    db.commit()


@auth_router.get("/admin/audit")
def list_audit_events(
    actor: str | None = None,
    action: str | None = None,
    entity_type: str | None = None,
    limit: int = 100,
    principal: Principal = Depends(require_permission("admin:audit")),
    db: Session = Depends(get_db),
):
    query = db.query(AuditEvent).order_by(AuditEvent.ts.desc())
    if actor:
        query = query.filter(AuditEvent.actor.ilike(f"%{actor}%"))
    if action:
        query = query.filter(AuditEvent.action.ilike(f"%{action}%"))
    if entity_type:
        query = query.filter(AuditEvent.entity_type == entity_type)
    rows = query.limit(min(max(limit, 1), 500)).all()
    return [
        {
            "id": str(row.id),
            "ts": row.ts.isoformat() if row.ts else None,
            "actor": row.actor,
            "action": row.action,
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
            "detail": row.detail or {},
        }
        for row in rows
    ]
