from __future__ import annotations

import contextvars
import json
from dataclasses import dataclass, field
from pathlib import Path

_STEP_CB: contextvars.ContextVar = contextvars.ContextVar("agent_step_cb", default=None)

from datasources import open_source
from shared.llm import make_llm, parse_json_response
from shared.otel import span
from harness.sections import missing_sections, requested_sections
from shared.report import compose_report, dig, values_close
from sqlguard import guard_sql

PLANNER_SYSTEM = """You are the planner inside an enterprise agent run pod.
Return one JSON object and nothing else. Do not invent numeric results.
The JSON schema is:
{
  "reasoning": "short",
  "sql": "single SELECT, aggregated or LIMITed, only allowed tables",
  "python": "code that reads WORKDIR/input.parquet and writes WORKDIR/output.json",
  "params": {"deviation_threshold_pct": 10, "baseline_days": 7},
  "cross_checks": [{"name": "grand_total", "sql": "SELECT ...", "json_path": "$.grand_total"}],
  "report_template": "markdown using {{yesterday}} {{grand_total}} {{sale_count}} {{region_table}} {{anomaly_section}}",
  "notify": false,
  "notification": null,
  "schedule_next": null
}
output.json must contain grand_total (number), sale_count (integer), regions (list), anomalies (list), yesterday.
Python must compute numbers from the parquet file. Never hard-code totals from memory.
Every item in required_sections must be a markdown heading in report_template, and the SQL plus python must compute that section. Do not drop a requested monthly breakdown, top-N list, or other section. Keep a single SELECT statement: extra aggregates go in that statement, in CTEs that only an aggregating query reads, or in one UNION ALL.
Each required section has its own short table or list, at most 15 rows, with the numbers for that section. Do not paste the raw result (no 90-row dump). Do not repeat the region table or the anomaly list under a second heading. Do not write a section that only says the figures are in a table above.
Any extra number you write to output.json (median, p95, monthly rows, top 5) must also have a placeholder or heading in report_template. The runtime keeps a short leftover such as median or p95 and drops raw dumps and duplicate tables.
Do not write a Doğrulama section that tells the reader to cross-check. The runtime replaces that section with the actual pass or fail and the numbers.
SQL dialect is given in the user payload. PostgreSQL uses ::float8 and LIMIT. Oracle uses CAST, not LIMIT.
For a raw Oracle export use FETCH FIRST n ROWS ONLY or WHERE ROWNUM <= n. FETCH FIRST n PERCENT and WITH TIES are rejected.
When ordering Turkish text on Oracle, use ORDER BY NLSSORT(column, 'NLS_SORT=TURKISH') so İç Anadolu is not last. In python, sort region names with Turkish alphabet order (ç after c, ğ after g, ı before i, ö after o, ş after s, ü after u).
If role is repair, fix the code or SQL using the error. Still do not invent numbers.
Execution environment for "python": Python 3.12 standard library plus duckdb, polars and pyarrow.
pandas and numpy are NOT installed; do not import them. There is no network access.
WORKDIR is os.environ["WORKDIR"]. WORKDIR/input.parquet holds exactly the columns returned by your SQL
(same aliases), so the code must only use column names that the SQL selects. params are in WORKDIR/params.json.
output.json fields: yesterday (ISO date string), grand_total, sale_count,
regions: [{"region", "yesterday_amount", "baseline_daily", "deviation_pct", "sale_count"}],
anomalies: [{"region", "deviation_pct", "direction": "yuksek" or "dusuk"}]. Convert dates and decimals to str/float.
Every cross_checks sql must return a single scalar that equals the value at json_path.
If repair.previous is given, it is your previous plan; keep what worked and fix only the failing part.
"""

