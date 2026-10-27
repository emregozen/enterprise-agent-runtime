"""SMTP and generic HTTP transports. Credentials stay in memory for the call."""

from __future__ import annotations

import base64
import smtplib
import time
from email.message import EmailMessage

import httpx

from delivery.render import fill_template, format_from


class DeliveryError(Exception):
    pass


def send_smtp(
    *,
    host: str,
    port: int,
    tls_mode: str,
    username: str,
    password: str,
    sender: str,
    from_name: str,
    to: list[str],
    cc: list[str],
    subject: str,
    html_body: str,
    text_body: str,
    attachments: list[dict],
    timeout: float,
) -> dict:
    if not host:
        raise DeliveryError("SMTP sunucusu yok")
    message = EmailMessage()
    message["From"] = format_from(from_name, sender)
    message["To"] = ", ".join(to)
    if cc:
        message["Cc"] = ", ".join(cc)
    message["Subject"] = subject
    message.set_content(text_body or "")
    if html_body:
        message.add_alternative(html_body, subtype="html")
    for item in attachments:
        main, _, sub = (item.get("content_type") or "application/octet-stream").partition("/")
        message.add_attachment(
            item["data"],
            maintype=main or "application",
            subtype=sub or "octet-stream",
            filename=item["filename"],
        )
    started = time.monotonic()
    client = smtplib.SMTP_SSL(host, port, timeout=timeout) if tls_mode == "ssl" else smtplib.SMTP(host, port, timeout=timeout)
    try:
        client.ehlo()
        if tls_mode == "starttls":
            client.starttls()
            client.ehlo()
        if username:
            client.login(username, password)
        client.send_message(message)
    except (smtplib.SMTPException, OSError, TimeoutError) as exc:
        raise DeliveryError(f"teslimat gönderilemedi: {exc}") from exc
    finally:
        try:
            client.quit()
        except Exception:
            pass
    return {"latency_ms": int((time.monotonic() - started) * 1000), "status_code": 250}


def send_http(
    *,
    url: str,
    method: str,
    headers: dict,
    auth: str,
    username: str,
    header_name: str,
    credential: str,
    body_template: str,
    values: dict,
    success_codes: list[int],
    timeout: float,
) -> dict:
    if not url:
        raise DeliveryError("teslimat adresi yok")
    payload = fill_template(body_template, values)
    request_headers = {str(key): str(value) for key, value in (headers or {}).items()}
    if not any(key.lower() == "content-type" for key in request_headers):
        request_headers["Content-Type"] = "application/json"
    auth_header = _auth_header(auth, username, header_name, credential)
    if auth_header:
        request_headers[auth_header[0]] = auth_header[1]
    started = time.monotonic()
    try:
        response = httpx.request(method, url, content=payload.encode(), headers=request_headers, timeout=timeout)
    except httpx.HTTPError as exc:
        raise DeliveryError(f"teslimat gönderilemedi: {exc}") from exc
    latency = int((time.monotonic() - started) * 1000)
    if response.status_code not in success_codes:
        raise DeliveryError(f"teslimat gönderilemedi: HTTP {response.status_code}")
    return {"latency_ms": latency, "status_code": response.status_code}


def attachment_values(attachments: list[dict]) -> list[dict]:
    rendered = []
    for item in attachments:
        rendered.append(
            {
                "filename": item["filename"],
                "content_type": item.get("content_type") or "application/octet-stream",
                "content_base64": base64.b64encode(item["data"]).decode("ascii"),
            }
        )
    return rendered


def _auth_header(auth: str, username: str, header_name: str, credential: str) -> tuple[str, str] | None:
    if auth == "none" or not auth:
        return None
    if auth == "bearer":
        return "Authorization", f"Bearer {credential}"
    if auth == "basic":
        token = base64.b64encode(f"{username}:{credential}".encode()).decode("ascii")
        return "Authorization", f"Basic {token}"
    if auth == "header":
        name = (header_name or "").strip()
        if not name:
            raise DeliveryError("özel başlık adı yok")
        return name, credential
    raise DeliveryError("kimlik doğrulama none, bearer, basic veya header olmalı")
