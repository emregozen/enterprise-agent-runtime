from __future__ import annotations

import json
import re
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

    def __init__(self, *, base_url: str, api_key: str, model: str, timeout: float = 120):
        from openai import OpenAI

        self.model = model
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
        kwargs = {"model": self.model, "messages": messages, "temperature": 0}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        response = self.client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content or ""
        if not content.strip():
            raise RuntimeError("LLM boş yanıt döndürdü")
        return content


def make_llm(settings, model_class: str, fault_rounds: int = 0):
    if settings.llm_mode == "fake":
        from shared.fake_llm import FakeLLM

        return FakeLLM(fault_rounds=fault_rounds)
    resolved = settings.resolve_model(model_class)
    return OpenAICompatibleLLM(
        base_url=resolved["base_url"],
        api_key=resolved["api_key"],
        model=resolved["model"],
        timeout=settings.llm_timeout_seconds,
    )
