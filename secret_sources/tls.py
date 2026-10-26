"""Temporary PEM files for a provider call. Deleted when the call finishes."""

from __future__ import annotations

import os
import tempfile


class TlsMaterial:
    def __init__(self, *, ca_pem: str = "", cert_pem: str = "", key_pem: str = ""):
        self._paths: list[str] = []
        self.verify: bool | str = True
        self.cert: tuple[str, str] | None = None
        if ca_pem.strip():
            self.verify = self._write(ca_pem)
        if cert_pem.strip() and key_pem.strip():
            self.cert = (self._write(cert_pem), self._write(key_pem))

    def _write(self, content: str) -> str:
        fd, path = tempfile.mkstemp(prefix="pam-", suffix=".pem")
        os.chmod(path, 0o600)
        text = content if content.endswith("\n") else content + "\n"
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        self._paths.append(path)
        return path

    def close(self) -> None:
        for path in self._paths:
            try:
                os.remove(path)
            except OSError:
                pass
        self._paths.clear()

    def __enter__(self) -> TlsMaterial:
        return self

    def __exit__(self, *_args) -> None:
        self.close()
