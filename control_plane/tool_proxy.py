from __future__ import annotations

import fnmatch
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.orm import Session

from control_plane.models import AuditEvent, ToolCall, utcnow
from shared.config import get_settings


class ToolError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def invoke_tool(db: Session, run, tool_name: str, arguments: dict) -> dict:
    settings = get_settings()
    allowed = run.spec_snapshot["spec"].get("tools") or []
    if tool_name not in allowed:
        _audit(db, run, "tool.rejected", {"tool": tool_name, "reason": "not allowed"})
        raise ToolError("araç bu ajanın listesinde yok", 403)
    if run.dry_run:
        _audit(db, run, "tool.rejected", {"tool": tool_name, "reason": "dry_run"})
        raise ToolError("deneme koşusunda araç çağrılmaz", 409)
    if run.status != "running":
        _audit(db, run, "tool.rejected", {"tool": tool_name, "reason": run.status})
        raise ToolError("araç yalnızca çalışan koşudan çağrılır", 409)
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    recent = (
        db.query(ToolCall)
        .filter(ToolCall.tool_name == tool_name, ToolCall.created_at >= since, ToolCall.status == "ok")
        .count()
    )
    if recent >= settings.tool_rate_limit_per_hour:
        raise ToolError("araç saatlik limitine takıldı", 429)
    if tool_name in {"send_email", "send_sms"}:
        recipient = str(arguments.get("to") or "")
        if not _recipient_ok(recipient, settings.recipient_allowlist()):
            _audit(db, run, "tool.rejected", {"tool": tool_name, "to": recipient})
            raise ToolError("alıcı izin listesinde değil", 403)
    if tool_name == "http_request":
        _validate_http_path(str(arguments.get("path") or ""))
    response, mode = _dispatch(tool_name, arguments, settings)
    call = ToolCall(
        run_id=run.id,
        tool_name=tool_name,
        request=_public_arguments(arguments),
        response=response,
        status="ok" if response.get("ok", True) else "error",
    )
    db.add(call)
    _audit(db, run, "tool.invoked", {"tool": tool_name, "mode": mode, "to": arguments.get("to")})
    db.commit()
    return {"ok": response.get("ok", True), "mode": mode, "result": response}


def _dispatch(tool_name: str, arguments: dict, settings) -> tuple[dict, str]:
    if tool_name == "send_email":
        return _post_or_mock(settings.email_api_url, settings.email_api_token, arguments, "email")
    if tool_name == "send_sms":
        return _post_or_mock(settings.sms_api_url, settings.sms_api_token, arguments, "sms")
    if tool_name == "http_request":
        return _generic_http(arguments, settings)
    raise ToolError("bilinmeyen araç", 404)


def _post_or_mock(url: str, token: str, arguments: dict, kind: str) -> tuple[dict, str]:
    payload = {
        "to": arguments.get("to"),
        "subject": arguments.get("subject"),
        "body": arguments.get("body"),
    }
    if not url:
        return {"ok": True, "status": "mocked", "provider": kind}, "mock"
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = httpx.post(url, json=payload, headers=headers, timeout=20)
    return {
        "ok": response.status_code < 300,
        "status_code": response.status_code,
        "body": response.text[:2000],
    }, "http"


def _generic_http(arguments: dict, settings) -> tuple[dict, str]:
    if not settings.http_tool_base_url:
        return {"ok": True, "status": "mocked", "provider": "http"}, "mock"
    path = arguments.get("path") or "/"
    method = str(arguments.get("method") or "POST").upper()
    if method not in {"GET", "POST", "PUT"}:
        raise ToolError("HTTP aracı yalnızca GET, POST veya PUT kullanır")
    url = settings.http_tool_base_url.rstrip("/") + path
    headers = {}
    if settings.http_tool_token:
        headers["Authorization"] = f"Bearer {settings.http_tool_token}"
    response = httpx.request(method, url, json=arguments.get("json"), headers=headers, timeout=20)
    return {"ok": response.status_code < 300, "status_code": response.status_code, "body": response.text[:2000]}, "http"


def _validate_http_path(path: str) -> None:
    if not path.startswith("/") or ".." in path or "://" in path or len(path) > 200:
        raise ToolError("HTTP yolu göreli ve kısa olmalı")


def _recipient_ok(recipient: str, patterns: list[str]) -> bool:
    if not recipient or "@" not in recipient:
        return False
    return any(fnmatch.fnmatch(recipient, pattern) for pattern in patterns)


def _public_arguments(arguments: dict) -> dict:
    hidden = {"authorization", "api_key", "token", "password"}
    return {key: value for key, value in arguments.items() if key.lower() not in hidden}


def _audit(db: Session, run, action: str, detail: dict) -> None:
    db.add(
        AuditEvent(
            ts=utcnow(),
            actor=f"run:{run.id}",
            action=action,
            entity_type="run",
            entity_id=str(run.id),
            detail=detail,
        )
    )
