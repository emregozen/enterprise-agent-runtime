from __future__ import annotations


def iso(value) -> str | None:
    return value.isoformat() if value else None


def agent_out(agent, schedule=None, goal: str | None = None) -> dict:
    return {
        "id": str(agent.id),
        "name": agent.name,
        "description": agent.description,
        "owner": agent.owner,
        "status": agent.status,
        "current_version": agent.current_version,
        "goal": goal if goal is not None else agent.description,
        "schedule": schedule_out(schedule) if schedule is not None else None,
        "created_at": iso(agent.created_at),
        "updated_at": iso(agent.updated_at),
    }


def schedule_out(schedule) -> dict | None:
    if schedule is None:
        return None
    return {
        "mode": schedule.mode,
        "cron": schedule.cron,
        "time_zone": schedule.timezone,
        "next_run_at": iso(schedule.next_run_at),
        "paused": schedule.paused,
        "min_interval_seconds": schedule.min_interval_seconds,
        "max_interval_seconds": schedule.max_interval_seconds,
        "max_runs_per_day": schedule.max_runs_per_day,
        "window": schedule.window,
        "concurrency": schedule.concurrency,
    }


def run_out(run) -> dict:
    summary = run.summary or {}
    return {
        "id": str(run.id),
        "agent_id": str(run.agent_id),
        "agent_name": run.agent_name,
        "spec_version": run.spec_version,
        "trigger": run.trigger,
        "status": run.status,
        "dry_run": run.dry_run,
        "job_name": run.job_name,
        "summary": summary,
        "error": run.error,
        "needs_review_reason": run.needs_review_reason,
        "created_at": iso(run.created_at),
        "started_at": iso(run.started_at),
        "finished_at": iso(run.finished_at),
        "grand_total": summary.get("grand_total"),
        "anomaly_regions": summary.get("anomaly_regions") or [],
    }


def spec_summary(spec: dict) -> dict:
    body = spec["spec"]
    return {
        "name": spec["metadata"]["name"],
        "owner": spec["metadata"]["owner"],
        "version": spec["metadata"]["version"],
        "goal": body["goal"],
        "model": body.get("model", {}).get("class"),
        "datasources": [item["ref"] for item in body["datasources"]],
        "tools": body.get("tools") or [],
        "schedule": body.get("schedule"),
        "verification": body.get("verification"),
        "runtime": body.get("runtime"),
    }
