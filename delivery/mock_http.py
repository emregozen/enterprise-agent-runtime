"""A tiny HTTP catcher for the corporate email API shape. Tests and local demos."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread


def serve(port: int = 0):
    inbox: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length)
            try:
                body = json.loads(raw.decode() or "{}")
            except json.JSONDecodeError:
                body = {"raw": raw.decode(errors="replace")}
            inbox.append(
                {
                    "path": self.path,
                    "body": body,
                    "authorization": self.headers.get("Authorization", ""),
                    "content_type": self.headers.get("Content-Type", ""),
                }
            )
            data = b'{"ok":true}'
            self.send_response(202)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, fmt: str, *args) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.inbox = inbox  # type: ignore[attr-defined]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


if __name__ == "__main__":
    import sys
    from threading import Event

    chosen = int(sys.argv[1]) if len(sys.argv) > 1 else 8899
    running = serve(chosen)
    host, bound = running.server_address
    print(f"mock email api on http://{host}:{bound}", flush=True)
    try:
        Event().wait()
    except KeyboardInterrupt:
        running.shutdown()
