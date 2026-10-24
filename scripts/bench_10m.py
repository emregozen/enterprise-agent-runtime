"""Time SQL pushdown and the Parquet/DuckDB path against the 10M sales table.

Writes docs/benchmarks/10m.json. Does not change the running control plane.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from datasources import open_source  # noqa: E402
from datasources.base import normalize_pg_dsn  # noqa: E402

DSN = os.environ.get("SALES_DATABASE_URL", "postgresql://sales_ro:sales_ro@127.0.0.1:5432/sales")
ADMIN = os.environ.get("SALES_ADMIN_URL", "postgresql://agentrt:agentrt@127.0.0.1:5432/sales")
API = os.environ.get("CONTROL_PLANE_PUBLIC_URL", "http://127.0.0.1:8841")
OUT = ROOT / "docs" / "benchmarks" / "10m.json"

PUSHDOWN_SQL = """
SELECT region, SUM(amount)::float8 AS total_amount, COUNT(*)::bigint AS sale_count
FROM sales
GROUP BY region
"""

DAILY_SQL = """
SELECT region AS region,
       sale_date AS sale_date,
       SUM(amount)::float8 AS total_amount,
       COUNT(*)::bigint AS sale_count
FROM sales
WHERE sale_date >= (CURRENT_DATE - INTERVAL '8 days')::date
  AND sale_date < CURRENT_DATE
