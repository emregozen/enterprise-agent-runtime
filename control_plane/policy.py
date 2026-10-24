from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from croniter import croniter


@dataclass
class ScheduleDecision:
    accepted: bool
    at: datetime | None
    adjustments: list[str] = field(default_factory=list)
    rejection: str | None = None


def compute_next_cron(expression: str, tz_name: str, after: datetime) -> datetime:
    zone = ZoneInfo(tz_name)
    base = after.astimezone(zone)
    nxt = croniter(expression, base).get_next(datetime)
    if nxt.tzinfo is None:
        nxt = nxt.replace(tzinfo=zone)
    return nxt.astimezone(ZoneInfo("UTC"))


def advance_past_today(expression: str, tz_name: str, now: datetime) -> datetime:
    zone = ZoneInfo(tz_name)
    today = now.astimezone(zone).date()
    candidate = compute_next_cron(expression, tz_name, now)
    for _ in range(16):
        if candidate.astimezone(zone).date() > today:
            return candidate
        candidate = compute_next_cron(expression, tz_name, candidate + timedelta(seconds=1))
    return candidate


def _align_window(at: datetime, window: str, zone: ZoneInfo) -> tuple[datetime, list[str]]:
    if window in {"", "always", "*"}:
        return at, []
    start_s, end_s = window.split("-")
    sh, sm = (int(part) for part in start_s.split(":"))
    eh, em = (int(part) for part in end_s.split(":"))
    local = at.astimezone(zone).replace(second=0, microsecond=0)
    start = local.replace(hour=sh, minute=sm)
    end = local.replace(hour=eh, minute=em)
    if start <= local <= end:
        return at, []
    moved = start if local < start else start + timedelta(days=1)
    return moved.astimezone(ZoneInfo("UTC")), [f"çalışma penceresine alındı: {moved.isoformat()}"]


def evaluate_self_schedule(
    *,
    now: datetime,
    requested: datetime,
    min_interval_seconds: int,
    max_interval_seconds: int,
    window: str,
    tz_name: str,
    last_run_at: datetime | None,
    runs_today: int,
    max_runs_per_day: int,
) -> ScheduleDecision:
    zone = ZoneInfo(tz_name)
    adjustments: list[str] = []
    at = requested.astimezone(ZoneInfo("UTC"))
    now_utc = now.astimezone(ZoneInfo("UTC"))
    if at < now_utc:
        at = now_utc
        adjustments.append("geçmiş zaman şimdiye çekildi")
    if last_run_at is not None:
        earliest = last_run_at.astimezone(ZoneInfo("UTC")) + timedelta(seconds=min_interval_seconds)
        if at < earliest:
            at = earliest
            adjustments.append("minimum aralığa çekildi")
    latest = now_utc + timedelta(seconds=max_interval_seconds)
    if at > latest:
        at = latest
        adjustments.append("maksimum aralığa çekildi")
    at, window_notes = _align_window(at, window, zone)
    adjustments.extend(window_notes)
    if at > latest:
        return ScheduleDecision(False, None, adjustments, "pencere, maksimum aralığın dışında")
    if last_run_at is not None:
        earliest = last_run_at.astimezone(ZoneInfo("UTC")) + timedelta(seconds=min_interval_seconds)
        if at < earliest:
            return ScheduleDecision(False, None, adjustments, "minimum aralık ile pencere çakışıyor")
    if at.astimezone(zone).date() == now_utc.astimezone(zone).date() and runs_today >= max_runs_per_day:
        return ScheduleDecision(False, None, adjustments, "günlük koşum limiti doldu")
    return ScheduleDecision(True, at, adjustments, None)


def local_day_start(now: datetime, tz_name: str) -> datetime:
    zone = ZoneInfo(tz_name)
    local = now.astimezone(zone)
    start = datetime.combine(local.date(), time.min, tzinfo=zone)
    return start.astimezone(ZoneInfo("UTC"))
