from __future__ import annotations

import json
import logging
import re
import time
from typing import Protocol


class LLM(Protocol):
    def complete(self, messages: list[dict]) -> str: ...


def parse_json_response(text: str) -> dict:
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start : end + 1]
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("LLM yanıtı JSON nesnesi değil")
    return data


class OpenAICompatibleLLM:
    """Chat Completions client. Works with vLLM, Ollama, and cloud OpenAI-compatible APIs."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 120,
        temperature: float = 0,
        reasoning_effort: str = "",
    ):
        from openai import OpenAI

        self.model = model
        self.temperature = temperature
        self.reasoning_effort = (reasoning_effort or "").strip()
        self.calls: list[dict] = []
        self.client = OpenAI(base_url=base_url, api_key=api_key or "not-set", timeout=timeout)

    def complete(self, messages: list[dict]) -> str:
        try:
            return self._call(messages, json_mode=True)
        except Exception as exc:
            message = str(exc).lower()
            if "response_format" in message or "json_object" in message or "unsupported" in message:
                return self._call(messages, json_mode=False)
            raise

    def _call(self, messages: list[dict], json_mode: bool) -> str:
        kwargs: dict = {"model": self.model, "messages": messages, "temperature": self.temperature}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if self.reasoning_effort:
            kwargs["extra_body"] = {"reasoning_effort": self.reasoning_effort}
        started = time.monotonic()
        response = self.client.chat.completions.create(**kwargs)
        usage = getattr(response, "usage", None)
        meta = {
            "model": getattr(response, "model", self.model),
            "latency_ms": int((time.monotonic() - started) * 1000),
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
        }
        self.calls.append(meta)
        logging.getLogger("llm").info(
            "llm.call model=%s json_mode=%s latency_ms=%d prompt_tokens=%s completion_tokens=%s total_tokens=%s",
            meta["model"],
            json_mode,
            meta["latency_ms"],
            meta["prompt_tokens"],
            meta["completion_tokens"],
            meta["total_tokens"],
        )
        content = response.choices[0].message.content or ""
        if not content.strip():
            raise RuntimeError("LLM boş yanıt döndürdü")
        return content


def make_llm(settings, model_class: str, fault_rounds: int = 0, provider: dict | None = None):
    if settings.llm_mode == "fake":
        from shared.fake_llm import FakeLLM

        return FakeLLM(fault_rounds=fault_rounds)
    resolved = provider or settings.resolve_model(model_class)
    temperature = resolved.get("temperature")
    if temperature is None:
        temperature = settings.llm_temperature
    return OpenAICompatibleLLM(
        base_url=resolved["base_url"],
        api_key=resolved.get("api_key") or "",
        model=resolved.get("model") or settings.llm_model,
        timeout=settings.llm_timeout_seconds,
        temperature=float(temperature),
        reasoning_effort=resolved.get("reasoning_effort") or settings.llm_reasoning_effort or "",
    )