GROUP BY region, sale_date
"""

PULL_SQL = "SELECT sale_id, region, amount::float8 AS amount FROM sales"


def _kb(pid: int, key: str) -> int:
    try:
        text = Path(f"/proc/{pid}/status").read_text()
    except OSError:
        return 0
    for line in text.splitlines():
        if line.startswith(key + ":"):
            return int(line.split()[1])
    return 0


def _children(pid: int) -> list[int]:
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text().split()
        except OSError:
            continue
        if len(stat) > 3 and stat[3] == str(pid):
            child = int(entry.name)
            found.append(child)
            found.extend(_children(child))
    return found


def _tree_hwm(pid: int) -> int:
    best = _kb(pid, "VmHWM")
    for child in _children(pid):
        best = max(best, _kb(child, "VmHWM"))
    return best


class PeakSampler:
    def __init__(self, pid: int):
        self.pid = pid
        self.peak_kb = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(timeout=2)

    def _run(self) -> None:
        while not self._stop.is_set():
            self.peak_kb = max(self.peak_kb, _tree_hwm(self.pid))
            self._stop.wait(0.02)


def _analyze(sql: str) -> dict:
    wrapped = "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql.strip()
    with psycopg.connect(normalize_pg_dsn(DSN)) as conn:
        conn.execute("SET statement_timeout = '300s'")
        conn.execute("SET TIME ZONE 'Europe/Istanbul'")
        started = time.perf_counter()
        plan = conn.execute(wrapped).fetchone()[0]
        elapsed = time.perf_counter() - started
    node = plan[0]
    return {
        "wall_seconds": round(elapsed, 3),
        "execution_ms": node.get("Execution Time"),
        "planning_ms": node.get("Planning Time"),
        "plan_node": (node.get("Plan") or {}).get("Node Type"),
        "shared_hit": (node.get("Plan") or {}).get("Shared Hit Blocks"),
        "shared_read": (node.get("Plan") or {}).get("Shared Read Blocks"),
    }


def _fetch(batch_rows: int, limit: int, path: Path) -> dict:
    source = open_source(
        "postgres",
        DSN,
        allow_tables=["sales"],
        statement_timeout_ms=300_000,
        max_limit=max(limit, 1),
    )
    sql = f"{PULL_SQL} LIMIT {int(limit)}"
    started = time.perf_counter()
    try:
        with PeakSampler(os.getpid()) as sampler:
            result = source.fetch_to_parquet(sql, str(path), batch_rows)
            peak = sampler.peak_kb
    finally:
        source.close()
    elapsed = time.perf_counter() - started
    return {
        "batch_rows": batch_rows,
        "limit": limit,
        "row_count": result.row_count,
        "seconds": round(elapsed, 3),
        "parquet_bytes": path.stat().st_size,
        "fetcher_hwm_mb": round(peak / 1024, 1),
        "rows_per_second": round(result.row_count / elapsed, 1) if elapsed else None,
    }


def _sql_totals() -> dict:
    with psycopg.connect(normalize_pg_dsn(DSN)) as conn:
        conn.execute("SET statement_timeout = '300s'")
        rows = conn.execute(
            "SELECT region, SUM(amount)::float8, COUNT(*) FROM sales GROUP BY region ORDER BY region"
        ).fetchall()
    return {
        "grand_total": sum(float(amount) for _region, amount, _count in rows),
        "sale_count": sum(int(count) for _region, _amount, count in rows),
        "regions": {region: float(amount) for region, amount, _count in rows},
    }


def _seeded_agent() -> dict:
    try:
        agents = httpx.get(f"{API}/api/agents", timeout=5).json()
    except httpx.HTTPError as exc:
        return {"skipped": str(exc)}
    agent = next((item for item in agents if item["name"] == "gunluk-satis-ozeti"), None)
    if agent is None:
        return {"skipped": "seed ajanı yok"}
    with psycopg.connect(normalize_pg_dsn(os.environ.get("DATABASE_URL", "postgresql://agentrt:agentrt@127.0.0.1:5432/agentrt"))) as conn:
        conn.execute(
            "UPDATE schedules SET max_runs_per_day = GREATEST(max_runs_per_day, 30) WHERE agent_id = %s",
            (agent["id"],),
        )
        conn.commit()
    started = time.perf_counter()
    created = httpx.post(f"{API}/api/agents/{agent['id']}/runs", json={"dry_run": False}, timeout=30)
    if created.status_code != 202:
        return {"status_code": created.status_code, "body": created.text[:400]}
    run_id = created.json()["id"]
    peak = 0
    status = None
    body = {}
    deadline = time.time() + 180
    while time.time() < deadline:
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            try:
                cmd = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
            except OSError:
                continue
            if "executor" in cmd or "python -I" in cmd or "harness" in cmd:
                peak = max(peak, _tree_hwm(int(entry.name)))
        body = httpx.get(f"{API}/api/runs/{run_id}", timeout=10).json()
        status = body.get("status")
        if status in {"succeeded", "failed", "needs_review"}:
            break
        time.sleep(0.2)
    return {
        "run_id": run_id,
        "status": status,
        "wall_seconds": round(time.perf_counter() - started, 3),
        "grand_total": body.get("grand_total"),
        "anomaly_regions": body.get("anomaly_regions"),
        "needs_review_reason": body.get("needs_review_reason"),
        "error": body.get("error"),
        "sql_rows": next((step["detail"].get("row_count") for step in body.get("steps", []) if step["name"] == "sql_execute"), None),
        "executor_tree_hwm_mb": round(peak / 1024, 1),
        "verification": (body.get("summary") or {}).get("verification"),
    }


def _isolated_fetch(batch_rows: int, limit: int, path: Path) -> dict:
    proc = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--fetch", str(batch_rows), str(limit), str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    with PeakSampler(proc.pid) as sampler:
        stdout, stderr = proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(stderr.decode()[-1000:])
    payload = json.loads(stdout.decode())
    payload["fetcher_hwm_mb"] = round(sampler.peak_kb / 1024, 1)
    return payload


def _free_port() -> int:
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _duckdb_in_executor(parquet: Path) -> dict:
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "executor", "serve", "--host", "127.0.0.1", "--port", str(port), "--workdir", str(parquet.parent)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            if httpx.get(f"http://127.0.0.1:{port}/healthz", timeout=0.3).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.05)
    else:
        proc.kill()
        raise RuntimeError("executor kalkmadı")
    code = r"""
