"""Delivery stays in the control plane. Recipients come from the spec, not the model."""

from __future__ import annotations

import json
import uuid

from fastapi.testclient import TestClient

from control_plane.backends import RecordingBackend, set_backend
from control_plane.main import create_app
from control_plane.models import AuditEvent, DeliveryLog, Run
from control_plane.seed import EXAMPLE_SPEC
from control_plane.service import complete_run
from delivery.mock_http import serve
from shared.fake_llm import FakeLLM


def _channel(url: str, *, name: str = "kurumsal", domains: list[str] | None = None, auth: str = "bearer", password: str = "s3cret-token", limit: int = 2_000_000) -> dict:
    return {
        "name": name,
        "kind": "http",
        "enabled": True,
        "from_address": "runtime@example.com",
        "from_name": "Agent Runtime",
        "allow_domains": domains or ["example.com"],
        "max_attachment_bytes": limit,
        "password": password,
        "secret_backend": "db",
        "config": {
            "url": url,
            "method": "POST",
            "headers": {"X-Caller": "agent-runtime"},
            "auth": auth,
            "success_codes": [200, 202],
            "timeout_seconds": 5,
            "body_template": '{"to": {{to}}, "cc": {{cc}}, "subject": "{{subject}}", "html": "{{html}}", "text": "{{text}}", "token": "nope"}',
        },
    }


def _spec(name: str, channel: str, to: list[str], **target) -> dict:
    spec = json.loads(json.dumps(EXAMPLE_SPEC))
    spec["metadata"]["name"] = name
    spec["spec"]["delivery"] = [
        {
            "channel": channel,
            "to": to,
            "cc": target.get("cc", []),
            "subject": target.get("subject", "{{agent_name}} – {{run_date}}"),
            "when": target.get("when", "success"),
            "content": target.get("content", "inline"),
            "attachment": "html",
        }
    ]
    return spec


def _finish(db, client, spec: dict, *, status: str = "succeeded", report: str = "# Rapor\n\nToplam 10", dry_run: bool = False):
    set_backend(RecordingBackend())
    created = client.post("/api/agents", json={"spec": spec, "publish": True})
    assert created.status_code == 201, created.text
    ran = client.post(f"/api/agents/{created.json()['id']}/runs", json={"dry_run": dry_run})
    assert ran.status_code == 202, ran.text
    run = db.get(Run, uuid.UUID(ran.json()["id"]))
    db.refresh(run)
    complete_run(
        db,
        run,
        {"status": status, "summary": {"note": "plan wanted other@evil.test"}, "report_markdown": report, "error": None},
    )
    db.refresh(run)
    return run


def test_http_delivery_uses_spec_recipients_and_hides_the_secret(db, datasource):
    server = serve()
    try:
        port = server.server_address[1]
        set_backend(RecordingBackend())
        with TestClient(create_app()) as client:
            saved = client.post("/api/delivery-channels", json=_channel(f"http://127.0.0.1:{port}/send"))
            assert saved.status_code == 201, saved.text
            body = saved.json()
            assert body["credential_set"] is True
            assert "s3cret-token" not in saved.text
            assert "credential_ciphertext" not in body
            run = _finish(db, client, _spec("teslim-http", "kurumsal", ["finance@example.com"], cc=["ops@example.com"]))
            assert run.status == "succeeded"
            assert (run.summary or {}).get("delivery_warning") is None
            detail = client.get(f"/api/runs/{run.id}")
            assert detail.status_code == 200
            logs = detail.json()["deliveries"]
            assert logs[0]["status"] == "sent"
            assert logs[0]["recipients"]["to"] == ["finance@example.com"]
            assert logs[0]["recipients"]["cc"] == ["ops@example.com"]
            assert any(event["action"] == "delivery.sent" for event in detail.json()["audit"])
        assert len(server.inbox) == 1
        message = server.inbox[0]
        assert message["body"]["to"] == ["finance@example.com"]
        assert message["body"]["cc"] == ["ops@example.com"]
        assert "other@evil.test" not in json.dumps(message["body"]["to"])
        assert message["authorization"] == "Bearer s3cret-token"
        assert message["body"]["token"] == "nope"
        assert "Toplam 10" in message["body"]["text"]
    finally:
        server.shutdown()
        set_backend(None)


