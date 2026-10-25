from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

import httpx

from harness.loop import RunContext, SourceBinding, execute_run
from shared.config import get_settings
from shared.logging import setup_logging
from shared.otel import setup_otel

MAX_ARTIFACT_BYTES = 20_000_000


class ControlClient:
    def __init__(self, base_url: str, run_id: str, token: str):
        self.base = base_url.rstrip("/")
        self.run_id = run_id
        self.http = httpx.Client(
            timeout=60,
            headers={"Authorization": f"Bearer {token}"},
        )

    def context(self) -> dict:
        response = self.http.get(f"{self.base}/api/internal/runs/{self.run_id}/context")
        response.raise_for_status()
        return response.json()

    def step(self, item: dict) -> None:
        self.http.post(f"{self.base}/api/internal/runs/{self.run_id}/steps", json=item).raise_for_status()

    def artifact(self, name: str, media_type: str, data: bytes) -> None:
        digest = hashlib.sha256(data).hexdigest()

        def chunks():
            view = memoryview(data)
            step = 64 * 1024
            for start in range(0, len(view), step):
                yield bytes(view[start : start + step])

        response = self.http.post(
            f"{self.base}/api/internal/runs/{self.run_id}/artifacts",
            content=chunks(),
            headers={
                "Content-Type": media_type,
                "X-Artifact-Name": name,
                "X-Artifact-Sha256": digest,
            },
        )
        response.raise_for_status()

    def invoke_tool(self, name: str, arguments: dict) -> dict:
        response = self.http.post(
            f"{self.base}/api/internal/runs/{self.run_id}/tools/{name}",
            json={"arguments": arguments},
        )
        response.raise_for_status()
        return response.json()

    def schedule_next(self, at: str, reason: str) -> dict:
        response = self.http.post(
            f"{self.base}/api/internal/runs/{self.run_id}/schedule-next",
            json={"at": at, "reason": reason},
        )
        response.raise_for_status()
        return response.json()

    def complete(self, outcome) -> None:
        response = self.http.post(
            f"{self.base}/api/internal/runs/{self.run_id}/complete",
            json={
                "status": outcome.status,
                "summary": outcome.summary,
                "report_markdown": outcome.report_markdown,
                "error": outcome.error,
                "needs_review_reason": outcome.needs_review_reason,
            },
        )
        response.raise_for_status()


def _bindings(context: dict) -> list[SourceBinding]:
    bindings = []
    for item in context["datasources"]:
        dsn = os.environ.get(item["dsn_env"], "")
        if not dsn:
            raise RuntimeError(f"{item['dsn_env']} harness ortamında yok")
        bindings.append(
            SourceBinding(
                name=item["name"],
                dialect=item["dialect"],
                dsn=dsn,
                allow_tables=item["allow_tables"],
                sensitivity=item.get("sensitivity") or "internal",
            )
        )
    if not bindings:
        raise RuntimeError("koşuya bağlı veri kaynağı yok")
    return bindings


