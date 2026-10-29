"""Send a finished run's report from the control plane."""

from __future__ import annotations

import time
from datetime import datetime

from sqlalchemy.orm import Session

from control_plane.models import Artifact, DeliveryChannel, DeliveryLog, Run, utcnow
from delivery.policy import reject_recipients
from delivery.render import message_parts, render_subject
from delivery.transport import DeliveryError, attachment_values, send_http, send_smtp

DEFAULT_HTTP_TEMPLATE = """{
  "to": {{to}},
  "cc": {{cc}},
  "subject": "{{subject}}",
  "html": "{{html}}",
  "text": "{{text}}",
  "attachments": {{attachments}},
  "report_url": "{{report_url}}"
}"""


def deliver_run(db: Session, run: Run) -> None:
    """Record each send. A failure here does not change the run status."""
    if run.dry_run:
        return
    if db.query(DeliveryLog).filter(DeliveryLog.run_id == run.id).count():
        return
    targets = ((run.spec_snapshot or {}).get("spec") or {}).get("delivery") or []
    if not targets:
        return
    failed = False
    for target in targets:
        if not _due(str(target.get("when") or "success"), run.status):
            _log(db, run, None, target, "skipped", None, {"automatic": True, "reason": "when"})
            continue
        ok = _send_target(db, run, target, automatic=True)
        failed = failed or not ok
    if failed:
        summary = dict(run.summary or {})
        summary["delivery_warning"] = "teslimat tamamlanamadı"
        run.summary = summary
    db.commit()


def resend(db: Session, run: Run, log: DeliveryLog) -> DeliveryLog:
    target = dict((log.detail or {}).get("target") or {})
    if not target:
        target = {
            "channel": log.channel_name,
            "to": (log.recipients or {}).get("to") or [],
            "cc": (log.recipients or {}).get("cc") or [],
            "subject": log.subject,
            "when": "always",
            "content": (log.detail or {}).get("content") or "inline",
            "attachment": (log.detail or {}).get("attachment") or "html",
        }
    ok = _send_target(db, run, target, automatic=False)
    if ok:
        summary = dict(run.summary or {})
        summary.pop("delivery_warning", None)
        run.summary = summary
    db.commit()
    latest = (
        db.query(DeliveryLog)
        .filter(DeliveryLog.run_id == run.id)
        .order_by(DeliveryLog.created_at.desc())
        .first()
    )
    return latest or log


def send_test(db: Session, channel: DeliveryChannel, recipient: str) -> dict:
    from control_plane.service import ServiceError

    if not channel.enabled:
        raise ServiceError("teslimat kanalı kapalı", 409)
    blocked = reject_recipients([recipient], list(channel.allow_domains or []))
    if blocked:
        raise ServiceError("alıcı izin verilen etki alanında değil", 400)
    target = {
        "channel": channel.name,
        "to": [recipient],
        "cc": [],
        "subject": "Delivery test",
        "content": "inline",
        "attachment": "html",
    }
    try:
        detail = _dispatch(
            db,
            channel,
            target,
            agent_name="delivery-test",
            moment=datetime.now(),
            run_id="test",
            status="succeeded",
            report="This is a test message from Agent Runtime.",
            report_url="",
            artifacts=[],
        )
    except DeliveryError as exc:
        raise ServiceError(str(exc), 502) from exc
    return {"ok": True, **detail}


def _due(when: str, status: str) -> bool:
    if when == "always":
        return status in {"succeeded", "failed", "needs_review"}
    if when == "failure":
        return status == "failed"
    return status == "succeeded"


def _send_target(db: Session, run: Run, target: dict, *, automatic: bool) -> bool:
    from control_plane.service import audit

    name = str(target.get("channel") or "")
    channel = db.query(DeliveryChannel).filter(DeliveryChannel.name == name).one_or_none()
    if channel is not None and run.owner_group_id and channel.owner_group_id and channel.owner_group_id != run.owner_group_id:
        channel = None
    recipients = {"to": list(target.get("to") or []), "cc": list(target.get("cc") or [])}
    subject = render_subject(
        str(target.get("subject") or ""),
        agent_name=run.agent_name,
        moment=run.finished_at,
        run_id=str(run.id),
        status=run.status,
    )
    if channel is None or not channel.enabled:
        _log(db, run, channel, target, "failed", "teslimat kanalı yok veya kapalı", {"automatic": automatic, "target": target, "content": target.get("content")})
        audit(db, "delivery", "delivery.failed", "run", str(run.id), {"channel": name, "to": recipients["to"]})
        return False
    blocked = reject_recipients(recipients["to"] + recipients["cc"], list(channel.allow_domains or []))
    if blocked or not recipients["to"]:
        _log(
            db,
            run,
            channel,
            target,
            "failed",
            "alıcı izin verilen etki alanında değil",
            {"automatic": automatic, "target": target, "blocked": blocked},
        )
        audit(db, "delivery", "delivery.failed", "run", str(run.id), {"channel": name, "to": recipients["to"], "blocked": blocked})
        return False
    try:
        detail = _dispatch(
            db,
            channel,
            target,
            agent_name=run.agent_name,
            moment=run.finished_at,
            run_id=str(run.id),
            status=run.status,
            report=run.report_markdown or "",
            report_url=_report_url(run),
            artifacts=_artifacts(db, run) if target.get("content") == "artifacts" else [],
        )
    except DeliveryError as exc:
        _log(db, run, channel, target, "failed", str(exc), {"automatic": automatic, "target": target, "content": target.get("content")})
        audit(db, "delivery", "delivery.failed", "run", str(run.id), {"channel": name, "to": recipients["to"], "error": str(exc)[:300]})
        return False
    action = "delivery.sent" if automatic else "delivery.resent"
    _log(
        db,
        run,
        channel,
        target,
        "sent",
        None,
        {"automatic": automatic, "target": target, "content": target.get("content"), "attachment": target.get("attachment"), **detail},
        subject=subject,
    )
    audit(db, "delivery", action, "run", str(run.id), {"channel": name, "to": recipients["to"], "status": "sent"})
    return True


