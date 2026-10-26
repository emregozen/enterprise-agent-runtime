"""Short in-memory cache. Failures are not cached. Values are not logged."""

from __future__ import annotations

import threading
import time

_lock = threading.Lock()
_store: dict[str, tuple[float, str]] = {}


def cache_get(key: str) -> str | None:
    now = time.monotonic()
    with _lock:
        item = _store.get(key)
        if item is None:
            return None
        expires, value = item
        if expires <= now:
            _store.pop(key, None)
            return None
        return value


def cache_put(key: str, value: str, ttl: float) -> None:
    if not value or ttl <= 0:
        return
    with _lock:
        _store[key] = (time.monotonic() + ttl, value)


def cache_clear() -> None:
    with _lock:
        _store.clear()