def _upload(client: ControlClient, work: Path, log, max_bytes: int) -> None:
    named = {
        "plan.json": "application/json",
        "analysis.py": "text/x-python",
        "query.sql": "text/plain",
        "input.parquet": "application/vnd.apache.parquet",
        "output.json": "application/json",
        "report.md": "text/markdown",
        "chart.svg": "image/svg+xml",
    }
    for name, media in named.items():
        path = work / name
        if not path.exists():
            continue
        data = path.read_bytes()
        if len(data) > max_bytes:
            note = (
                f"{name} {len(data)} bayt olduğu için kontrol düzlemine yüklenmedi. "
                f"sha256={hashlib.sha256(data).hexdigest()}"
            ).encode()
            client.artifact(f"{name}.skipped.txt", "text/plain", note)
            log.info("artifact skipped", extra={"step": name})
            continue
        client.artifact(name, media, data)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    settings = get_settings()
    setup_otel(settings.otel_service_name + "-harness", os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", settings.otel_exporter_otlp_endpoint))
    log = setup_logging("harness", os.environ.get("LOG_LEVEL", settings.log_level))
    base = os.environ.get("CONTROL_PLANE_URL", settings.control_plane_internal_url)
    token = os.environ["RUN_TOKEN"]
    client = ControlClient(base, args.run_id, token)
    outcome = None
    try:
        context = client.context()
        spec = context["spec"]
        body = spec["spec"]
        work = Path(os.environ.get("WORKDIR", "/work"))
        ctx = RunContext(
            run_id=args.run_id,
            goal=body["goal"],
            spec=spec,
            sources=_bindings(context),
            workdir=str(work),
            executor_url=os.environ.get("EXECUTOR_URL", "http://127.0.0.1:7070"),
            dry_run=bool(context.get("dry_run")),
            model_class=(body.get("model") or {}).get("class", "local-default"),
            schedule_mode=(body.get("schedule") or {}).get("mode", "manual"),
            tools=body.get("tools") or [],
            recipient_allowlist=context.get("recipient_allowlist") or [],
            max_repair_rounds=int((body.get("verification") or {}).get("maxRepairRounds", 2)),
            cross_check=bool((body.get("verification") or {}).get("crossCheckSql", True)),
            numeric_tolerance=float((body.get("verification") or {}).get("numericTolerance", 1.0)),
            timeout_seconds=min(int((body.get("runtime") or {}).get("timeoutSeconds", 180)), 300),
            fault_rounds=int(os.environ.get("HARNESS_FAULT_ROUNDS", "0") or 0),
            previous_summary=context.get("previous_summary"),
            max_preview_rows=settings.llm_max_preview_rows,
            max_cost=settings.sql_max_cost,
            batch_rows=settings.arrow_batch_rows,
            statement_timeout_ms=settings.sql_statement_timeout_ms,
            max_limit=settings.sql_max_limit,
        )
        client.step({"name": "start", "status": "succeeded", "detail": {"trigger": context.get("trigger")}})

        def on_step(item: dict) -> None:
            try:
                client.step(item)
            except Exception as exc:  # noqa: BLE001
                log.warning("step post failed: %s", exc)

        outcome = execute_run(ctx, settings=settings, on_step=on_step)
        plan_path = work / "plan.json"
        if plan_path.exists():
            import json

            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            if plan.get("sql"):
                (work / "query.sql").write_text(plan["sql"], encoding="utf-8")
        if outcome.status == "succeeded" and outcome.notification:
            try:
                note = outcome.notification
                client.invoke_tool(note["tool"], {key: value for key, value in note.items() if key != "tool"})
            except Exception as exc:  # noqa: BLE001
                outcome.summary["notification_error"] = str(exc)
        elif outcome.status == "needs_review":
            outcome.summary["notification"] = "suppressed"
        if outcome.status == "succeeded" and outcome.schedule_request:
            try:
                decision = client.schedule_next(outcome.schedule_request["at"], outcome.schedule_request.get("reason") or "")
                outcome.summary["schedule_next"] = decision
            except Exception as exc:  # noqa: BLE001
                outcome.summary["schedule_error"] = str(exc)
        _upload(client, work, log, int(settings.artifact_max_bytes or MAX_ARTIFACT_BYTES))
        client.complete(outcome)
        log.info("run finished", extra={"run_id": args.run_id, "step": outcome.status})
    except Exception as exc:  # noqa: BLE001
        log.exception("harness failed")
        if outcome is None:
            try:
                client.complete(
                    type("O", (), {
                        "status": "failed",
                        "summary": {"error": str(exc)},
                        "report_markdown": "",
                        "error": str(exc),
                        "needs_review_reason": None,
                    })()
                )
            except Exception:
                sys.exit(1)
        sys.exit(1)


if __name__ == "__main__":
    main()