BUILDER_SYSTEM = """You are the AgentSpec builder.
Return one JSON object matching apiVersion agents.internal/v1 kind AgentSpec.
Use only the datasources listed in the user payload. Do not invent table names.
model.class must be local-default when any datasource sensitivity is restricted.
tools may include send_email, send_sms, http_request only when the description asks.
schedule.mode is cron, self, hybrid, or manual. Use Europe/Istanbul.
If the description does not name a clock time or a day part (sabah, akşam, her gün, hafta içi), schedule.mode is manual and cron is null. Do not invent a time such as 08:15.
Put every report part the description asks for into spec.output.sections, as short titles (for example "Aylık kırılım", "İlk 5"). Do not drop one to simplify the spec.
The JSON must follow agentspec_schema in the user payload exactly. Top-level keys are
apiVersion, kind, metadata (name, version: 1, owner) and spec (goal, datasources, schedule, ...).
Example skeleton:
{"apiVersion": "agents.internal/v1", "kind": "AgentSpec",
 "metadata": {"name": "gunluk-satis-ozeti", "version": 1, "owner": "ekip"},
 "spec": {"goal": "...", "model": {"class": "local-default"},
          "datasources": [{"ref": "postgres-sales", "allowTables": ["sales"]}],
          "tools": [], "schedule": {"mode": "manual", "timeZone": "Europe/Istanbul"},
          "output": {"sections": ["Bölge", "Sapma"]}}}
If the payload has validation_error, return a corrected full AgentSpec.
"""


@dataclass
class SourceBinding:
    name: str
    dialect: str
    dsn: str
    allow_tables: list[str]
    sensitivity: str = "internal"


@dataclass
class RunContext:
    run_id: str
    goal: str
    spec: dict
    sources: list[SourceBinding]
    workdir: str
    executor_url: str
    dry_run: bool = False
    model_class: str = "local-default"
    schedule_mode: str = "manual"
    tools: list[str] = field(default_factory=list)
    recipient_allowlist: list[str] = field(default_factory=list)
    max_repair_rounds: int = 2
    cross_check: bool = True
    numeric_tolerance: float = 1.0
    timeout_seconds: int = 120
    fault_rounds: int = 0
    llm_mode: str | None = None
    max_preview_rows: int = 200
    max_cost: float = 10_000_000
    batch_rows: int = 10_000
    statement_timeout_ms: int = 30_000
    max_limit: int = 2_000_000
    previous_summary: dict | None = None


@dataclass
class RunOutcome:
    status: str
    summary: dict
    report_markdown: str
    error: str | None = None
    needs_review_reason: str | None = None
    steps: list[dict] = field(default_factory=list)
    schedule_request: dict | None = None
    notification: dict | None = None


class ExecutorClient:
    def __init__(self, base_url: str):
        import httpx

        self.base_url = base_url.rstrip("/")
        self.http = httpx.Client(timeout=None)

    def wait_until_ready(self, attempts: int = 50) -> None:
        import time

        last = "executor henüz ayakta değil"
        for _ in range(attempts):
            try:
                response = self.http.get(f"{self.base_url}/healthz", timeout=0.5)
                if response.status_code == 200:
                    return
            except Exception as exc:  # noqa: BLE001
                last = str(exc)
            time.sleep(0.1)
        raise RuntimeError(last)

    def run(self, code: str, timeout_seconds: int) -> dict:
        response = self.http.post(
            f"{self.base_url}/v1/execute",
            json={"code": code, "timeout_seconds": timeout_seconds},
            timeout=timeout_seconds + 15,
        )
        response.raise_for_status()
        return response.json()

    def shutdown(self) -> None:
        try:
            self.http.post(f"{self.base_url}/v1/shutdown", timeout=3)
        except Exception:
            return

    def close(self) -> None:
        self.http.close()


def execute_run(ctx: RunContext, settings=None, on_step=None, llm=None) -> RunOutcome:
    from shared.config import get_settings

    settings = settings or get_settings()
    if ctx.llm_mode and ctx.llm_mode != settings.llm_mode:
        settings = settings.model_copy(update={"llm_mode": ctx.llm_mode})
    token = _STEP_CB.set(on_step)
    try:
        return _execute_run(ctx, settings, llm)
    finally:
        _STEP_CB.reset(token)


