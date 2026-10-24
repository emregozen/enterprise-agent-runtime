from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from control_plane.policy import compute_next_cron, evaluate_self_schedule
from shared.spec import AgentSpec

SPEC = {
    "apiVersion": "agents.internal/v1",
    "kind": "AgentSpec",
    "metadata": {"name": "gunluk-satis-ozeti", "version": 1, "owner": "finans-ekibi"},
    "spec": {
        "goal": "Dünkü satışları bölge bazında özetle ve sapmaları açıkla.",
        "model": {"class": "local-default"},
        "datasources": [{"ref": "postgres-sales", "allowTables": ["sales"]}],
        "tools": ["send_email"],
        "schedule": {
            "mode": "hybrid",
            "cron": "0 7 * * 1-5",
            "timeZone": "Europe/Istanbul",
            "selfScheduling": {"minInterval": "1h", "maxInterval": "7d", "maxRunsPerDay": 4, "window": "07:00-20:00"},
        },
        "output": {"notify": ["send_email"]},
        "verification": {"crossCheckSql": True, "maxRepairRounds": 2},
    },
}


def test_spec_round_trip_uses_class_alias():
    spec = AgentSpec.model_validate(SPEC)
    data = spec.canonical()
    assert data["spec"]["model"]["class"] == "local-default"
    assert spec.sensitivity_allows_model(["restricted"]) is True
    cloud = AgentSpec.model_validate(SPEC)
    cloud.spec.model.class_ = "cloud-strong"
    assert cloud.sensitivity_allows_model(["restricted"]) is False


def test_spec_rejects_unknown_tool_and_bad_cron():
    broken = json_copy(SPEC)
    broken["spec"]["tools"] = ["shell"]
    with pytest.raises(ValidationError):
        AgentSpec.model_validate(broken)
    broken = json_copy(SPEC)
    broken["spec"]["schedule"]["cron"] = "not a cron"
    with pytest.raises(ValidationError):
        AgentSpec.model_validate(broken)


def test_weekday_cron_from_saturday_lands_on_monday_morning():
    zone = ZoneInfo("Europe/Istanbul")
    saturday = datetime(2026, 10, 24, 12, 0, tzinfo=zone)
    nxt = compute_next_cron("0 7 * * 1-5", "Europe/Istanbul", saturday)
    local = nxt.astimezone(zone)
    assert local.weekday() == 0
    assert (local.hour, local.minute) == (7, 0)
    assert local.date().isoformat() == "2026-10-26"


def test_self_schedule_clamps_to_window_and_min_interval():
    zone = ZoneInfo("Europe/Istanbul")
    now = datetime(2026, 10, 21, 21, 30, tzinfo=zone)
    requested = now + timedelta(minutes=10)
    decision = evaluate_self_schedule(
        now=now,
        requested=requested,
        min_interval_seconds=3600,
        max_interval_seconds=7 * 86400,
        window="07:00-20:00",
        tz_name="Europe/Istanbul",
        last_run_at=now - timedelta(minutes=30),
        runs_today=1,
        max_runs_per_day=4,
    )
    assert decision.accepted
    local = decision.at.astimezone(zone)
    assert local.hour == 7
    assert local.date() == datetime(2026, 10, 22).date()


def test_self_schedule_rejects_when_window_exceeds_max_interval():
    zone = ZoneInfo("Europe/Istanbul")
    now = datetime(2026, 10, 21, 21, 30, tzinfo=zone)
    decision = evaluate_self_schedule(
        now=now,
        requested=now,
        min_interval_seconds=60,
        max_interval_seconds=30 * 60,
        window="07:00-20:00",
        tz_name="Europe/Istanbul",
        last_run_at=None,
        runs_today=0,
        max_runs_per_day=4,
    )
    assert not decision.accepted


def test_daily_cap_blocks_another_run_today_but_not_tomorrow():
    zone = ZoneInfo("Europe/Istanbul")
    now = datetime(2026, 10, 21, 9, 0, tzinfo=zone)
    blocked = evaluate_self_schedule(
        now=now,
        requested=now + timedelta(hours=2),
        min_interval_seconds=60,
        max_interval_seconds=7 * 86400,
        window="07:00-20:00",
        tz_name="Europe/Istanbul",
        last_run_at=now - timedelta(hours=3),
        runs_today=4,
        max_runs_per_day=4,
    )
    assert not blocked.accepted
    allowed = evaluate_self_schedule(
        now=now,
        requested=now + timedelta(days=1),
        min_interval_seconds=60,
        max_interval_seconds=7 * 86400,
        window="07:00-20:00",
        tz_name="Europe/Istanbul",
        last_run_at=now - timedelta(hours=3),
        runs_today=4,
        max_runs_per_day=4,
    )
    assert allowed.accepted


def json_copy(payload):
    import json

    return json.loads(json.dumps(payload))
