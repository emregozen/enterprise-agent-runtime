"""OIDC authentication, PKCE BFF session management, and JWKS JWT verification."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa, utils as asym_utils
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from control_plane.db import get_db
from control_plane.migrate import DEFAULT_GROUP_ID, DEFAULT_GROUP_NAME
from control_plane.models import AuthSession, Group, GroupMembership, User, utcnow
from control_plane.rbac import (
    VALID_ROLES,
    GroupMembershipInfo,
    Principal,
    allowed_group_ids_for,
    can_access_record,
    has_permission,
    permitted_actions,
)
from control_plane.service import audit, hash_token
from shared.config import Settings, get_settings

log = logging.getLogger("control-plane.auth")

SESSION_COOKIE = "agentrt_session"
FLOW_COOKIE = "agentrt_oidc_flow"
CSRF_HEADER = "X-CSRF-Token"

_discovery_cache: dict[str, tuple[float, dict]] = {}
_jwks_cache: dict[str, tuple[float, dict]] = {}


class OidcError(Exception):
    def __init__(self, message: str, status_code: int = 401):
        super().__init__(message)
        self.status_code = status_code


def clear_oidc_caches() -> None:
    _discovery_cache.clear()
    _jwks_cache.clear()


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    padded = text + "=" * ((4 - len(text) % 4) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def generate_pkce_pair() -> tuple[str, str]:
    verifier = _b64url_encode(secrets.token_bytes(32))
    challenge = _b64url_encode(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def _signing_key(settings: Settings) -> bytes:
    raw = (settings.config_master_key or "dev-only-master-key").strip()
    return hashlib.sha256(f"oidc-flow:{raw}".encode("utf-8")).digest()


def sign_flow_cookie(payload: dict, settings: Settings) -> str:
    body = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = _b64url_encode(hmac.new(_signing_key(settings), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify_flow_cookie(cookie_value: str, settings: Settings, max_age_seconds: int = 600) -> dict:
    if not cookie_value or "." not in cookie_value:
        raise OidcError("OIDC oturum durumu bulunamadı veya süresi doldu", 400)
    body, sig = cookie_value.split(".", 1)
    expected = _b64url_encode(hmac.new(_signing_key(settings), body.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        raise OidcError("OIDC oturum imzası geçersiz", 400)
    try:
        data = json.loads(_b64url_decode(body).decode("utf-8"))
    except Exception as exc:
        raise OidcError("OIDC oturum verisi okunamadı", 400) from exc
    issued_at = float(data.get("iat") or 0)
    if time.time() - issued_at > max_age_seconds:
        raise OidcError("OIDC giriş isteğinin süresi doldu", 400)
    return data


def resolve_oidc_client_secret(settings: Settings) -> str:
    """Resolve OIDC client secret from env or Kubernetes Secret. Never log the value."""
    if (settings.oidc_client_secret or "").strip():
        return settings.oidc_client_secret.strip()
    if (settings.oidc_k8s_secret_name or "").strip():
        from secret_sources.resolve import resolve_kubernetes_value

        return resolve_kubernetes_value(
            settings.oidc_k8s_secret_name.strip(),
            (settings.oidc_k8s_secret_key or "client_secret").strip(),
            [settings.secret_namespace, settings.run_namespace],
        )
    return ""


def _http_verify(settings: Settings) -> bool | str:
    if not settings.oidc_verify_tls:
        return False
    if (settings.oidc_ca_bundle or "").strip():
        from secret_sources.tls import ca_bundle_path

        path = ca_bundle_path(settings.oidc_ca_bundle)
        if path:
            return path
    return True


def fetch_discovery(settings: Settings) -> dict:
    issuer = (settings.oidc_issuer_url or "").strip().rstrip("/")
    if not issuer:
        raise OidcError("OIDC issuer adresi tanımlı değil", 500)
    now = time.monotonic()
    cached = _discovery_cache.get(issuer)
    if cached and now - cached[0] < 300:
        return cached[1]
    url = f"{issuer}/.well-known/openid-configuration"
    try:
        resp = httpx.get(url, timeout=10, verify=_http_verify(settings))
        resp.raise_for_status()
        doc = resp.json()
    except Exception as exc:
        raise OidcError("OIDC kimlik sağlayıcısına ulaşılamadı", 502) from exc
    _discovery_cache[issuer] = (now, doc)
    return doc


def fetch_jwks(settings: Settings, jwks_uri: str | None = None, *, force: bool = False) -> dict:
    uri = jwks_uri
    if not uri:
        doc = fetch_discovery(settings)
        uri = str(doc.get("jwks_uri") or "").strip()
    if not uri:
        raise OidcError("OIDC JWKS adresi bulunamadı", 502)
    now = time.monotonic()
    cached = _jwks_cache.get(uri)
    if cached and not force and now - cached[0] < 300:
        return cached[1]
    try:
        resp = httpx.get(uri, timeout=10, verify=_http_verify(settings))
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        raise OidcError("OIDC JWKS anahtarları alınamadı", 502) from exc
    _jwks_cache[uri] = (now, data)
    return data


def build_authorization_url(
    settings: Settings,
    *,
    redirect_uri: str,
    state: str,
    nonce: str,
    code_challenge: str,
) -> str:
    doc = fetch_discovery(settings)
    auth_endpoint = str(doc.get("authorization_endpoint") or "").strip()
    if not auth_endpoint:
        raise OidcError("OIDC authorization_endpoint eksik", 502)
    public_issuer = (settings.oidc_public_issuer_url or "").strip().rstrip("/")
    internal_issuer = (settings.oidc_issuer_url or "").strip().rstrip("/")
    if public_issuer and internal_issuer and auth_endpoint.startswith(internal_issuer):
        auth_endpoint = public_issuer + auth_endpoint[len(internal_issuer) :]
    params = {
        "response_type": "code",
        "client_id": settings.oidc_client_id,
        "redirect_uri": redirect_uri,
        "scope": settings.oidc_scopes or "openid profile email",
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{auth_endpoint}?{urllib.parse.urlencode(params)}"


def exchange_code_for_tokens(
    settings: Settings,
    *,
    code: str,
    redirect_uri: str,
    code_verifier: str,
) -> dict:
    doc = fetch_discovery(settings)
    token_endpoint = str(doc.get("token_endpoint") or "").strip()
    if not token_endpoint:
        raise OidcError("OIDC token_endpoint eksik", 502)
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": settings.oidc_client_id,
        "code_verifier": code_verifier,
    }
    client_secret = resolve_oidc_client_secret(settings)
    if client_secret:
        data["client_secret"] = client_secret
    try:
        resp = httpx.post(
            token_endpoint,
            data=data,
            headers={"Accept": "application/json"},
            timeout=15,
            verify=_http_verify(settings),
        )
    except Exception as exc:
        raise OidcError("OIDC token servisine ulaşılamadı", 502) from exc
    if resp.status_code >= 400:
        raise OidcError("OIDC yetkilendirme kodu reddedildi", 401)
    try:
        return resp.json()
    except Exception as exc:
        raise OidcError("OIDC token yanıtı geçersiz", 502) from exc


def _jwk_to_public_key(jwk: dict):
    kty = jwk.get("kty")
    if kty == "RSA":
        n = int.from_bytes(_b64url_decode(jwk["n"]), "big")
        e = int.from_bytes(_b64url_decode(jwk["e"]), "big")
        return rsa.RSAPublicNumbers(e, n).public_key()
    if kty == "EC":
        crv_name = jwk.get("crv", "P-256")
        curve = ec.SECP256R1() if crv_name == "P-256" else ec.SECP384R1() if crv_name == "P-384" else ec.SECP521R1()
        x = int.from_bytes(_b64url_decode(jwk["x"]), "big")
        y = int.from_bytes(_b64url_decode(jwk["y"]), "big")
        return ec.EllipticCurvePublicNumbers(x, y, curve).public_key()
    raise OidcError(f"Desteklenmeyen JWK anahtar türü: {kty}", 401)


def _verify_jws_signature(alg: str, public_key, signing_input: bytes, signature: bytes) -> None:
    hash_map = {
        "RS256": hashes.SHA256(),
        "RS384": hashes.SHA384(),
        "RS512": hashes.SHA512(),
        "ES256": hashes.SHA256(),
        "ES384": hashes.SHA384(),
        "ES512": hashes.SHA512(),
    }
    hash_alg = hash_map.get(alg)
    if hash_alg is None:
        raise OidcError(f"Desteklenmeyen JWT imzalama algoritması: {alg}", 401)
    try:
        if alg.startswith("RS"):
            public_key.verify(signature, signing_input, padding.PKCS1v15(), hash_alg)
        elif alg.startswith("ES"):
            half = len(signature) // 2
            r = int.from_bytes(signature[:half], "big")
            s = int.from_bytes(signature[half:], "big")
            der_sig = asym_utils.encode_dss_signature(r, s)
            public_key.verify(der_sig, signing_input, ec.ECDSA(hash_alg))
        else:
            raise OidcError("Geçersiz JWT algoritması", 401)
    except OidcError:
        raise
    except Exception as exc:
        raise OidcError("JWT imzası doğrulanamadı", 401) from exc


def verify_jwt_token(
    token: str,
    settings: Settings,
    *,
    expected_nonce: str | None = None,
    require_audience: bool = True,
) -> dict:
    parts = (token or "").strip().split(".")
    if len(parts) != 3:
        raise OidcError("Geçersiz JWT biçimi", 401)
    header_b64, payload_b64, sig_b64 = parts
    try:
        header = json.loads(_b64url_decode(header_b64).decode("utf-8"))
        claims = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
        signature = _b64url_decode(sig_b64)
    except Exception as exc:
        raise OidcError("JWT çözümlenemedi", 401) from exc

    alg = str(header.get("alg") or "")
    kid = header.get("kid")
    jwks = fetch_jwks(settings)
    keys = jwks.get("keys") or []
    matching = [k for k in keys if not kid or k.get("kid") == kid]
    if not matching and kid:
        jwks = fetch_jwks(settings, force=True)
        keys = jwks.get("keys") or []
        matching = [k for k in keys if k.get("kid") == kid]
    if not matching:
        raise OidcError("JWT imzalayan anahtar JWKS içinde bulunamadı", 401)

    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    verified = False
    last_err: OidcError | None = None
    for jwk in matching:
        try:
            pub = _jwk_to_public_key(jwk)
            _verify_jws_signature(alg, pub, signing_input, signature)
            verified = True
            break
        except OidcError as err:
            last_err = err
    if not verified:
        raise last_err or OidcError("JWT imzası geçersiz", 401)

    now = time.time()
    exp = claims.get("exp")
    if exp is None or float(exp) < now - 30:
        raise OidcError("JWT süresi dolmuş", 401)
    nbf = claims.get("nbf")
    if nbf is not None and float(nbf) > now + 30:
        raise OidcError("JWT henüz geçerli değil", 401)

    allowed_issuers = {
        u.strip().rstrip("/")
        for u in (settings.oidc_issuer_url, settings.oidc_public_issuer_url)
        if (u or "").strip()
    }
    token_iss = str(claims.get("iss") or "").strip().rstrip("/")
    if allowed_issuers and token_iss not in allowed_issuers:
        raise OidcError("JWT issuer uyuşmuyor", 401)

    if require_audience and (settings.oidc_client_id or "").strip():
        aud = claims.get("aud")
        azp = claims.get("azp")
        aud_list = [aud] if isinstance(aud, str) else list(aud or [])
        if settings.oidc_client_id not in aud_list and azp != settings.oidc_client_id:
            raise OidcError("JWT audience uyuşmuyor", 401)

    if expected_nonce is not None:
        if claims.get("nonce") != expected_nonce:
            raise OidcError("OIDC nonce uyuşmuyor", 401)

    if not claims.get("sub"):
        raise OidcError("JWT sub alanı eksik", 401)

    return claims


def ensure_default_group(db: Session) -> Group:
    row = db.query(Group).filter(Group.name == DEFAULT_GROUP_NAME).one_or_none()
    if row is not None:
        return row
    row = Group(
        id=DEFAULT_GROUP_ID,
        name=DEFAULT_GROUP_NAME,
        description="Default group for existing and initial resources",
    )
    db.add(row)
    db.flush()
    return row


def provision_or_update_user(db: Session, claims: dict, settings: Settings) -> User:
    issuer = str(claims.get("iss") or settings.oidc_issuer_url or "oidc").strip().rstrip("/")
    sub = str(claims["sub"]).strip()
    email_claim = (settings.oidc_email_claim or "email").strip()
    name_claim = (settings.oidc_name_claim or "name").strip()
    raw_email = str(claims.get(email_claim) or claims.get("preferred_username") or "").strip().lower()
    display_name = str(
        claims.get(name_claim)
        or claims.get("preferred_username")
        or raw_email
        or sub
    ).strip()[:200]
    email = (raw_email or f"{sub}@oidc.local")[:320]

    default_group = ensure_default_group(db)
    bootstrap_admins = settings.bootstrap_admin_emails()
    is_bootstrap = bool(email and email in bootstrap_admins)

    user = db.query(User).filter(User.issuer == issuer, User.sub == sub).one_or_none()
    creating = False
    if user is None:
        creating = True
        user = User(
            issuer=issuer,
            sub=sub,
            email=email,
            display_name=display_name,
            status="active" if is_bootstrap else "pending",
            is_admin=is_bootstrap,
            last_login_at=utcnow(),
        )
        db.add(user)
        db.flush()
        if is_bootstrap:
            _ensure_membership(db, user.id, default_group.id, "editor")
    else:
        user.email = email
        if display_name:
            user.display_name = display_name
        user.last_login_at = utcnow()
        if is_bootstrap and not user.is_admin:
            user.is_admin = True
            if user.status == "pending":
                user.status = "active"
            _ensure_membership(db, user.id, default_group.id, "editor")

    if settings.oidc_group_mapping_enabled:
        _apply_idp_group_mapping(db, user, claims, settings)

    action = "auth.user_registered" if creating else "auth.login"
    audit(
        db,
        user.email or f"user:{user.id}",
        action,
        "user",
        str(user.id),
        {"email": user.email, "status": user.status, "is_admin": user.is_admin},
    )
    db.commit()
    db.refresh(user)
    return user


def _ensure_membership(db: Session, user_id: uuid.UUID, group_id: uuid.UUID, role: str) -> GroupMembership:
    role_clean = role if role in VALID_ROLES else "viewer"
    existing = (
        db.query(GroupMembership)
        .filter(GroupMembership.user_id == user_id, GroupMembership.group_id == group_id)
        .one_or_none()
    )
    if existing is None:
        existing = GroupMembership(user_id=user_id, group_id=group_id, role=role_clean)
        db.add(existing)
        db.flush()
    return existing


def _apply_idp_group_mapping(db: Session, user: User, claims: dict, settings: Settings) -> None:
    mapping = settings.parsed_group_mapping()
    if not mapping:
        return
    claim_name = (settings.oidc_groups_claim or "groups").strip()
    raw_groups = claims.get(claim_name)
    if isinstance(raw_groups, str):
        idp_groups = [raw_groups]
    elif isinstance(raw_groups, list):
        idp_groups = [str(item) for item in raw_groups]
    else:
        return
    matched_any = False
    for idp_group in idp_groups:
        target = mapping.get(idp_group)
        if not target:
            continue
        group_name = target["group"]
        role = target["role"] if target["role"] in VALID_ROLES else "viewer"
        group = db.query(Group).filter(Group.name == group_name).one_or_none()
        if group is None:
            group = Group(name=group_name[:63], description=f"Mapped from IdP group {idp_group}")
            db.add(group)
            db.flush()
        _ensure_membership(db, user.id, group.id, role)
        matched_any = True
    if matched_any and user.status == "pending":
        user.status = "active"


def create_user_session(db: Session, user: User, settings: Settings, id_token_hint: str = "") -> tuple[str, AuthSession]:
    raw_token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(24)
    memberships = (
        db.query(GroupMembership)
        .filter(GroupMembership.user_id == user.id)
        .order_by(GroupMembership.created_at)
        .all()
    )
    active_group_id = memberships[0].group_id if memberships else None
    if active_group_id is None and user.is_admin:
        default_group = ensure_default_group(db)
        active_group_id = default_group.id
    ttl = max(300, int(settings.auth_session_ttl_seconds or 28800))
    session = AuthSession(
        user_id=user.id,
        token_hash=hash_token(raw_token),
        csrf_token=csrf_token,
        active_group_id=active_group_id,
        id_token_hint=id_token_hint or "",
        expires_at=utcnow() + timedelta(seconds=ttl),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return raw_token, session


def build_principal_for_user(
    db: Session,
    user: User,
    *,
    active_group_id: uuid.UUID | None = None,
    auth_method: str = "session",
) -> Principal:
    rows = (
        db.query(GroupMembership, Group)
        .join(Group, GroupMembership.group_id == Group.id)
        .filter(GroupMembership.user_id == user.id)
        .order_by(Group.name)
        .all()
    )
    memberships = tuple(
        GroupMembershipInfo(group_id= grp.id, group_name=grp.name, role=mem.role)
        for mem, grp in rows
    )
    member_ids = {m.group_id for m in memberships}
    effective_group = active_group_id
    if effective_group is not None and not user.is_admin and effective_group not in member_ids:
        effective_group = None
    if effective_group is None:
        if memberships:
            effective_group = memberships[0].group_id
        elif user.is_admin:
            default_grp = ensure_default_group(db)
            effective_group = default_grp.id
    return Principal(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name or user.email,
        status=user.status,
        is_admin=bool(user.is_admin),
        memberships=memberships,
        active_group_id=effective_group,
        auth_method=auth_method,
    )


def _disabled_mode_principal(db: Session, request: Request | None = None) -> Principal:
    default_grp = ensure_default_group(db)
    db.commit()
    requested_group: uuid.UUID | None = None
    if request is not None:
        header_gid = (request.headers.get("X-Active-Group") or "").strip()
        if header_gid:
            try:
                requested_group = uuid.UUID(header_gid)
            except ValueError:
                requested_group = None
    return Principal(
        user_id=None,
        email="local-dev@agent-runtime.local",
        display_name="Local Operator",
        status="active",
        is_admin=True,
        memberships=(GroupMembershipInfo(group_id=default_grp.id, group_name=default_grp.name, role="editor"),),
        active_group_id=requested_group or default_grp.id,
        auth_method="disabled",
    )


def authenticate_request(
    request: Request,
    db: Session = Depends(get_db),
) -> tuple[Principal, AuthSession | None]:
    settings = get_settings()
    mode = (settings.auth_mode or "disabled").strip().lower()
    if mode == "disabled":
        return _disabled_mode_principal(db, request), None

    # 1. Check Bearer JWT header for API automation
    auth_header = (request.headers.get("Authorization") or "").strip()
    if auth_header.lower().startswith("bearer "):
        jwt_token = auth_header.split(" ", 1)[1].strip()
        try:
            claims = verify_jwt_token(jwt_token, settings)
        except OidcError as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc
        user = provision_or_update_user(db, claims, settings)
        requested_group = _requested_group_header(request)
        return build_principal_for_user(db, user, active_group_id=requested_group, auth_method="bearer"), None

    # 2. Check session cookie (BFF flow)
    raw_cookie = (request.cookies.get(SESSION_COOKIE) or "").strip()
    if not raw_cookie:
        raise HTTPException(401, "oturum açmanız gerekiyor")
    session = (
        db.query(AuthSession)
        .filter(AuthSession.token_hash == hash_token(raw_cookie))
        .one_or_none()
    )
    if session is None:
        raise HTTPException(401, "oturum geçersiz veya süresi dolmuş")
    now = utcnow()
    expires = session.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires <= now:
        db.delete(session)
        db.commit()
        raise HTTPException(401, "oturum süresi doldu")

    user = db.get(User, session.user_id)
    if user is None:
        raise HTTPException(401, "kullanıcı bulunamadı")

    # Enforce CSRF protection on state-mutating requests when using session cookies
    if request.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
        csrf_header = (request.headers.get(CSRF_HEADER) or "").strip()
        if not csrf_header or not hmac.compare_digest(csrf_header, session.csrf_token):
            raise HTTPException(403, "CSRF doğrulaması başarısız")

    requested_group = _requested_group_header(request) or session.active_group_id
    return build_principal_for_user(db, user, active_group_id=requested_group, auth_method="session"), session


def _requested_group_header(request: Request) -> uuid.UUID | None:
    raw = (request.headers.get("X-Active-Group") or "").strip()
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        return None


def get_current_principal(
    auth: tuple[Principal, AuthSession | None] = Depends(authenticate_request),
) -> Principal:
    """Return authenticated principal regardless of pending/active status (used by /api/auth/me)."""
    principal, _session = auth
    return principal


def get_active_principal(
    auth: tuple[Principal, AuthSession | None] = Depends(authenticate_request),
) -> Principal:
    """Require an active user who belongs to at least one group (or is platform admin)."""
    principal, _session = auth
    if principal.status == "pending":
        raise HTTPException(403, "hesabınız yönetici onayı bekliyor")
    if principal.status == "rejected":
        raise HTTPException(403, "hesap başvurunuz reddedildi")
    if principal.status == "disabled":
        raise HTTPException(403, "hesabınız devre dışı bırakıldı")
    if principal.status != "active":
        raise HTTPException(403, "hesabınız aktif değil")
    if not principal.is_admin and not principal.memberships:
        raise HTTPException(403, "henüz bir gruba atanmadınız; yönetici onayı bekleniyor")
    return principal


def require_permission(permission: str):
    """FastAPI dependency factory enforcing a permission from the RBAC matrix."""

    def _dep(principal: Principal = Depends(get_active_principal)) -> Principal:
        if not has_permission(principal, permission):
            raise HTTPException(403, "bu işlem için yetkiniz yok")
        return principal

    return _dep


def ensure_record_access(
    principal: Principal,
    owner_group_id: uuid.UUID | None,
    action: str,
    not_found_detail: str,
) -> None:
    """Return 404 if the user is not in the record's group; 403 if in the group without the required role."""
    if not can_access_record(principal, owner_group_id, "agent:read"):
        raise HTTPException(404, not_found_detail)
    if not can_access_record(principal, owner_group_id, action):
        raise HTTPException(403, "bu işlem için yetkiniz yok")