def _execute_run(ctx: RunContext, settings, llm=None) -> RunOutcome:
    work = Path(ctx.workdir)
    work.mkdir(parents=True, exist_ok=True)
    steps: list[dict] = []
    primary = ctx.sources[0]
    if any(source.sensitivity == "restricted" for source in ctx.sources) and ctx.model_class.startswith("cloud"):
        return _finish(ctx, "needs_review", steps, reason="kısıtlı veri bulutu modeline gidemez")

    llm = llm or make_llm(settings, ctx.model_class, fault_rounds=ctx.fault_rounds)
    source = open_source(
        primary.dialect,
        primary.dsn,
        allow_tables=primary.allow_tables,
        statement_timeout_ms=ctx.statement_timeout_ms,
        max_limit=ctx.max_limit,
    )
    executor = ExecutorClient(ctx.executor_url)
    try:
        executor.wait_until_ready()
        with span("datasource.introspect", run_id=ctx.run_id, db_system=primary.dialect):
            catalog = source.introspect(primary.allow_tables).as_dict()
        _step(steps, "introspect", "succeeded", {"tables": [table["name"] for table in catalog.get("tables", [])]})
        plan = _complete_plan(llm, _plan_payload(ctx, catalog, repair=None))
        _step(steps, "plan", "succeeded", {"reasoning": plan.get("reasoning"), "sql": plan.get("sql")})
        (work / "plan.json").write_text(json.dumps({k: v for k, v in plan.items() if k != "python"}, ensure_ascii=False, default=str), encoding="utf-8")

        outcome = _attempt_loop(ctx, settings, source, executor, llm, plan, catalog, work, steps)
        _attach_llm_calls(outcome, llm)
        return outcome
    except Exception as exc:  # noqa: BLE001
        _step(steps, "crash", "failed", {"error": str(exc)})
        outcome = _finish(ctx, "failed", steps, error=str(exc), report="")
        _attach_llm_calls(outcome, llm)
        return outcome
    finally:
        executor.shutdown()
        executor.close()
        source.close()


