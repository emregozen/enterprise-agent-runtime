"""The harness asks the executor to exit even when the run itself fails."""

from __future__ import annotations

import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading

from harness.__main__ import _stop_executor


def test_stop_executor_posts_shutdown(monkeypatch):
    seen = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            seen["path"] = self.path
            self.send_response(200)
            self.end_headers()

        def log_message(self, fmt, *args):
            return None

    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    monkeypatch.setenv("EXECUTOR_URL", f"http://127.0.0.1:{port}")
    try:
        _stop_executor(logging.getLogger("test-harness"))
        thread.join(3)
        assert seen["path"] == "/v1/shutdown"
    finally:
        server.server_close()


def test_stop_executor_swallows_a_dead_executor():
    _stop_executor(logging.getLogger("test-harness"))
