from __future__ import annotations

import logging
import time

from control_plane.backends import get_backend
from control_plane.db import SessionLocal
from control_plane.models import Run, utcnow
from control_plane.service import claim_due, purge_expired_artifacts
from shared.config import get_settings

log = logging.getLogger("control-plane.scheduler")
_purged_at = 0.0


def _maybe_purge() -> None:
    global _purged_at
    now = time.monotonic()
    if now - _purged_at < 3600:
        return
    _purged_at = now
    db = SessionLocal()
    try:
        removed = purge_expired_artifacts(db)
        if removed:
            log.info("eski artefakt silindi: %s", removed)
    except Exception:
        log.exception("artefakt temizliği başarısız")
    finally:
        db.close()


def tick() -> int:
    settings = get_settings()
    backend = get_backend()
    if not settings.scheduler_enabled:
        backend.reconcile()
        _maybe_purge()
        return 0
    db = SessionLocal()
    created: list[tuple] = []
    try:
        with db.begin():
            created = claim_due(db)
    finally:
        db.close()
    for run_id, token in created:
        try:
            backend.submit(run_id, token)
        except Exception as exc:  # noqa: BLE001
            log.exception("submit failed")
            failed = SessionLocal()
            try:
                run = failed.get(Run, run_id)
                if run is not None and run.status in {"pending", "running"}:
                    run.status = "failed"
                    run.error = str(exc)
                    run.finished_at = utcnow()
                    failed.commit()
            finally:
                failed.close()
    backend.reconcile()
    _maybe_purge()
    return len(created)