def _attempt_loop(ctx, settings, source, executor, llm, plan, catalog, work: Path, steps: list[dict]) -> RunOutcome:
    max_rounds = ctx.max_repair_rounds
    fetched_sql = None
    fetch = None
    last_reason = "doğrulama tamamlanamadı"
    for attempt in range(max_rounds + 1):
        sql = str(plan.get("sql") or "")
        guarded = guard_sql(sql, dialect=source.dialect, allow_tables=source.allow_tables, max_limit=ctx.max_limit)
        if not guarded.ok:
            last_reason = guarded.reason or "SQL reddedildi"
            _step(steps, "sql_guard", "failed", {"reason": last_reason, "attempt": attempt})
            if attempt == max_rounds:
                return _finish(ctx, "needs_review", steps, reason=last_reason)
            plan = _complete_plan(llm, _plan_payload(ctx, catalog, repair={"error": last_reason, "sql": sql, "previous": _previous(plan)}))
            continue
        _step(steps, "sql_guard", "succeeded", {"tables": guarded.tables, "aggregate": guarded.aggregate, "attempt": attempt})
        if fetched_sql != guarded.sql:
            with span("sql.explain", run_id=ctx.run_id):
                explained = source.explain(guarded.sql)
            if explained.supported and explained.cost is not None and explained.cost > ctx.max_cost:
                last_reason = f"sorgu maliyeti eşiği aştı: {explained.cost}"
                _step(steps, "explain", "failed", {"cost": explained.cost})
                return _finish(ctx, "needs_review", steps, reason=last_reason)
            _step(steps, "explain", "succeeded", {"supported": explained.supported, "cost": explained.cost})
            with span("sql.fetch", run_id=ctx.run_id, db_system=source.dialect):
                fetch = source.fetch_to_parquet(guarded.sql, str(work / "input.parquet"), ctx.batch_rows)
            fetched_sql = guarded.sql
            preview_note = "agregat veya sınırlı sonuç; ham satır modele gönderilmez"
            _step(
                steps,
                "sql_execute",
                "succeeded",
                {"row_count": fetch.row_count, "columns": fetch.columns, "note": preview_note, "attempt": attempt},
            )
        params = plan.get("params") or {"deviation_threshold_pct": 10, "baseline_days": 7}
        (work / "params.json").write_text(json.dumps(params), encoding="utf-8")
        code = str(plan.get("python") or "")
        (work / "analysis.py").write_text(code, encoding="utf-8")
        with span("code.execute", run_id=ctx.run_id, attempt=attempt):
            executed = executor.run(code, ctx.timeout_seconds)
        if not executed.get("ok"):
            last_reason = executed.get("error") or "kod çalışmadı"
            _step(steps, "code_execute", "failed", {"error": last_reason, "stderr": (executed.get("stderr") or "")[:1500], "attempt": attempt})
            if attempt == max_rounds:
                return _finish(ctx, "needs_review", steps, reason=last_reason, extra={"stderr": executed.get("stderr")})
            plan = _complete_plan(
                llm,
                _plan_payload(
                    ctx,
                    catalog,
                    repair={
                        "error": last_reason,
                        "stderr": (executed.get("stderr") or "")[:1500],
                        "attempt": attempt,
                        "input_parquet_columns": fetch.columns if fetch else None,
                        "previous": _previous(plan),
                    },
                ),
            )
            continue
        output = executed.get("output") or {}
        _step(steps, "code_execute", "succeeded", {"keys": list(output.keys()), "attempt": attempt})
        checks = _cross_check(ctx, source, plan.get("cross_checks") or [], output)
        failed = [item for item in checks if not item["ok"]]
        _step(steps, "verify", "failed" if failed else "succeeded", {"checks": checks, "attempt": attempt})
        if ctx.cross_check and not checks:
            last_reason = "çapraz kontrol sorgusu tanımlı değil"
            failed = [{"name": "missing", "ok": False}]
        if not failed:
            report = compose_report(plan.get("report_template") or "", output, checks)
            missing = missing_sections(report, requested_sections(ctx.goal, ctx.spec))
            if not missing:
                return _succeed(ctx, steps, output, plan, work, checks, attempt)
            last_reason = "raporda eksik bölüm: " + ", ".join(missing)
            if attempt == max_rounds:
                return _finish(ctx, "needs_review", steps, reason=last_reason, report=report, extra={"checks": checks})
            plan = _complete_plan(
                llm,
                _plan_payload(
                    ctx,
                    catalog,
                    repair={"error": last_reason, "missing_sections": missing, "previous": _previous(plan)},
                ),
            )
            continue
        last_reason = "SQL çapraz kontrolü tutmadı: " + ", ".join(item["name"] for item in failed)
        if attempt == max_rounds:
            return _finish(
                ctx,
                "needs_review",
                steps,
                reason=last_reason,
                report=_safe_report(plan, output, checks),
                extra={"checks": checks, "output_keys": list(output.keys())},
            )
        repair_preview = None
        if fetch and fetch.row_count <= ctx.max_preview_rows:
            repair_preview = {"row_count": fetch.row_count, "columns": fetch.columns, "checks": checks}
        else:
            repair_preview = {
                "row_count": fetch.row_count if fetch else None,
                "columns": fetch.columns if fetch else None,
                "note": "bulk rows omitted",
            }
        plan = _complete_plan(
            llm,
            _plan_payload(ctx, catalog, repair={"error": last_reason, "preview": repair_preview, "previous": _previous(plan)}),
        )
    return _finish(ctx, "needs_review", steps, reason=last_reason)