import json
import os
from pathlib import Path
import duckdb
workdir = Path(os.environ["WORKDIR"])
con = duckdb.connect()
rows = con.execute(
    "SELECT region, SUM(amount)::DOUBLE, COUNT(*) FROM read_parquet(?) GROUP BY region ORDER BY region",
    [str(workdir / "input.parquet")],
).fetchall()
total = sum(amount for _region, amount, _count in rows)
count = sum(n for _region, _amount, n in rows)
(workdir / "output.json").write_text(
    json.dumps({"grand_total": total, "sale_count": count}),
    encoding="utf-8",
)
"""
    started = time.perf_counter()
    try:
        with PeakSampler(proc.pid) as sampler:
            response = httpx.post(
                f"http://127.0.0.1:{port}/v1/execute",
                json={"code": code, "timeout_seconds": 300},
                timeout=320,
            )
            payload = response.json()
            peak = sampler.peak_kb
    finally:
        try:
            httpx.post(f"http://127.0.0.1:{port}/v1/shutdown", timeout=3)
        except httpx.HTTPError:
            proc.kill()
        proc.wait(timeout=10)
    return {
        "seconds": round(time.perf_counter() - started, 3),
        "ok": payload.get("ok"),
        "error": payload.get("error"),
        "stderr": (payload.get("stderr") or "")[:500],
        "executor_hwm_mb": round(peak / 1024, 1),
        "output": payload.get("output"),
    }


def main() -> None:
    with psycopg.connect(normalize_pg_dsn(ADMIN), autocommit=True) as conn:
        count = int(conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0])
        size = conn.execute("SELECT pg_total_relation_size('sales')").fetchone()[0]
    if count < 10_000_000:
        raise SystemExit(f"sales satırı {count}; 10000000 bekleniyor")
    report: dict = {
        "rows": count,
        "table_bytes": int(size),
        "loader_hwm_mb": None,
    }
    hwm_path = Path("/tmp/sales-10m-loader-hwm-kb")
    if hwm_path.exists() and hwm_path.read_text().strip():
        report["loader_hwm_mb"] = round(int(hwm_path.read_text().strip()) / 1024, 1)
    report["pushdown_full_table"] = _analyze(PUSHDOWN_SQL)
    report["pushdown_daily_window"] = _analyze(DAILY_SQL)
    work = ROOT / "var" / "bench-10m"
    work.mkdir(parents=True, exist_ok=True)
    tuning = []
    for batch in (2_000, 10_000, 50_000):
        tuning.append(_isolated_fetch(batch, 300_000, work / f"tune-{batch}.parquet"))
    report["chunk_tuning_300k"] = tuning
    best = min(tuning, key=lambda item: item["seconds"])
    report["chosen_batch_rows"] = best["batch_rows"]
    full = _isolated_fetch(best["batch_rows"], 10_000_000, work / "input.parquet")
    report["parquet_10m"] = full
    duck = _duckdb_in_executor(work / "input.parquet")
    report["duckdb_executor"] = {key: value for key, value in duck.items() if key != "output"}
    sql_totals = _sql_totals()
    output = duck.get("output") or {}
    report["cross_check"] = {
        "sql_total": sql_totals["grand_total"],
        "duckdb_total": output.get("grand_total"),
        "sql_count": sql_totals["sale_count"],
        "duckdb_count": output.get("sale_count"),
        "match": output.get("grand_total") is not None
        and abs(float(output["grand_total"]) - sql_totals["grand_total"]) < 1.0
        and int(output.get("sale_count") or -1) == sql_totals["sale_count"],
    }
    report["seeded_agent"] = _seeded_agent()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "--fetch":
    batch_rows, limit, path = int(sys.argv[2]), int(sys.argv[3]), Path(sys.argv[4])
    print(json.dumps(_fetch(batch_rows, limit, path)))
elif __name__ == "__main__":
    main()
