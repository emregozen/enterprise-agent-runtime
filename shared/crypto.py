"""Encrypt secrets at rest. The master key never goes into the database or the logs."""

from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

_log = logging.getLogger("crypto")
_warned = False


def _material(raw: str) -> bytes:
    text = raw.strip()
    try:
        Fernet(text.encode())
        return text.encode()
    except Exception:
        digest = hashlib.sha256(text.encode()).digest()
        return base64.urlsafe_b64encode(digest)


def master_key_values() -> list[str]:
    """Current key first, then previous keys. The first key is the one we encrypt with."""
    from shared.config import get_settings

    settings = get_settings()
    current = (settings.config_master_key or "").strip()
    previous = [part.strip() for part in (settings.config_master_key_old or "").split(",") if part.strip()]
    keys: list[str] = []
    if current:
        keys.append(current)
    for key in previous:
        if key not in keys:
            keys.append(key)
    return keys


def _fernet() -> MultiFernet:
    global _warned
    keys = master_key_values()
    if not keys:
        keys = ["dev-only-master-key"]
        if not _warned:
            _log.warning("CONFIG_MASTER_KEY boş; geliştirme anahtarı kullanılıyor")
            _warned = True
    return MultiFernet([Fernet(_material(key)) for key in keys])


def encrypt_secret(value: str) -> str:
    if not value:
        return ""
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(token: str) -> str:
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise RuntimeError("gizli alan çözülemedi; CONFIG_MASTER_KEY değişmiş olabilir") from exc


def secret_hint(value: str) -> str:
    """Mask a stored secret. Last four characters only for long API keys."""
    if not value:
        return ""
    if len(value) > 20:
        return f"••••{value[-4:]}"
    return "••••"


def public_hint(ciphertext: str, stored: str = "") -> str:
    """Hint for an API response. Never returns a stored suffix of a short secret."""
    if ciphertext:
        try:
            return secret_hint(decrypt_secret(ciphertext))
        except Exception:
            return "••••"
    return "••••" if stored else ""


def redact(text: str, secrets: list[str]) -> str:
    rendered = text
    for secret in secrets:
        if secret and len(secret) >= 4:
            rendered = rendered.replace(secret, "***")
    return rendered
