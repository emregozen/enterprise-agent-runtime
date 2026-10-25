"""Contract for the OpenAI-compatible client against a tiny local HTTP server.

No model weights. The server speaks Chat Completions, including the json_mode
fallback used for engines that reject response_format.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from shared.config import get_settings
from shared.llm import OpenAICompatibleLLM, make_llm, parse_json_response


class _ChatHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length)
        body = json.loads(raw.decode() or "{}")
        self.server.requests.append(  # type: ignore[attr-defined]
            {
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
                "body": body,
            }
        )
        if self.server.reject_json_mode and body.get("response_format"):  # type: ignore[attr-defined]
            payload = {"error": {"message": "response_format is unsupported", "type": "invalid_request_error"}}
            encoded = json.dumps(payload).encode()
            self.send_response(400)
        else:
            payload = {
                "id": "chatcmpl-contract",
                "object": "chat.completion",
                "created": 0,
                "model": body.get("model"),
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "{\"grand_total\": 10160}"},
                        "finish_reason": "stop",
                    }
                ],
            }
            encoded = json.dumps(payload).encode()
            self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def _server(reject_json_mode: bool) -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ChatHandler)
    server.requests = []  # type: ignore[attr-defined]
    server.reject_json_mode = reject_json_mode  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return server, f"http://{host}:{port}/v1"


def test_openai_client_sends_model_and_bearer_token():
    server, base_url = _server(reject_json_mode=False)
    try:
        llm = OpenAICompatibleLLM(base_url=base_url, api_key="contract-key", model="tiny-local", timeout=10)
        text = llm.complete([{"role": "user", "content": "özetle"}])
        parsed = parse_json_response(text)
        assert parsed["grand_total"] == 10160
        seen = server.requests[0]  # type: ignore[attr-defined]
        assert seen["path"].rstrip("/").endswith("/chat/completions")
        assert seen["authorization"] == "Bearer contract-key"
        assert seen["body"]["model"] == "tiny-local"
        assert seen["body"]["response_format"] == {"type": "json_object"}
    finally:
        server.shutdown()


def test_json_mode_falls_back_when_the_engine_rejects_it():
    server, base_url = _server(reject_json_mode=True)
    try:
        llm = OpenAICompatibleLLM(base_url=base_url, api_key="contract-key", model="tiny-local", timeout=10)
        text = llm.complete([{"role": "user", "content": "özetle"}])
        assert parse_json_response(text)["grand_total"] == 10160
        modes = [item["body"].get("response_format") for item in server.requests]  # type: ignore[attr-defined]
        assert modes[0] == {"type": "json_object"}
        assert modes[1] is None
    finally:
        server.shutdown()


def test_reasoning_effort_is_off_unless_configured():
    server, base_url = _server(reject_json_mode=False)
    try:
        plain = OpenAICompatibleLLM(base_url=base_url, api_key="contract-key", model="tiny-local", timeout=10)
        plain.complete([{"role": "user", "content": "özetle"}])
        assert "reasoning_effort" not in server.requests[0]["body"]  # type: ignore[attr-defined]
        low = OpenAICompatibleLLM(
            base_url=base_url,
            api_key="contract-key",
            model="tiny-local",
            timeout=10,
            reasoning_effort="low",
        )
        low.complete([{"role": "user", "content": "özetle"}])
        assert server.requests[-1]["body"]["reasoning_effort"] == "low"  # type: ignore[attr-defined]
        assert low.calls[-1]["latency_ms"] >= 0
    finally:
        server.shutdown()


def test_make_llm_uses_the_openai_compatible_client():
    server, base_url = _server(reject_json_mode=False)
    try:
        settings = get_settings().model_copy(
            update={
                "llm_mode": "openai",
                "llm_base_url": base_url,
                "llm_api_key": "contract-key",
                "llm_model": "tiny-local",
                "llm_model_classes": "",
            }
        )
        llm = make_llm(settings, "local-default")
        assert isinstance(llm, OpenAICompatibleLLM)
        assert parse_json_response(llm.complete([{"role": "user", "content": "özet"}]))["grand_total"] == 10160
    finally:
        server.shutdown()
