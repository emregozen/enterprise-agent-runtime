"""CyberArk Conjur Open Source REST API.

API-key auth is the PoC path: POST the host API key, then GET the variable with the
short-lived token. authn-k8s and authn-jwt use the control-plane service account
token when that file is mounted. The response body is the secret and is not logged.

See Conjur REST: /authn/{account}/{login}/authenticate and
/secrets/{account}/variable/{id}. Login and variable ids are percent-encoded.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path
from urllib.parse import quote

import httpx

from secret_sources.errors import SecretProviderError
from secret_sources.http import client

_SA_TOKEN = "/var/run/secrets/kubernetes.io/serviceaccount/token"


def fetch_variable(
    *,
    base_url: str,
    account: str,
    auth_method: str,
    login: str,
    api_key: str,
    variable_id: str,
    verify: bool | str = True,
    service_id: str = "",
    token_path: str = "",
) -> str:
    token = authenticate(
        base_url=base_url,
        account=account,
        auth_method=auth_method,
        login=login,
        api_key=api_key,
        verify=verify,
        service_id=service_id,
        token_path=token_path,
    )
    url = f"{base_url.rstrip('/')}/secrets/{quote(account, safe='')}/variable/{quote(variable_id, safe='')}"
    try:
        with client(verify=verify) as http:
            response = http.get(url, headers={"Authorization": f'Token token="{token}"'})
    except httpx.HTTPError as exc:
        raise SecretProviderError(
            "Conjur sunucusuna ulaşılamadı. Adres, sertifika ve ağ politikasını kontrol edin."
        ) from exc
    if response.status_code == 404:
        raise SecretProviderError(f"Conjur değişkeni bulunamadı: {variable_id}")
    if response.status_code >= 400:
        raise SecretProviderError(
            f"Conjur değişkeni okunamadı (HTTP {response.status_code}). Host'un bu değişkeni okuma izni olmayabilir."
        )
    return response.text


def authenticate(
    *,
    base_url: str,
    account: str,
    auth_method: str,
    login: str,
    api_key: str,
    verify: bool | str = True,
    service_id: str = "",
    token_path: str = "",
) -> str:
    if not account.strip():
        raise SecretProviderError("Conjur hesap adı yok")
    if not login.strip():
        raise SecretProviderError(
            "Conjur host kimliği yok. Sağlayıcı kaydında login yazın (örnek: host/agent-runtime/control)."
        )
    method = (auth_method or "api-key").strip()
    encoded_login = quote(login.strip(), safe="")
    root = base_url.rstrip("/")
    headers = {"Accept-Encoding": "base64"}
    content: bytes | None = None
    data: dict[str, str] | None = None
    if method == "api-key":
        if not api_key:
            raise SecretProviderError("Conjur API anahtarı boş. Anahtar Kubernetes Secret içinden okunur, düz metin kaydedilmez.")
        url = f"{root}/authn/{quote(account, safe='')}/{encoded_login}/authenticate"
        content = api_key.encode("utf-8")
    elif method in {"authn-k8s", "authn-jwt"}:
        jwt = _service_account_token(token_path)
        authenticator = (service_id or method).strip()
        url = (
            f"{root}/{method}/{quote(authenticator, safe='')}/"
            f"{quote(account, safe='')}/{encoded_login}/authenticate"
        )
        data = {"jwt": jwt}
    else:
        raise SecretProviderError(
            "Conjur kimlik yöntemi api-key, authn-k8s veya authn-jwt olmalı. PoC yolu API anahtarıdır."
        )
    try:
        with client(verify=verify) as http:
            if data is not None:
                response = http.post(url, data=data, headers=headers)
            else:
                response = http.post(url, content=content, headers=headers)
    except httpx.HTTPError as exc:
        raise SecretProviderError(
            "Conjur sunucusuna ulaşılamadı. Adres, sertifika ve ağ politikasını kontrol edin."
        ) from exc
    if response.status_code in {401, 403}:
        raise SecretProviderError("Conjur kimlik doğrulaması reddedildi. API anahtarı veya host kimliği yanlış.")
    if response.status_code >= 400:
        raise SecretProviderError(f"Conjur kimlik doğrulaması başarısız (HTTP {response.status_code}).")
    return _token_text(response.content)


def _service_account_token(token_path: str) -> str:
    path = token_path.strip() or os.environ.get("CONJUR_SA_TOKEN_PATH", "") or _SA_TOKEN
    file = Path(path)
    if not file.is_file():
        raise SecretProviderError(
            "authn-k8s / authn-jwt için kontrol düzleminin servis hesabı token dosyası yok. "
            "PoC API anahtarı kullanır; bu yöntem token dosyası bağlanınca açılır."
        )
    token = file.read_text(encoding="utf-8").strip()
    if not token:
        raise SecretProviderError("servis hesabı token dosyası boş")
    return token


def _token_text(raw: bytes) -> str:
    try:
        text = raw.decode("ascii").strip()
    except UnicodeDecodeError:
        text = base64.b64encode(raw).decode("ascii")
    if not text:
        raise SecretProviderError("Conjur token boş döndü")
    return text