def test_delivery_failure_does_not_fail_the_run_and_resend_works(db, datasource):
    server = serve()
    try:
        with TestClient(create_app()) as client:
            saved = client.post("/api/delivery-channels", json=_channel("http://127.0.0.1:1/send", name="kopuk", auth="none", password=""))
            assert saved.status_code == 201, saved.text
            channel_id = saved.json()["id"]
            run = _finish(db, client, _spec("teslim-hata", "kopuk", ["finance@example.com"]))
            assert run.status == "succeeded"
            assert run.summary["delivery_warning"] == "teslimat tamamlanamadı"
            row = db.query(DeliveryLog).filter(DeliveryLog.run_id == run.id).one()
            assert row.status == "failed"
            patched = client.patch(
                f"/api/delivery-channels/{channel_id}",
                json=_channel(f"http://127.0.0.1:{server.server_address[1]}/send", name="kopuk", auth="none", password=""),
            )
            assert patched.status_code == 200, patched.text
            resent = client.post(f"/api/runs/{run.id}/deliveries/{row.id}/resend")
            assert resent.status_code == 200, resent.text
            assert resent.json()["status"] == "sent"
            db.refresh(run)
            assert run.status == "succeeded"
            assert "delivery_warning" not in (run.summary or {})
        assert server.inbox[0]["body"]["to"] == ["finance@example.com"]
        audits = db.query(AuditEvent).filter(AuditEvent.action == "delivery.resent").all()
        assert audits
    finally:
        server.shutdown()
        set_backend(None)


def test_allowlist_and_when_and_dry_run(db, datasource):
    server = serve()
    try:
        with TestClient(create_app()) as client:
            saved = client.post("/api/delivery-channels", json=_channel(f"http://127.0.0.1:{server.server_address[1]}/send", name="izin"))
            assert saved.status_code == 201, saved.text
            blocked = client.post("/api/agents", json={"spec": _spec("yasak", "izin", ["outsider@other.test"]), "publish": True})
            assert blocked.status_code == 400
            assert blocked.json()["detail"] == "alıcı izin verilen etki alanında değil"
            skipped = _finish(db, client, _spec("yalniz-hata", "izin", ["finance@example.com"], when="failure"))
            assert skipped.status == "succeeded"
            log = db.query(DeliveryLog).filter(DeliveryLog.run_id == skipped.id).one()
            assert log.status == "skipped"
            dry = _finish(db, client, _spec("kuru", "izin", ["finance@example.com"]), dry_run=True)
            assert dry.status == "succeeded"
            assert db.query(DeliveryLog).filter(DeliveryLog.run_id == dry.id).count() == 0
        assert server.inbox == []
    finally:
        server.shutdown()
        set_backend(None)


def test_builder_prefills_from_the_description_and_drops_model_recipients(db, datasource, monkeypatch):
    original = FakeLLM._build

    def sneak(self, payload):
        spec = original(self, payload)
        spec["spec"]["delivery"] = [{"channel": "evil", "to": ["attacker@evil.test"], "cc": [], "subject": "stolen", "when": "always", "content": "link", "attachment": "html"}]
        return spec

    monkeypatch.setattr(FakeLLM, "_build", sneak)
    with TestClient(create_app()) as client:
        quiet = client.post("/api/delivery-channels", json=_channel("http://127.0.0.1:9/send", name="kurumsal", domains=["firma.example"]))
        assert quiet.status_code == 201, quiet.text
        mentioned = client.post(
            "/api/builder/draft",
            json={
                "description": "Sonucu satis-ekibi@firma.example adresine mail at",
                "owner": "satis",
                "datasource_refs": ["postgres-sales"],
            },
        )
        assert mentioned.status_code == 200, mentioned.text
        target = mentioned.json()["spec"]["spec"]["delivery"][0]
        assert target["to"] == ["satis-ekibi@firma.example"]
        assert target["channel"] == "kurumsal"
        assert "attacker@evil.test" not in mentioned.text
        plain = client.post(
            "/api/builder/draft",
            json={
                "description": "Satışları bölge bazında özetle",
                "owner": "satis",
                "datasource_refs": ["postgres-sales"],
            },
        )
        assert plain.status_code == 200, plain.text
        assert plain.json()["spec"]["spec"]["delivery"] == []


def test_attachment_limit_is_a_warning(db, datasource):
    with TestClient(create_app()) as client:
        saved = client.post(
            "/api/delivery-channels",
            json=_channel("http://127.0.0.1:9/send", name="kucuk", limit=20),
        )
        assert saved.status_code == 201, saved.text
        run = _finish(
            db,
            client,
            _spec("ek-siniri", "kucuk", ["finance@example.com"], content="attachment"),
            report="bu rapor sinirdan uzun bir metin",
        )
        assert run.status == "succeeded"
        assert run.summary["delivery_warning"] == "teslimat tamamlanamadı"
        log = db.query(DeliveryLog).filter(DeliveryLog.run_id == run.id).one()
        assert log.status == "failed"
        assert "ek boyutu" in (log.error or "")
    set_backend(None)
