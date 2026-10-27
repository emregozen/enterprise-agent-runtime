"""Re-encrypt stored secrets with the current CONFIG_MASTER_KEY.

Decrypt accepts CONFIG_MASTER_KEY and CONFIG_MASTER_KEY_OLD (comma-separated).
Encrypt always uses CONFIG_MASTER_KEY. Keys stay in the environment, never on argv.

A bare invocation only counts. Writing requires --yes.

    CONFIG_MASTER_KEY=new CONFIG_MASTER_KEY_OLD=old python -m control_plane.rotate_master_key --yes
"""

from __future__ import annotations

import argparse
import sys

from shared.config import get_settings
from shared.crypto import decrypt_secret, encrypt_secret


class RotationError(RuntimeError):
    pass


def rotate_stored_secrets(db, dry_run: bool = False) -> dict:
    settings = get_settings()
    if not (settings.config_master_key or "").strip():
        raise RotationError("CONFIG_MASTER_KEY boş; döndürme geliştirme anahtarına yazmaz")
    from control_plane.models import DataSourceRecord, DeliveryChannel, LlmProvider

    rewritten = 0
    for row in db.query(DataSourceRecord).all():
        rewritten += _rewrite(row, "password_ciphertext", row.name, dry_run=dry_run)
    for row in db.query(LlmProvider).all():
        rewritten += _rewrite(row, "api_key_ciphertext", row.name, dry_run=dry_run)
    for row in db.query(DeliveryChannel).all():
        rewritten += _rewrite(row, "credential_ciphertext", row.name, dry_run=dry_run)
    if dry_run:
        db.rollback()
    else:
        db.commit()
    return {"rewritten": rewritten, "dry_run": dry_run}


def _rewrite(row, attr: str, name: str, dry_run: bool = False) -> int:
    token = getattr(row, attr) or ""
    if not token:
        return 0
    try:
        plain = decrypt_secret(token)
    except RuntimeError as exc:
        raise RotationError(f"{name} çözülemedi; eski anahtar CONFIG_MASTER_KEY_OLD içinde olmalı") from exc
    if not dry_run:
        setattr(row, attr, encrypt_secret(plain))
    return 1


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m control_plane.rotate_master_key",
        description=(
            "Kayıtlı parola ve API anahtarı alanlarını CONFIG_MASTER_KEY ile yeniden şifreler. "
            "Anahtarlar ortam değişkenindedir, argümana yazılmaz. Argümansız çağrı yalnız sayar."
        ),
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--yes", action="store_true", help="Alanları yeniden şifrele ve kaydet")
    group.add_argument("--dry-run", action="store_true", help="Yalnız say; veritabanına yazma (varsayılan)")
    args = parser.parse_args(argv)
    dry_run = not args.yes
    from control_plane.db import SessionLocal

    db = SessionLocal()
    try:
        result = rotate_stored_secrets(db, dry_run=dry_run)
    except RotationError as exc:
        db.rollback()
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    finally:
        db.close()
    if result["dry_run"]:
        print(f"yeniden şifrelenen alan: {result['rewritten']} (kuru çalıştırma)")
    else:
        print(f"yeniden şifrelenen alan: {result['rewritten']}")


if __name__ == "__main__":
    main()
