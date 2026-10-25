import json
import os
import time
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from control_plane.backends import RecordingBackend, set_backend
from control_plane.db import SessionLocal
from control_plane.main import create_app
from control_plane.models import Run, Schedule
from control_plane.scheduler import tick
from control_plane.seed import EXAMPLE_SPEC
from control_plane.service import claim_due
from shared.config import get_settings


def test_builder_and_run_registry(datasource):
    set_backend(RecordingBackend())
    with TestClient(create_app()) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        draft = client.post(
            "/api/builder/draft",
            json={
                "description": "Hafta içi her sabah dünkü satışları bölge bazında özetle, sapmaları açıkla ve e-posta gönder.",
                "owner": "finans-ekibi",
                "datasource_refs": ["postgres-sales"],
            },
        )
        assert draft.status_code == 200, draft.text
        spec = draft.json()["spec"]
        assert spec["spec"]["schedule"]["mode"] in {"cron", "hybrid"}
        assert "send_email" in spec["spec"]["tools"]
        created = client.post("/api/agents", json={"spec": spec, "publish": True})
        assert created.status_code == 201, created.text
        agent_id = created.json()["id"]
        ran = client.post(f"/api/agents/{agent_id}/runs", json={"dry_run": False})
        assert ran.status_code == 202, ran.text
        assert ran.json()["status"] in {"pending", "running"}
        listing = client.get("/api/runs")
        assert listing.status_code == 200
        assert listing.json()[0]["agent_name"]
    set_backend(None)


def test_scheduler_claims_one_due_schedule(db, datasource):
    set_backend(RecordingBackend())
    from control_plane.service import create_agent

    agent = create_agent(db, EXAMPLE_SPEC, publish=True, actor="test")
    schedule = db.query(Schedule).filter(Schedule.agent_id == agent.id).one()
    schedule.next_run_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    created = claim_due(db)
    db.commit()
    assert len(created) == 1
    db.refresh(schedule)
    assert schedule.next_run_at > datetime.now(timezone.utc)
    again = claim_due(db)
    db.commit()
    assert again == []
    run = db.get(Run, created[0][0])
    assert run.trigger == "cron"
    assert run.idempotency_key
    set_backend(None)


def test_audit_log_is_append_only(db):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    from control_plane.service import audit

    audit(db, "test", "agent.created", "agent", "x", {"hello": "world"})
    db.commit()
    try:
        db.execute(text("UPDATE audit_events SET actor = 'mutated'"))
        db.commit()
    except DBAPIError:
        db.rollback()
        return
    raise AssertionError("audit update should fail")


def test_end_to_end_local_job(datasource):
    """Run the sample agent as two local processes against the live API."""
    port = 8871
    os.environ["CONTROL_PLANE_PUBLIC_URL"] = f"http://127.0.0.1:{port}"
    os.environ["CONTROL_PLANE_INTERNAL_URL"] = f"http://127.0.0.1:{port}"
    os.environ["SCHEDULER_ENABLED"] = "false"
    get_settings.cache_clear()
    set_backend(None)
    import uvicorn

    app = create_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    import threading

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            import httpx

            if httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=0.5).status_code == 200:
                break
        except Exception:
            time.sleep(0.1)
    else:
        raise RuntimeError("control plane did not start")
    try:
        import httpx

        created = httpx.post(
            f"http://127.0.0.1:{port}/api/agents",
            json={"spec": EXAMPLE_SPEC, "publish": True},
            timeout=30,
        )
        assert created.status_code == 201, created.text
        agent_id = created.json()["id"]
        started = httpx.post(
            f"http://127.0.0.1:{port}/api/agents/{agent_id}/runs",
            json={"dry_run": False},
            timeout=30,
        )
        assert started.status_code == 202, started.text
        run_id = started.json()["id"]
        status = None
        body = None
        deadline = time.time() + 90
        while time.time() < deadline:
            body = httpx.get(f"http://127.0.0.1:{port}/api/runs/{run_id}", timeout=10).json()
            status = body["status"]
            if status not in {"pending", "running"}:
                break
            time.sleep(0.5)
        log_text = httpx.get(f"http://127.0.0.1:{port}/api/runs/{run_id}/logs", timeout=10).text
        assert status == "succeeded", {"body": body, "logs": log_text}
        assert "Doğu Anadolu" in body["summary"]["anomaly_regions"]
        assert body["report_markdown"]
        assert any(call["tool"] == "send_email" and call["status"] == "ok" for call in body["tool_calls"])
        assert "super-secret-mail-token" not in str(body)
        names = {item["name"] for item in body["artifacts"]}
        assert "report.md" in names
        assert "analysis.py" in names
        assert "query.sql" in names
        schedule = httpx.get(f"http://127.0.0.1:{port}/api/agents/{agent_id}", timeout=10).json()["schedule"]
        assert schedule["next_run_at"]
        logs = httpx.get(f"http://127.0.0.1:{port}/api/runs/{run_id}/logs", timeout=10).json()["text"]
        assert logs
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        os.environ["CONTROL_PLANE_PUBLIC_URL"] = "http://127.0.0.1:8841"
        os.environ["CONTROL_PLANE_INTERNAL_URL"] = "http://127.0.0.1:8841"
        get_settings.cache_clear()
        set_backend(None)


def test_kubernetes_backend_submits_to_a_fake_api(db, datasource, monkeypatch):
    import secrets

    import kubernetes.utils as k8s_utils

    from control_plane.backends import KubernetesBackend
    from control_plane.service import create_agent, hash_token

    created = {}

    def create_from_dict(api, data, verbose=False, namespace=None, **kwargs):
        created.setdefault("items", []).append(data)
        created["namespace"] = namespace
        meta = type("M", (), {"name": data["metadata"]["name"], "uid": "uid-1"})()
        return [type("O", (), {"metadata": meta})()]

    class FakeCore:
        def patch_namespaced_secret(self, name, namespace, body):
            created["patched"] = name

    class FakeBatch:
        def list_namespaced_job(self, *args, **kwargs):
            return type("L", (), {"items": []})()

    monkeypatch.setattr(k8s_utils, "create_from_dict", create_from_dict)
    backend = KubernetesBackend.__new__(KubernetesBackend)
    backend.api = object()
    backend.batch = FakeBatch()
    backend.core = FakeCore()
    backend.namespace = "agent-runs"
    agent = create_agent(db, EXAMPLE_SPEC, publish=True, actor="test")
    token = secrets.token_urlsafe(16)
    run = Run(
        agent_id=agent.id,
        agent_name=agent.name,
        spec_version=1,
        spec_snapshot=EXAMPLE_SPEC,
        trigger="manual",
        status="pending",
        dry_run=False,
        run_token_hash=hash_token(token),
    )
    db.add(run)
    db.commit()
    job_name = backend.submit(run.id, token)
    db.refresh(run)
    assert job_name.startswith("run-")
    assert run.status == "running"
    kinds = [item["kind"] for item in created["items"]]
    assert kinds == ["Secret", "Job"]
    job = created["items"][1]
    assert created["namespace"] == "agent-runs"
    assert created["items"][0]["metadata"]["namespace"] == "agent-runs"
    assert job["metadata"]["namespace"] == "agent-runs"
    assert job["spec"]["backoffLimit"] == 0
    assert job["spec"]["ttlSecondsAfterFinished"] == 600
    assert "agentrt" not in json.dumps(job["spec"]["template"]["spec"]["containers"][1])
    executor = job["spec"]["template"]["spec"]["containers"][1]
    assert "SALES_DATABASE_URL" not in str(executor.get("env"))
    assert created["patched"].startswith("run-")
