"""Resolve a datasource password or an LLM API key at run start.

The database stores a reference. The value lives only in this process, then in
the per-run Secret. Provider credentials themselves are read from a Kubernetes
Secret in the control-plane namespace.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from secret_sources.cache import cache_get, cache_put
from secret_sources.errors import SecretProviderError
from secret_sources.k8s import read_secret_data
from secret_sources.providers import ccp, conjur, vault
from secret_sources.tls import TlsMaterial

_KINDS = {"conjur", "ccp", "vault"}


def effective_backend(row, ciphertext_attr: str) -> str:
    backend = (getattr(row, "secret_backend", None) or "db").strip() or "db"
    if backend in {"kubernetes", "conjur", "ccp", "vault"}:
        return backend
    ciphertext = getattr(row, ciphertext_attr, "") or ""
    if not ciphertext and getattr(row, "k8s_secret_name", None):
        return "kubernetes"
    return "db"


def credential_namespace(explicit: str = "") -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    from shared.config import get_settings

    settings = get_settings()
    configured = (settings.secret_namespace or "").strip()
    if configured:
        return configured
    path = Path("/var/run/secrets/kubernetes.io/serviceaccount/namespace")
    if path.is_file():
        found = path.read_text(encoding="utf-8").strip()
        if found:
            return found
    return os.environ.get("POD_NAMESPACE", "") or "agent-runtime"


def resolve_kubernetes_value(name: str, key: str, namespaces: list[str]) -> str:
    if not name:
        raise SecretProviderError("Kubernetes Secret adı yok")
    if not key:
        raise SecretProviderError("Kubernetes Secret anahtarı yok")
    last: SecretProviderError | None = None
    seen: list[str] = []
    for namespace in namespaces:
        if not namespace or namespace in seen:
            continue
        seen.append(namespace)
        try:
            data = read_secret_data(name, namespace)
        except SecretProviderError as exc:
            last = exc
            continue
        if key not in data or data[key] == "":
            last = SecretProviderError(f"Kubernetes Secret {namespace}/{name} içinde '{key}' anahtarı yok")
            continue
        return data[key]
    if last is not None:
        raise last
    raise SecretProviderError("Kubernetes Secret okunamadı")


def fetch_provider_secret(db, provider_id, path: str, ref: dict | None) -> str:
    if not provider_id:
        raise SecretProviderError("gizli bilgi kaynağı seçilmedi")
    from control_plane.models import SecretProvider

    provider = db.get(SecretProvider, provider_id)
    if provider is None or not provider.enabled:
        raise SecretProviderError("gizli bilgi kaynağı yok veya kapalı")
    if provider.kind not in _KINDS:
        raise SecretProviderError("bilinmeyen gizli bilgi kaynağı türü")
    payload = ref or {}
    cache_key = f"{provider.id}:{provider.kind}:{path}:{json.dumps(payload, sort_keys=True, default=str)}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached
    value = _fetch(provider, path or "", payload)
    if not value:
        raise SecretProviderError("sağlayıcı boş değer döndürdü")
    from shared.config import get_settings

    cache_put(cache_key, value, ttl=float(get_settings().secret_cache_ttl_seconds or 30))
    return value


def probe_provider(db, provider_id, *, path: str = "", ref: dict | None = None) -> dict:
    from control_plane.models import SecretProvider

    provider = db.get(SecretProvider, provider_id)
    if provider is None:
        raise SecretProviderError("gizli bilgi kaynağı yok")
    if provider.kind == "vault":
        vault.fetch_secret()
    if path or (ref or {}):
        fetch_provider_secret(db, provider.id, path, ref or {})
        return {"ok": True, "checked": "secret"}
    if provider.kind == "conjur":
        _authenticate_only(provider)
        return {"ok": True, "checked": "auth"}
    if provider.kind == "ccp":
        material, cert = _ccp_tls(provider)
        try:
            status = ccp.probe_base(base_url=provider.base_url, verify=material.verify, cert=cert)
        finally:
            material.close()
        return {"ok": True, "checked": "reachability", "http_status": status}
    raise SecretProviderError("bilinmeyen gizli bilgi kaynağı türü")


def _fetch(provider, path: str, ref: dict) -> str:
    if provider.kind == "vault":
        return vault.fetch_secret()
    if provider.kind == "conjur":
        if not path.strip():
            raise SecretProviderError("Conjur değişken yolu yok")
        material, api_key = _conjur_material(provider)
        try:
            config = provider.config or {}
            return conjur.fetch_variable(
                base_url=provider.base_url,
                account=provider.account or "",
                auth_method=provider.auth_method or "api-key",
                login=str(config.get("login") or ""),
                api_key=api_key,
                variable_id=path.strip(),
                verify=material.verify,
                service_id=str(config.get("service_id") or ""),
                token_path=str(config.get("token_path") or ""),
            )
        finally:
            material.close()
    if provider.kind == "ccp":
        material, cert = _ccp_tls(provider)
        try:
            config = provider.config or {}
            app_id = str(ref.get("app_id") or config.get("app_id") or "")
            return ccp.fetch_account(
                base_url=provider.base_url,
                app_id=app_id,
                safe=str(ref.get("safe") or ""),
                object_name=str(ref.get("object") or ""),
                query=str(ref.get("query") or ""),
                verify=material.verify,
                cert=cert,
            )
        finally:
            material.close()
    raise SecretProviderError("bilinmeyen gizli bilgi kaynağı türü")


def _authenticate_only(provider) -> None:
    material, api_key = _conjur_material(provider)
    try:
        config = provider.config or {}
        conjur.authenticate(
            base_url=provider.base_url,
            account=provider.account or "",
            auth_method=provider.auth_method or "api-key",
            login=str(config.get("login") or ""),
            api_key=api_key,
            verify=material.verify,
            service_id=str(config.get("service_id") or ""),
            token_path=str(config.get("token_path") or ""),
        )
    finally:
        material.close()


def _load_credential_secret(provider) -> dict[str, str]:
    name = (provider.credential_secret_name or "").strip()
    if not name:
        return {}
    namespace = credential_namespace(provider.credential_namespace or "")
    return read_secret_data(name, namespace)


def _conjur_material(provider) -> tuple[TlsMaterial, str]:
    data = _load_credential_secret(provider)
    method = (provider.auth_method or "api-key").strip()
    api_key = ""
    if method == "api-key":
        key_name = (provider.credential_secret_key or "api_key").strip() or "api_key"
        api_key = data.get(key_name) or ""
        if not api_key:
            raise SecretProviderError(
                "Conjur API anahtarı Kubernetes Secret içinde yok. Düz metin anahtar kaydedilmez."
            )
    material = TlsMaterial(ca_pem=provider.ca_bundle or "")
    return material, api_key


def _ccp_tls(provider) -> tuple[TlsMaterial, tuple[str, str] | None]:
    data = _load_credential_secret(provider)
    method = (provider.auth_method or "allowed-machines").strip()
    cert_pem = ""
    key_pem = ""
    if method == "mtls":
        cert_name = (provider.tls_cert_key or "tls.crt").strip()
        key_name = (provider.tls_key_key or "tls.key").strip()
        cert_pem = data.get(cert_name) or ""
        key_pem = data.get(key_name) or ""
        if not cert_pem or not key_pem:
            raise SecretProviderError(
                "CCP istemci sertifikası Kubernetes Secret içinde yok. Sertifika düz metin kaydedilmez."
            )
    elif method != "allowed-machines":
        raise SecretProviderError("CCP kimlik yöntemi mtls veya allowed-machines olmalı.")
    material = TlsMaterial(ca_pem=provider.ca_bundle or "", cert_pem=cert_pem, key_pem=key_pem)
    return material, material.cert
