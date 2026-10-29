"""Secret provider records. The credential value is never a column."""

from __future__ import annotations

from control_plane.models import DataSourceRecord, DeliveryChannel, LlmProvider, SecretProvider


def secret_provider_out(row: SecretProvider) -> dict:
    return {
        "id": str(row.id),
        "name": row.name,
        "kind": row.kind,
        "base_url": row.base_url,
        "account": row.account or "",
        "auth_method": row.auth_method or "",
        "ca_bundle": row.ca_bundle or "",
        "config": row.config or {},
        "credential_secret_name": row.credential_secret_name or "",
        "credential_secret_key": row.credential_secret_key or "",
        "tls_cert_key": row.tls_cert_key or "",
        "tls_key_key": row.tls_key_key or "",
        "credential_namespace": row.credential_namespace or "",
        "enabled": bool(row.enabled),
        "owner_group_id": str(row.owner_group_id) if row.owner_group_id else None,
        "created_by": str(row.created_by) if row.created_by else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def apply_secret_provider(row: SecretProvider, body, *, creating: bool) -> None:
    from control_plane.service import ServiceError

    kind = (body.kind or "").strip()
    if kind not in {"conjur", "ccp", "vault"}:
        raise ServiceError("tür conjur, ccp veya vault olmalı", 400)
    if "PRIVATE KEY" in (body.ca_bundle or ""):
        raise ServiceError("özel anahtar CA alanına yazılmaz; Kubernetes Secret kullanın", 400)
    config = dict(body.config or {})
    for banned in ("api_key", "password", "token", "secret", "client_key", "private_key"):
        if config.get(banned):
            raise ServiceError("sağlayıcı sırrı kayda yazılmaz; Kubernetes Secret kullanın", 400)
    auth = (body.auth_method or "").strip()
    if kind == "conjur":
        auth = auth or "api-key"
        if auth not in {"api-key", "authn-k8s", "authn-jwt"}:
            raise ServiceError("Conjur kimliği api-key, authn-k8s veya authn-jwt olmalı", 400)
        if not (body.account or "").strip():
            raise ServiceError("Conjur hesap adı gerekli", 400)
        if not str(config.get("login") or "").strip():
            raise ServiceError("Conjur host kimliği (login) gerekli", 400)
        if auth == "api-key" and not (body.credential_secret_name or "").strip():
            raise ServiceError("Conjur API anahtarı için Kubernetes Secret adı gerekli", 400)
    elif kind == "ccp":
        auth = auth or "mtls"
        if auth not in {"mtls", "allowed-machines"}:
            raise ServiceError("CCP kimliği mtls veya allowed-machines olmalı", 400)
        if auth == "mtls":
            if not (body.credential_secret_name or "").strip():
                raise ServiceError("CCP sertifikası için Kubernetes Secret adı gerekli", 400)
            if not (body.tls_cert_key or "").strip() or not (body.tls_key_key or "").strip():
                raise ServiceError("CCP sertifika ve anahtar adları gerekli", 400)
    else:
        auth = auth or "token"
    if not (body.base_url or "").strip():
        raise ServiceError("adres gerekli", 400)
    if creating:
        row.name = body.name.strip()
    row.kind = kind
    row.base_url = body.base_url.strip().rstrip("/")
    row.account = (body.account or "").strip()
    row.auth_method = auth
    row.ca_bundle = body.ca_bundle or ""
    row.config = config
    row.credential_secret_name = (body.credential_secret_name or "").strip()
    row.credential_secret_key = (body.credential_secret_key or "").strip() or "api_key"
    row.tls_cert_key = (body.tls_cert_key or "").strip()
    row.tls_key_key = (body.tls_key_key or "").strip()
    row.credential_namespace = (body.credential_namespace or "").strip()
    row.enabled = bool(body.enabled)


def provider_in_use(db, provider_id) -> bool:
    sources = db.query(DataSourceRecord).filter(DataSourceRecord.secret_provider_id == provider_id).count()
    models = db.query(LlmProvider).filter(LlmProvider.secret_provider_id == provider_id).count()
    channels = db.query(DeliveryChannel).filter(DeliveryChannel.secret_provider_id == provider_id).count()
    return bool(sources or models or channels)
