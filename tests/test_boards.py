from __future__ import annotations

from fastapi.testclient import TestClient

from control_plane.main import create_app
from control_plane.models import Agent, Run, utcnow


def _agent(db, name: str) -> Agent:
    agent = Agent(name=name, status="active")
    db.add(agent)
    db.commit()
    return agent


def _run(db, agent: Agent, status: str, report: str | None = None, error: str | None = None) -> Run:
    run = Run(
        agent_id=agent.id,
        agent_name=agent.name,
        spec_version=1,
        spec_snapshot={},
        trigger="manual",
        status=status,
        run_token_hash="x",
        report_markdown=report,
        error=error,
        created_at=utcnow(),
    )
    db.add(run)
    db.commit()
    return run


def test_board_crud_and_snapshot_states(db):
    ok, failing, busy, fresh = (_agent(db, n) for n in ("ok-agent", "failing-agent", "busy-agent", "fresh-agent"))
    _run(db, ok, "succeeded", report="# ok")
    _run(db, failing, "succeeded", report="# old")
    _run(db, failing, "failed", error="boom")
    _run(db, busy, "succeeded", report="# prev")
    _run(db, busy, "running")
    with TestClient(create_app()) as client:
        created = client.post(
            "/api/boards",
            json={"name": "Daily", "widgets": [{"agent_id": str(a.id)} for a in (ok, failing, busy, fresh)]},
        )
        assert created.status_code == 201, created.text
        board_id = created.json()["id"]
        snap = client.get(f"/api/boards/{board_id}/snapshot").json()
        by_name = {w["agent_name"]: w for w in snap["widgets"]}
        assert by_name["ok-agent"]["state"] == "ok"
        assert by_name["ok-agent"]["result"]["report_markdown"] == "# ok"
        failed = by_name["failing-agent"]
        assert failed["state"] == "failed"
        assert failed["stale"]["has_older_result"] is True and failed["stale"]["reason"] == "boom"
        assert failed["result"]["report_markdown"] == "# old"
        assert by_name["busy-agent"]["state"] == "running"
        assert by_name["busy-agent"]["active_run"]["status"] == "running"
        assert by_name["busy-agent"]["result"]["report_markdown"] == "# prev"
        assert by_name["fresh-agent"]["state"] == "empty"

        patched = client.patch(f"/api/boards/{board_id}", json={"name": "Renamed", "widgets": [{"agent_id": str(ok.id), "size": "lg"}]})
        assert patched.status_code == 200
        assert patched.json()["name"] == "Renamed" and patched.json()["widgets"][0]["size"] == "lg"
        assert len(client.get("/api/boards").json()) == 1
        assert client.delete(f"/api/boards/{board_id}").status_code == 204
        assert client.get(f"/api/boards/{board_id}").status_code == 404


def test_board_rejects_unknown_agent(db):
    with TestClient(create_app()) as client:
        res = client.post("/api/boards", json={"name": "x", "widgets": [{"agent_id": "00000000-0000-4000-8000-0000000000aa"}]})
        assert res.status_code == 404


def test_chart_data_flag_extends_the_planning_goal_only():
    from shared.spec import AgentSpec, CHART_DATA_INSTRUCTION, goal_for_planning

    assert goal_for_planning("Satışları özetle", False) == "Satışları özetle"
    extended = goal_for_planning("Satışları özetle", True)
    assert extended.startswith("Satışları özetle") and CHART_DATA_INSTRUCTION in extended
    spec = AgentSpec.model_validate(
        {
            "metadata": {"name": "a", "version": 1},
            "spec": {
                "goal": "Satışları özetle",
                "datasources": [{"ref": "x", "allowTables": ["sales"]}],
                "output": {"chartData": True},
            },
        }
    ).canonical()
    assert spec["spec"]["output"]["chartData"] is True
    assert spec["spec"]["goal"] == "Satışları özetle"
