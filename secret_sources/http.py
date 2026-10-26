"""HTTP client for secret providers. Callers must not log request or response bodies."""

from __future__ import annotations

import httpx

_transport: httpx.BaseTransport | None = None


def set_http_transport(transport: httpx.BaseTransport | None) -> None:
    global _transport
    _transport = transport


def client(*, verify: bool | str = True, cert: tuple[str, str] | None = None, timeout: float = 15.0) -> httpx.Client:
    kwargs: dict = {"timeout": timeout, "trust_env": False, "verify": verify}
    if cert is not None:
        kwargs["cert"] = cert
    if _transport is not None:
        kwargs["transport"] = _transport
    return httpx.Client(**kwargs)
