"""Pluggable secret providers. Values are resolved in memory and never logged."""

from __future__ import annotations

import logging

# A debug control plane must not record API keys or tokens that travel in headers.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
