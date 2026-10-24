from __future__ import annotations

import logging

from control_plane.backends import get_backend
from control_plane.db import SessionLocal
from control_plane.models import Run, utcnow
from control_plane.service import claim_due
from shared.config import get_settings

log = logging.getLogger("control-plane.scheduler")


def tick() -> int:
    settings = get_settings()
    backend = get_backend()
    if not settings.scheduler_enabled:
        backend.reconcile()
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
    return len(created)