def _succeed(ctx: RunContext, steps: list[dict], output: dict, plan: dict, work: Path, checks: list[dict], attempt: int) -> RunOutcome:
    report = compose_report(plan.get("report_template") or "", output, checks)
    (work / "report.md").write_text(report, encoding="utf-8")
    summary = {
        "grand_total": output.get("grand_total"),
        "sale_count": output.get("sale_count"),
        "yesterday": output.get("yesterday"),
        "anomaly_regions": [item.get("region") for item in output.get("anomalies") or []],
        "cross_checks": checks,
        "repair_rounds": attempt,
        "verification": "passed",
    }
    _step(steps, "report", "succeeded", {"chars": len(report)})
    notification = None
    if plan.get("notify") and not ctx.dry_run and plan.get("notification"):
        notification = dict(plan["notification"])
        notification["body"] = report[:4000]
    schedule_request = None
    if plan.get("schedule_next") and not ctx.dry_run and ctx.schedule_mode in {"self", "hybrid"}:
        schedule_request = plan["schedule_next"]
    outcome = _finish(ctx, "succeeded", steps, report=report, extra=summary)
    outcome.notification = notification
    outcome.schedule_request = schedule_request
    return outcome


def _cross_check(ctx: RunContext, source, checks: list[dict], output: dict) -> list[dict]:
    if not ctx.cross_check:
        return []
    results = []
    for check in checks:
        name = check.get("name") or "check"
        try:
            expected = source.scalar(check["sql"])
            actual = dig(output, check["json_path"])
            ok = values_close(expected, actual, abs_tol=ctx.numeric_tolerance)
            results.append(
                {
                    "name": name,
                    "ok": ok,
                    "sql_value": _jsonable(expected),
                    "code_value": _jsonable(actual),
                }
            )
        except Exception as exc:  # noqa: BLE001
            results.append({"name": name, "ok": False, "error": str(exc)})
    return results


def _previous(plan: dict) -> dict:
    """Previous plan for repair prompts. Code is model-written; row data stays out."""
    return {
        "sql": str(plan.get("sql") or "")[:4000],
        "python": str(plan.get("python") or "")[:8000],
        "cross_checks": plan.get("cross_checks"),
    }


def _attach_llm_calls(outcome, llm) -> None:
    calls = list(getattr(llm, "calls", []) or [])
    if not calls:
        return
    outcome.summary = {**(outcome.summary or {}), "llm_calls": calls}


def _plan_payload(ctx: RunContext, catalog: dict, repair: dict | None) -> dict:
    return {
        "role": "plan",
        "goal": ctx.goal,
        "dialect": ctx.sources[0].dialect,
        "catalog": catalog,
        "tools": ctx.tools,
        "recipient_allowlist": ctx.recipient_allowlist,
        "schedule_mode": ctx.schedule_mode,
        "dry_run": ctx.dry_run,
        "previous_summary": ctx.previous_summary,
        "required_sections": requested_sections(ctx.goal, ctx.spec),
        "repair": repair,
    }


def _complete_plan(llm, payload: dict) -> dict:
    system = PLANNER_SYSTEM
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
    ]
    with span("llm.complete", role="plan"):
        return parse_json_response(llm.complete(messages))


def _safe_report(plan: dict, output: dict, checks: list[dict] | None = None) -> str:
    try:
        return compose_report(plan.get("report_template") or "", output, checks)
    except Exception:
        return ""


def _step(steps: list[dict], name: str, status: str, detail: dict) -> None:
    item = {"name": name, "status": status, "detail": detail}
    steps.append(item)
    callback = _STEP_CB.get()
    if callback is not None:
        try:
            callback(item)
        except Exception:
            return


def _finish(ctx: RunContext, status: str, steps: list[dict], report: str = "", error: str | None = None, reason: str | None = None, extra: dict | None = None) -> RunOutcome:
    summary = dict(extra or {})
    summary["run_id"] = ctx.run_id
    if status != "succeeded":
        summary["verification"] = "failed"
    return RunOutcome(
        status=status,
        summary=summary,
        report_markdown=report,
        error=error,
        needs_review_reason=reason if status == "needs_review" else None,
        steps=steps,
    )


def _jsonable(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, (int, float, str, bool)) or value is None:
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return str(value)


def builder_messages(payload: dict) -> list[dict]:
    return [
        {"role": "system", "content": BUILDER_SYSTEM},
        {"role": "user", "content": json.dumps({"role": "builder", **payload}, ensure_ascii=False)},
    ]
