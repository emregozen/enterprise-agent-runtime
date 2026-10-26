"""CyberArk Central Credential Provider REST API.

Documented call (AIMWebService):

    GET /AIMWebService/api/Accounts?AppID=&Safe=&Object=
    GET /AIMWebService/api/Accounts?AppID=&Query=Safe=...;Object=...

The JSON field ``Content`` is the secret. UserName, Address and
PasswordChangeInProcess may also be present; they are not logged.

Auth is the TLS client certificate (mTLS) and/or the allowed-machines list
(the control plane's source address must be on the CyberArk application).
There is no password in the query string.
"""

from __future__ import annotations

import httpx

from secret_sources.errors import SecretProviderError
from secret_sources.http import client


def fetch_account(
    *,
    base_url: str,
    app_id: str,
    safe: str = "",
    object_name: str = "",
    query: str = "",
    verify: bool | str = True,
    cert: tuple[str, str] | None = None,
) -> str:
    if not app_id.strip():
        raise SecretProviderError("CyberArk CCP AppID yok. Sağlayıcıda veya hesap başvurusunda AppID yazın.")
    if not query.strip() and not object_name.strip():
        raise SecretProviderError("CyberArk CCP için Object veya Query gerekli.")
    params: dict[str, str] = {"AppID": app_id.strip()}
    if query.strip():
        params["Query"] = query.strip()
    else:
        if safe.strip():
            params["Safe"] = safe.strip()
        params["Object"] = object_name.strip()
    url = base_url.rstrip("/") + "/AIMWebService/api/Accounts"
    try:
        with client(verify=verify, cert=cert) as http:
            response = http.get(url, params=params)
    except httpx.HTTPError as exc:
        raise SecretProviderError(
            "CyberArk CCP sunucusuna ulaşılamadı. Adres, istemci sertifikası ve izinli makine listesini kontrol edin."
        ) from exc
    if response.status_code >= 400:
        raise SecretProviderError(
            f"CyberArk CCP isteği reddedildi (HTTP {response.status_code}). "
            "AppID, Safe veya istemci sertifikası kabul edilmedi."
        )
    try:
        body = response.json()
    except Exception as exc:  # noqa: BLE001
        raise SecretProviderError("CyberArk CCP yanıtı okunamadı.") from exc
    if not isinstance(body, dict):
        raise SecretProviderError("CyberArk CCP yanıtı beklenen hesap nesnesi değil.")
    content = body.get("Content")
    if content is None or content == "":
        raise SecretProviderError("CyberArk CCP hesap içeriği boş döndü.")
    return str(content)


def probe_base(*, base_url: str, verify: bool | str = True, cert: tuple[str, str] | None = None) -> int:
    """Any HTTP status means the CCP answered. The body is discarded."""
    url = base_url.rstrip("/") + "/AIMWebService/api/Accounts"
    try:
        with client(verify=verify, cert=cert) as http:
            response = http.get(url)
    except httpx.HTTPError as exc:
        raise SecretProviderError(
            "CyberArk CCP sunucusuna ulaşılamadı. Adres, istemci sertifikası ve izinli makine listesini kontrol edin."
        ) from exc
    return response.status_code
