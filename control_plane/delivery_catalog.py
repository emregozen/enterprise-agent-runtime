"""Delivery channels. The API returns a hint, never the credential."""

from __future__ import annotations

import json
import uuid

from sqlalchemy.orm import Session

from control_plane.models import DeliveryChannel
from delivery.policy import reject_recipients
from delivery.send import DEFAULT_HTTP_TEMPLATE, test_recipient
from shared.crypto import decrypt_secret, encrypt_secret, public_hint, secret_hint
from shared.spec import _EMAIL


def channel_out(row: DeliveryChannel) -> dict:
    from secret_sources.resolve import effective_backend

    backend = effective_backend(row, "credential_ciphertext")
    hint = public_hint(row.credential_ciphertext, row.credential_hint)
    configured = _credential_configured(row, backend)
    if configured and not hint:
        hint = "••••"
    return {
        "id": str(row.id),
        "name": row.name,
        "kind": row.kind,
        "enabled": row.enabled,
        "from_address": row.from_address,
        "from_name": row.from_name,
        "allow_domains": list(row.allow_domains or []),
        "max_attachment_bytes": row.max_attachment_bytes,
        "secret_backend": backend,
        "secret_provider_id": str(row.secret_provider_id) if row.secret_provider_id else None,
        "secret_path": row.secret_path or "",
        "secret_ref": row.secret_ref or {},
        "k8s_secret_name": row.k8s_secret_name,
        "k8s_secret_key": row.k8s_secret_key,
        "credential_set": configured,
        "credential_hint": hint,
        "config": _public_config(row),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def apply_channel(db: Session, row: DeliveryChannel, body, *, creating: bool) -> None:
    from control_plane.service import ServiceError

    kind = (body.kind or "").strip()
    if kind not in {"smtp", "http"}:
        raise ServiceError("tür smtp veya http olmalı", 400)
    address = (body.from_address or "").strip().lower()
    if not _EMAIL.match(address):
        raise ServiceError("gönderen adresi geçersiz", 400)
    domains = _domains(body.allow_domains)
    if not domains:
        raise ServiceError("alıcı izin listesi boş", 400)
    limit = int(body.max_attachment_bytes or 0)
    if limit < 1 or limit > 50_000_000:
        raise ServiceError("ek boyutu sınırı geçersiz", 400)
    config = _config(kind, body.config or {})
    if creating:
        row.name = body.name.strip()
    row.kind = kind
    row.enabled = bool(body.enabled)
    row.from_address = address
    row.from_name = (body.from_name or "").strip()[:120]
    row.allow_domains = domains
    row.max_attachment_bytes = limit
    row.config = config
    _assign_secret(db, row, body, creating=creating)


def assert_spec_delivery(db: Session, spec: dict) -> None:
    from control_plane.service import ServiceError

    targets = (spec.get("spec") or {}).get("delivery") or []
    for target in targets:
        name = str(target.get("channel") or "").strip()
        recipients = list(target.get("to") or [])
        copied = list(target.get("cc") or [])
        if not name:
            raise ServiceError("teslimat kanalı seçilmedi", 400)
        if not recipients:
            raise ServiceError("en az bir alıcı gerekli", 400)
        channel = db.query(DeliveryChannel).filter(DeliveryChannel.name == name).one_or_none()
        if channel is None or not channel.enabled:
            raise ServiceError("teslimat kanalı yok veya kapalı", 400)
        blocked = reject_recipients(recipients + copied, list(channel.allow_domains or []))
        if blocked:
            raise ServiceError("alıcı izin verilen etki alanında değil", 400)


def resolve_credential(db: Session, row: DeliveryChannel) -> str:
    from control_plane.service import ServiceError
    from secret_sources.errors import SecretProviderError
    from secret_sources.resolve import effective_backend, fetch_provider_secret, resolve_kubernetes_value

    backend = effective_backend(row, "credential_ciphertext")
    if backend == "db":
        return decrypt_secret(row.credential_ciphertext) if row.credential_ciphertext else ""
    try:
        if backend == "kubernetes":
            from shared.config import get_settings

            settings = get_settings()
            return resolve_kubernetes_value(
                row.k8s_secret_name or "",
                row.k8s_secret_key or "password",
                [settings.secret_namespace, settings.run_namespace],
            )
        return fetch_provider_secret(db, row.secret_provider_id, row.secret_path or "", row.secret_ref or {})
    except SecretProviderError as exc:
        raise ServiceError(str(exc), 502) from exc


def probe_channel(db: Session, row: DeliveryChannel) -> dict:
    from delivery.send import send_test

    return send_test(db, row, test_recipient(row))


def _credential_configured(row: DeliveryChannel, backend: str) -> bool:
    if backend == "kubernetes":
        return bool(row.k8s_secret_name)
    if backend == "conjur":
        return bool(row.secret_provider_id and (row.secret_path or "").strip())
    if backend == "ccp":
        ref = row.secret_ref or {}
        return bool(row.secret_provider_id and (ref.get("object") or ref.get("query")))
    return bool(row.credential_ciphertext)


def _public_config(row: DeliveryChannel) -> dict:
    config = dict(row.config or {})
    if row.kind == "http" and not config.get("body_template"):
        config["body_template"] = DEFAULT_HTTP_TEMPLATE
    return config


def _domains(value) -> list[str]:
    if isinstance(value, str):
        parts = [item.strip() for item in value.split(",")]
    else:
        parts = [str(item).strip() for item in (value or [])]
    cleaned = []
    for item in parts:
        domain = item.lower().lstrip("@")
        if domain and domain not in cleaned:
            cleaned.append(domain)
    return cleaned


def _config(kind: str, raw: dict) -> dict:
    from control_plane.service import ServiceError

    if kind == "smtp":
        tls_mode = str(raw.get("tls_mode") or "starttls")
        if tls_mode not in {"none", "starttls", "ssl"}:
            raise ServiceError("TLS biçimi none, starttls veya ssl olmalı", 400)
        port = int(raw.get("port") or (465 if tls_mode == "ssl" else 587))
        if port < 1 or port > 65535:
            raise ServiceError("SMTP portu geçersiz", 400)
        timeout = float(raw.get("timeout_seconds") or 20)
        host = str(raw.get("host") or "").strip()
        if not host:
            raise ServiceError("SMTP sunucusu gerekli", 400)
        return {
            "host": host,
            "port": port,
            "tls_mode": tls_mode,
            "username": str(raw.get("username") or "").strip(),
            "timeout_seconds": min(max(timeout, 1), 120),
        }
    auth = str(raw.get("auth") or "none")
    if auth not in {"none", "bearer", "basic", "header"}:
        raise ServiceError("kimlik doğrulama none, bearer, basic veya header olmalı", 400)
    method = str(raw.get("method") or "POST").upper()
    if method not in {"POST", "PUT", "PATCH"}:
        raise ServiceError("HTTP yöntemi POST, PUT veya PATCH olmalı", 400)
    headers = raw.get("headers") or {}
    if isinstance(headers, str):
        try:
            headers = json.loads(headers or "{}")
        except json.JSONDecodeError as exc:
            raise ServiceError("başlıklar JSON olmalı", 400) from exc
    if not isinstance(headers, dict):
        raise ServiceError("başlıklar JSON olmalı", 400)
    codes = raw.get("success_codes") or [200, 201, 202]
    if isinstance(codes, str):
        codes = [int(item) for item in codes.replace(" ", "").split(",") if item]
    codes = [int(item) for item in codes]
    if not codes or any(code < 100 or code > 599 for code in codes):
        raise ServiceError("başarı durum kodu geçersiz", 400)
    timeout = float(raw.get("timeout_seconds") or 20)
    template = str(raw.get("body_template") or DEFAULT_HTTP_TEMPLATE)
    url = str(raw.get("url") or "").strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        raise ServiceError("teslimat adresi gerekli", 400)
    return {
        "url": url,
        "method": method,
        "headers": {str(key): str(value) for key, value in headers.items()},
        "auth": auth,
        "username": str(raw.get("username") or "").strip(),
        "header_name": str(raw.get("header_name") or "").strip(),
        "success_codes": codes,
        "timeout_seconds": min(max(timeout, 1), 120),
        "body_template": template,
    }


def _assign_secret(db: Session, row: DeliveryChannel, body, *, creating: bool) -> None:
    from control_plane.catalog import _provider_or_error
    from control_plane.service import ServiceError

    incoming = (getattr(body, "password", None) or "").strip()
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
        if incoming:
            row.credential_ciphertext = encrypt_secret(incoming)
            row.credential_hint = secret_hint(incoming)
        elif creating:
            row.credential_ciphertext = ""
            row.credential_hint = ""
        return
    row.credential_ciphertext = ""
    row.credential_hint = ""
    row.k8s_secret_name = None
    row.k8s_secret_key = None
    row.secret_provider_id = None
    row.secret_path = ""
    row.secret_ref = {}
    if backend == "kubernetes":
        name = (body.k8s_secret_name or "").strip()
        if not name:
            raise ServiceError("Kubernetes Secret adı gerekli", 400)
        row.k8s_secret_name = name
        row.k8s_secret_key = (body.k8s_secret_key or "").strip() or "password"
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
    if not (ref.get("object") or ref.get("query")):
        raise ServiceError("CCP Object veya Query gerekli", 400)
    if not ref.get("app_id"):
        raise ServiceError("CCP AppID gerekli", 400)
    row.secret_ref = ref


def log_out(row) -> dict:
    return {
        "id": str(row.id),
        "run_id": str(row.run_id),
        "channel_id": str(row.channel_id) if row.channel_id else None,
        "channel_name": row.channel_name,
        "recipients": row.recipients or {},
        "subject": row.subject,
        "status": row.status,
        "error": row.error,
        "detail": {key: value for key, value in (row.detail or {}).items() if key != "target"},
        "content": (row.detail or {}).get("content") or (row.detail or {}).get("target", {}).get("content"),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def new_id() -> uuid.UUID:
    return uuid.uuid4()