def effective_write_group_id(principal: Principal, action: str) -> uuid.UUID:
    """Resolve the active group ID for creating a resource and verify write permission in that group."""
    gid = principal.effective_group_id()
    if gid is None:
        if principal.is_admin:
            gid = DEFAULT_GROUP_ID
        else:
            raise HTTPException(403, "aktif grup seçilmedi")
    if not has_permission(principal, action, group_id=gid):
        raise HTTPException(403, "bu işlem için yetkiniz yok")
    return gid


def serialize_principal(db: Session, principal: Principal, session: AuthSession | None, settings: Settings) -> dict:
    groups_out = [
        {"id": str(m.group_id), "name": m.group_name, "role": m.role}
        for m in principal.memberships
    ]
    if principal.is_admin:
        # Include all platform groups so admins can switch or inspect any group
        member_map = {m.group_id: m.role for m in principal.memberships}
        all_groups = db.query(Group).order_by(Group.name).all()
        groups_out = [
            {"id": str(g.id), "name": g.name, "role": member_map.get(g.id, "admin")}
            for g in all_groups
        ]
    effective_gid = principal.effective_group_id()
    return {
        "auth_mode": (settings.auth_mode or "disabled").strip().lower(),
        "authenticated": True,
        "user": {
            "id": str(principal.user_id) if principal.user_id else None,
            "email": principal.email,
            "display_name": principal.display_name,
            "status": principal.status,
            "is_admin": principal.is_admin,
        },
        "groups": groups_out,
        "active_group_id": str(effective_gid) if effective_gid else None,
        "permissions": permitted_actions(principal, group_id=effective_gid),
        "csrf_token": session.csrf_token if session else None,
    }
