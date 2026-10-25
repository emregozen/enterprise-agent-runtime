"""A run that never started must not consume the daily cap."""

from __future__ import annotations

from datetime import timedelta

import pytest

from control_plane.backends import RunBackend, set_backend
from control_plane.models import DataSourceRecord, Run, Schedule, utcnow
from control_plane.seed import EXAMPLE_SPEC
from control_plane.service import ServiceError, _runs_today, create_agent, hash_token, trigger_run


def _agent(db):
    db.add(
        DataSourceRecord(
            name="postgres-sales",
            dialect="postgres",
            description="Satış",
            dsn_env="SALES_DATABASE_URL",
            allow_tables=["sales"],
            sensitivity="internal",
        )
    )
    db.commit()
    agent = create_agent(db, EXAMPLE_SPEC, publish=True, actor="quota")
    schedule = db.query(Schedule).filter(Schedule.agent_id == agent.id).one()
    schedule.max_runs_per_day = 1
    db.commit()
    return agent, schedule


def _run(db, agent, *, status: str, started: bool, dry_run: bool = False) -> None:
    db.add(
        Run(
            agent_id=agent.id,
            agent_name=agent.name,
            spec_version=1,
            spec_snapshot=EXAMPLE_SPEC,
            trigger="manual",
            status=status,
            dry_run=dry_run,
            started_at=utcnow() - timedelta(minutes=5) if started else None,
            finished_at=utcnow(),
            run_token_hash=hash_token("tok"),
            error="Job create failed" if status == "failed" else None,
        )
    )
    db.commit()


def test_runs_today_skips_failures_that_never_started(db):
    agent, schedule = _agent(db)
    _run(db, agent, status="failed", started=False)
    _run(db, agent, status="cancelled", started=True)
    _run(db, agent, status="failed", started=False, dry_run=True)
    assert _runs_today(db, agent.id, schedule.timezone) == 0
    _run(db, agent, status="failed", started=True)
    assert _runs_today(db, agent.id, schedule.timezone) == 1


def test_job_create_failure_leaves_room_for_another_run(db):
    agent, schedule = _agent(db)

    class Boom(RunBackend):
        def submit(self, run_id, token):
            raise RuntimeError("jobs.batch is forbidden: 502")

    set_backend(Boom())
    try:
        with pytest.raises(ServiceError) as caught:
            trigger_run(db, agent, trigger="manual", dry_run=False, actor="quota")
        assert caught.value.status_code == 502
        assert _runs_today(db, agent.id, schedule.timezone) == 0
        failed = db.query(Run).filter(Run.agent_id == agent.id).one()
        assert failed.status == "failed"
        assert failed.started_at is None
    finally:
        set_backend(None)
