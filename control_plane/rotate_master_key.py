"""Re-encrypt stored secrets with the current CONFIG_MASTER_KEY.

Decrypt accepts CONFIG_MASTER_KEY and CONFIG_MASTER_KEY_OLD (comma-separated).
Encrypt always uses CONFIG_MASTER_KEY. Keys stay in the environment, never on argv.

    CONFIG_MASTER_KEY=new CONFIG_MASTER_KEY_OLD=old python -m control_plane.rotate_master_key
"""

from __future__ import annotations

import sys

from shared.config import get_settings
from shared.crypto import decrypt_secret, encrypt_secret


class RotationError(RuntimeError):
    pass


def rotate_stored_secrets(db) -> dict:
    settings = get_settings()
    if not (settings.config_master_key or "").strip():
        raise RotationError("CONFIG_MASTER_KEY boş; döndürme geliştirme anahtarına yazmaz")
    from control_plane.models import DataSourceRecord, LlmProvider

    rewritten = 0
    for row in db.query(DataSourceRecord).all():
        rewritten += _rewrite(row, "password_ciphertext", row.name)
    for row in db.query(LlmProvider).all():
        rewritten += _rewrite(row, "api_key_ciphertext", row.name)
    db.commit()
    return {"rewritten": rewritten}


def _rewrite(row, attr: str, name: str) -> int:
    token = getattr(row, attr) or ""
    if not token:
        return 0
    try:
        plain = decrypt_secret(token)
    except RuntimeError as exc:
        raise RotationError(f"{name} çözülemedi; eski anahtar CONFIG_MASTER_KEY_OLD içinde olmalı") from exc
    setattr(row, attr, encrypt_secret(plain))
    return 1


def main() -> None:
    from control_plane.db import SessionLocal

    db = SessionLocal()
    try:
        result = rotate_stored_secrets(db)
    except RotationError as exc:
        db.rollback()
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    finally:
        db.close()
    print(f"yeniden şifrelenen alan: {result['rewritten']}")


if __name__ == "__main__":
    main()
