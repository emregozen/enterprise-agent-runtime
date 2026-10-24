import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

from control_plane.models import Run
from control_plane.tool_proxy import ToolError, invoke_tool
from shared.spec import AgentSpec
from tests.test_spec_and_policy import SPEC


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_executor_child_cannot_see_secrets(tmp_path: Path):
    port = _free_port()
    env = {
        "PATH": __import__("os").environ["PATH"],
        "HOME": "/tmp",
        "LANG": "C.UTF-8",
        "PYTHONNOUSERSITE": "1",
        "PYTHONUNBUFFERED": "1",
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "executor", "serve", "--host", "127.0.0.1", "--port", str(port), "--workdir", str(tmp_path)],
        env=env,
    )
    try:
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                if httpx.get(f"http://127.0.0.1:{port}/healthz", timeout=0.3).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.05)
        code = r"""
import json, os
from pathlib import Path
blob = json.dumps(dict(os.environ))
Path("output.json").write_text(json.dumps({"grand_total": 0, "env": blob}))
"""
        response = httpx.post(
            f"http://127.0.0.1:{port}/v1/execute",
            json={"code": code, "timeout_seconds": 15},
            timeout=20,
        )
        body = response.json()
        assert body["ok"]
        env_blob = body["output"]["env"]
        assert "SALES_DATABASE_URL" not in env_blob
        assert "super-secret-mail-token" not in env_blob
        assert "RUN_TOKEN" not in env_blob
        httpx.post(f"http://127.0.0.1:{port}/v1/shutdown", timeout=3)
    finally:
        process.wait(timeout=5)


def test_tool_proxy_mocks_email_and_hides_token(db, datasource):
    spec = AgentSpec.model_validate(SPEC).canonical()
    run = Run(
        agent_id=datasource.id,
        agent_name="gunluk-satis-ozeti",
        spec_version=1,
        spec_snapshot=spec,
        trigger="manual",
        status="running",
        dry_run=False,
        run_token_hash="x" * 64,
    )
    # agent_id FK points at agents, not datasources. Create a real agent.
    db.rollback()
    from control_plane.seed import EXAMPLE_SPEC
    from control_plane.service import create_agent, trigger_run
    from control_plane.backends import set_backend, RecordingBackend

    set_backend(RecordingBackend())
    agent = create_agent(db, EXAMPLE_SPEC, publish=True, actor="test")
    run, _token = trigger_run(db, agent, trigger="manual", dry_run=False, actor="test")
    db.refresh(run)
    result = invoke_tool(
        db,
        run,
        "send_email",
        {"to": "finans@sirket.local", "subject": "özet", "body": "toplam 10"},
    )
    assert result["mode"] == "mock"
    assert "super-secret-mail-token" not in json.dumps(result)
    try:
        invoke_tool(db, run, "send_email", {"to": "evil@example.com", "subject": "x", "body": "y"})
        raise AssertionError("expected rejection")
    except ToolError as exc:
        assert exc.status_code == 403
    run.dry_run = True
    db.commit()
    try:
        invoke_tool(db, run, "send_email", {"to": "finans@sirket.local", "subject": "x", "body": "y"})
        raise AssertionError("dry run should not send")
    except ToolError as exc:
        assert exc.status_code == 409


def test_needs_review_run_cannot_notify(db, datasource):
    from control_plane.backends import RecordingBackend, set_backend
    from control_plane.seed import EXAMPLE_SPEC
    from control_plane.service import create_agent, trigger_run

    set_backend(RecordingBackend())
    agent = create_agent(db, EXAMPLE_SPEC, publish=True, actor="test")
    run, _token = trigger_run(db, agent, trigger="manual", dry_run=False, actor="test")
    db.refresh(run)
    run.status = "needs_review"
    db.commit()
    try:
        invoke_tool(db, run, "send_email", {"to": "finans@sirket.local", "subject": "x", "body": "y"})
        raise AssertionError("needs_review must not notify")
    except ToolError as exc:
        assert exc.status_code == 409
