"""UI-managed configuration and agent/run lifecycle."""

from __future__ import annotations

from fastapi.testclient import TestClient

from control_plane.backends import RecordingBackend, set_backend
from control_plane.main import create_app
from control_plane.models import Run
from control_plane.service import _runs_today


def test_sources_models_and_agent_lifecycle(datasource, db):
    set_backend(RecordingBackend())
    try:
        with TestClient(create_app()) as client:
            created = client.post(
                "/api/datasources",
                json={
                    "name": "satis-canli",
                    "dialect": "postgres",
                    "description": "Canlı satış",
                    "allow_tables": ["sales"],
                    "host": "127.0.0.1",
                    "port": 5432,
                    "database_name": "agentrt_test",
                    "username": "agentrt",
                    "password": "agentrt",
                    "read_only": True,
                },
            )
            assert created.status_code == 201, created.text
            body = created.json()
            assert body["password_set"] is True
            assert "password" not in body
            assert body["password_hint"] == "••••ntrt"
            source_id = body["id"]
            tested = client.post(f"/api/datasources/{source_id}/test")
            assert tested.status_code == 200, tested.text
            assert tested.json()["ok"] is True

            listed = client.get("/api/datasources")
            sales = next(item for item in listed.json() if item["name"] == "postgres-sales")
            provider = client.post(
                "/api/llm/providers",
                json={
                    "name": "deepseek-flash",
                    "base_url": "https://api.deepseek.com",
                    "model": "deepseek-flash",
                    "api_key": "sk-test-secret-value",
                    "reasoning_effort": "",
                    "is_default": True,
                },
            )
            assert provider.status_code == 201, provider.text
            assert "sk-test-secret-value" not in provider.text
            assert provider.json()["api_key_set"] is True
            assert provider.json()["reasoning_effort"] == ""

            draft = client.post(
                "/api/builder/draft",
                json={
                    "description": "Hafta içi her sabah dünkü satışları bölge bazında özetle ve e-posta gönder.",
                    "owner": "finans",
                    "datasource_refs": [sales["id"]],
                    "model_ref": "deepseek-flash",
                },
            )
            assert draft.status_code == 200, draft.text
            spec = draft.json()["spec"]
            assert spec["spec"]["model"]["class"] == "deepseek-flash"
            agent = client.post("/api/agents", json={"spec": spec, "publish": True})
            assert agent.status_code == 201, agent.text
            agent_id = agent.json()["id"]

            first = client.post(f"/api/agents/{agent_id}/runs", json={})
            assert first.status_code == 202, first.text
            run_id = first.json()["id"]
            cancelled = client.post(f"/api/runs/{run_id}/cancel")
            assert cancelled.status_code == 200, cancelled.text
            assert cancelled.json()["status"] == "cancelled"
            row = db.get(Run, __import__("uuid").UUID(run_id))
            db.refresh(row)
            assert _runs_today(db, row.agent_id, "Europe/Istanbul") == 0

            again = client.post(f"/api/runs/{run_id}/rerun")
            assert again.status_code == 202, again.text
            second_id = again.json()["id"]

            spec["spec"]["goal"] = spec["spec"]["goal"] + " Kısa tut."
            edited = client.patch(f"/api/agents/{agent_id}", json={"spec": spec, "publish": True})
            assert edited.status_code == 200, edited.text
            assert edited.json()["version"] == 2
            diff = client.get(f"/api/agents/{agent_id}/diff", params={"left": 1, "right": 2})
            assert diff.status_code == 200
            assert "Kısa tut" in diff.json()["diff"]

            copied = client.post(f"/api/agents/{agent_id}/duplicate")
            assert copied.status_code == 201, copied.text
            assert copied.json()["schedule"]["paused"] is True

            removed = client.delete(f"/api/runs/{second_id}")
            assert removed.status_code == 204
            assert client.get(f"/api/runs/{second_id}").status_code == 404

            assert client.delete(f"/api/agents/{agent_id}").status_code == 204
            names = [item["name"] for item in client.get("/api/agents").json()]
            assert agent.json()["name"] not in names
            board = client.get("/api/dashboard")
            assert board.status_code == 200
            assert "tokens_today" in board.json()
            settings = client.get("/api/settings")
            assert settings.json()["egress"]["mode"] == "networkpolicy"
            assert "encryption_configured" in settings.json()
    finally:
        set_backend(None)
