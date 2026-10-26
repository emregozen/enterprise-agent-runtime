import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import polars as pl

from datasources import open_source
from harness.loop import RunContext, SourceBinding, execute_run
from shared.config import get_settings
from shared.fake_llm import FakeLLM


def _port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class RecordingLLM:
    def __init__(self):
        self.inner = FakeLLM()
        self.messages = []

    def complete(self, messages):
        self.messages.append(messages)
        return self.inner.complete(messages)


def _executor(tmp_path: Path):
    port = _port()
    env = {
        "PATH": __import__("os").environ["PATH"],
        "HOME": "/tmp",
        "LANG": "C.UTF-8",
        "PYTHONNOUSERSITE": "1",
        "PYTHONUNBUFFERED": "1",
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "executor", "serve", "--host", "127.0.0.1", "--port", str(port), "--workdir", str(tmp_path)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            if httpx.get(f"http://127.0.0.1:{port}/healthz", timeout=0.3).status_code == 200:
                return process, f"http://127.0.0.1:{port}"
        except httpx.HTTPError:
            time.sleep(0.05)
    process.kill()
    raise RuntimeError("executor did not start")


def _context(tmp_path: Path, url: str, **overrides) -> RunContext:
    settings = get_settings()
    base = dict(
        run_id="run-test",
        goal="Dünkü satışları bölge bazında özetle, toplam tutarı hesapla, yüzde 10'dan büyük sapmaları açıkla ve finans@sirket.local adresine e-posta gönder.",
        spec={},
        sources=[
            SourceBinding(
                name="postgres-sales",
                dialect="postgres",
                dsn=settings.sales_database_url or __import__("os").environ["SALES_DATABASE_URL"],
                allow_tables=["sales"],
                sensitivity="internal",
            )
        ],
        workdir=str(tmp_path),
        executor_url=url,
        schedule_mode="hybrid",
        tools=["send_email"],
        recipient_allowlist=["finans@sirket.local", "*@sirket.local"],
        max_repair_rounds=2,
    )
    base.update(overrides)
    return RunContext(**base)


def test_postgres_session_is_read_only_and_spills_to_parquet(sales, tmp_path: Path):
    import psycopg

    source = open_source(
        "postgres",
        sales,
        allow_tables=["sales"],
        statement_timeout_ms=5000,
        max_limit=1000,
    )
    try:
        try:
            source.conn.execute(
                "INSERT INTO sales (sale_id, sale_date, region, product, quantity, unit_price, amount, customer_id) "
                "VALUES (1, CURRENT_DATE, 'x', 'y', 1, 1, 1, 1)"
            )
            raise AssertionError("insert should have been rejected")
        except psycopg.errors.ReadOnlySqlTransaction:
            pass
        result = source.fetch_to_parquet(
            "SELECT sale_id, amount FROM sales ORDER BY sale_id LIMIT 20",
            str(tmp_path / "slice.parquet"),
            batch_rows=7,
        )
        assert result.row_count == 20
        frame = pl.read_parquet(result.parquet_path)
        assert frame.height == 20
        assert "amount" in frame.columns
    finally:
        source.close()


def test_harness_cross_checks_and_does_not_show_raw_rows_to_the_model(sales, tmp_path: Path):
    process, url = _executor(tmp_path)
    llm = RecordingLLM()
    try:
        outcome = execute_run(_context(tmp_path, url), llm=llm)
    finally:
        process.wait(timeout=5)
    assert outcome.status == "succeeded", outcome.error or outcome.needs_review_reason
    assert "Doğu Anadolu" in (outcome.summary.get("anomaly_regions") or [])
    assert outcome.summary["verification"] == "passed"
    assert all(item["ok"] for item in outcome.summary["cross_checks"])
    blob = json.dumps(llm.messages, ensure_ascii=False)
    assert "123456.78" not in blob
    assert outcome.notification is not None
    assert outcome.notification["to"] == "finans@sirket.local"
    assert (tmp_path / "chart.svg").exists()
    assert (tmp_path / "report.md").exists()
    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "Doğu Anadolu" in report
    assert "geçti" in report
    assert "edilmeli" not in report


def test_failed_cross_check_repairs_then_a_stuck_fault_needs_review(sales, tmp_path: Path):
    process, url = _executor(tmp_path / "repair")
    try:
        repaired = execute_run(_context(tmp_path / "repair", url), llm=FakeLLM(fault_rounds=1))
    finally:
        process.wait(timeout=5)
    assert repaired.status == "succeeded", repaired.needs_review_reason
    assert repaired.summary["repair_rounds"] == 1

    work = tmp_path / "stuck"
    process, url = _executor(work)
    try:
        stuck = execute_run(
            _context(work, url, max_repair_rounds=1),
            llm=FakeLLM(fault_rounds=5),
        )
    finally:
        process.wait(timeout=5)
    assert stuck.status == "needs_review"
    assert stuck.notification is None


def test_missing_requested_sections_block_success_until_the_report_has_them(sales, tmp_path: Path):
    goal = (
        "Dünkü satışları bölge bazında özetle, son 12 ayın aylık kırılımını ve ilk 5 ürünü yaz, "
        "yüzde 10'dan büyük sapmaları açıkla."
    )
    process, url = _executor(tmp_path)
    llm = RecordingLLM()
    try:
        outcome = execute_run(_context(tmp_path, url, goal=goal, tools=[], schedule_mode="manual"), llm=llm)
    finally:
        process.kill()
        process.wait(timeout=5)
    assert outcome.status == "succeeded", outcome.needs_review_reason
    assert "Aylık kırılım" in outcome.report_markdown
    assert "İlk 5" in outcome.report_markdown
    blob = json.dumps(llm.messages, ensure_ascii=False)
    assert "Aylık kırılım" in blob
    assert "İlk 5" in blob