def _dispatch(
    db: Session,
    channel: DeliveryChannel,
    target: dict,
    *,
    agent_name: str,
    moment: datetime | None,
    run_id: str,
    status: str,
    report: str,
    report_url: str,
    artifacts: list[dict],
) -> dict:
    from control_plane.delivery_catalog import resolve_credential

    credential = resolve_credential(db, channel)
    subject = render_subject(
        str(target.get("subject") or ""),
        agent_name=agent_name,
        moment=moment,
        run_id=run_id,
        status=status,
    )
    html_body, text_body, files = message_parts(
        content=str(target.get("content") or "inline"),
        attachment=str(target.get("attachment") or "html"),
        report_markdown=report,
        report_url=report_url,
        artifacts=artifacts,
    )
    total = sum(len(item["data"]) for item in files)
    if total > int(channel.max_attachment_bytes or 0):
        raise DeliveryError("ek boyutu sınırı aşıyor")
    to = list(target.get("to") or [])
    cc = list(target.get("cc") or [])
    config = channel.config or {}
    timeout = float(config.get("timeout_seconds") or 20)
    if channel.kind == "smtp":
        return send_smtp(
            host=str(config.get("host") or ""),
            port=int(config.get("port") or 587),
            tls_mode=str(config.get("tls_mode") or "starttls"),
            username=str(config.get("username") or ""),
            password=credential,
            sender=channel.from_address,
            from_name=channel.from_name or "",
            to=to,
            cc=cc,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            attachments=files,
            timeout=timeout,
        )
    if channel.kind == "http":
        values = {
            "to": to,
            "cc": cc,
            "subject": subject,
            "html": html_body,
            "text": text_body,
            "attachments": attachment_values(files),
            "report_url": report_url,
        }
        return send_http(
            url=str(config.get("url") or ""),
            method=str(config.get("method") or "POST").upper(),
            headers=dict(config.get("headers") or {}),
            auth=str(config.get("auth") or "none"),
            username=str(config.get("username") or ""),
            header_name=str(config.get("header_name") or ""),
            credential=credential,
            body_template=str(config.get("body_template") or DEFAULT_HTTP_TEMPLATE),
            values=values,
            success_codes=[int(code) for code in (config.get("success_codes") or [200, 201, 202])],
            timeout=timeout,
        )
    raise DeliveryError("tür smtp veya http olmalı")


def _artifacts(db: Session, run: Run) -> list[dict]:
    from shared.artifacts import build_store
    from shared.config import get_settings

    store = build_store(get_settings())
    files = []
    rows = db.query(Artifact).filter(Artifact.run_id == run.id).all()
    for row in rows:
        try:
            data = store.get_bytes(row.storage_uri)
        except Exception:
            continue
        files.append({"filename": row.name, "content_type": row.media_type, "data": data})
    return files


def _report_url(run: Run) -> str:
    from shared.config import get_settings

    base = get_settings().control_plane_public_url.rstrip("/")
    return f"{base}/api/runs/{run.id}"


def _log(
    db: Session,
    run: Run,
    channel: DeliveryChannel | None,
    target: dict,
    status: str,
    error: str | None,
    detail: dict,
    subject: str = "",
) -> DeliveryLog:
    if not subject:
        subject = render_subject(
            str(target.get("subject") or ""),
            agent_name=run.agent_name,
            moment=run.finished_at,
            run_id=str(run.id),
            status=run.status,
        )
    row = DeliveryLog(
        run_id=run.id,
        channel_id=channel.id if channel is not None else None,
        channel_name=(channel.name if channel is not None else str(target.get("channel") or ""))[:63],
        recipients={"to": list(target.get("to") or []), "cc": list(target.get("cc") or [])},
        subject=subject[:300],
        status=status,
        error=(error or None),
        detail=detail,
        created_at=utcnow(),
    )
    db.add(row)
    db.flush()
    return row


def test_recipient(channel: DeliveryChannel) -> str:
    domains = [str(item) for item in (channel.allow_domains or []) if str(item).strip()]
    if not domains:
        from control_plane.service import ServiceError

        raise ServiceError("alıcı izin listesi boş", 400)
    domain = domains[0].lower().strip().lstrip("@")
    if domain.startswith("*."):
        domain = domain[2:]
    return f"delivery-test@{domain}"


# Imported for tests that want a monotonic marker without sending.
def _now_ms() -> int:
    return int(time.monotonic() * 1000)
