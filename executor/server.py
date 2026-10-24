from __future__ import annotations

import json
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


def run_code(code: str, workdir: str, timeout_seconds: int) -> dict:
    root = Path(workdir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    script = root / "analysis.py"
    output_path = root / "output.json"
    if output_path.exists():
        output_path.unlink()
    script.write_text(code, encoding="utf-8")
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": "/tmp",
        "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONNOUSERSITE": "1",
        "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "WORKDIR": str(root),
    }
    process = subprocess.Popen(
        [sys.executable, "-I", str(script)],
        cwd=str(root),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
        timed_out = True
    stdout_text = stdout.decode("utf-8", "replace")[-8000:]
    stderr_text = stderr.decode("utf-8", "replace")[-8000:]
    output = None
    parse_error = None
    if output_path.exists():
        try:
            output = json.loads(output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            parse_error = str(exc)
    ok = process.returncode == 0 and output is not None and not timed_out and parse_error is None
    error = None
    if timed_out:
        error = f"kod {timeout_seconds} saniye sınırını aştı"
    elif parse_error:
        error = f"output.json okunamadı: {parse_error}"
    elif process.returncode != 0:
        error = f"kod çıkış kodu {process.returncode}"
    elif output is None:
        error = "kod /work/output.json yazmadı"
    return {
        "ok": ok,
        "returncode": process.returncode,
        "stdout": stdout_text,
        "stderr": stderr_text,
        "output": output,
        "error": error,
    }


class _Handler(BaseHTTPRequestHandler):
    server_version = "agent-executor/0.2"

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write(json.dumps({"logger": "executor", "msg": fmt % args}) + "\n")

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] == "/healthz":
            self._send(200, {"ok": True})
            return
        self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._send(400, {"ok": False, "error": "json geçersiz"})
            return
        if path == "/v1/shutdown":
            self._send(200, {"ok": True})
            self.server.stop = True  # type: ignore[attr-defined]
            return
        if path != "/v1/execute":
            self._send(404, {"ok": False, "error": "not found"})
            return
        code = body.get("code")
        if not isinstance(code, str) or not code.strip():
            self._send(400, {"ok": False, "error": "code zorunlu"})
            return
        timeout = int(body.get("timeout_seconds") or 60)
        timeout = max(1, min(timeout, 1800))
        result = run_code(code, self.server.workdir, timeout)  # type: ignore[attr-defined]
        self._send(200, result)


class ExecutorServer(HTTPServer):
    allow_reuse_address = True
    timeout = 1

    def __init__(self, host: str, port: int, workdir: str):
        super().__init__((host, port), _Handler)
        self.workdir = str(Path(workdir).expanduser().resolve())
        self.stop = False


def serve(host: str, port: int, workdir: str) -> None:
    server = ExecutorServer(host, port, workdir)
    while not server.stop:
        server.handle_request()
    server.server_close()
