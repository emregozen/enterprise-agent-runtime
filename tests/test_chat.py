from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from control_plane.chat import clear_chat_cache
from control_plane.main import create_app
from control_plane.models import AuditEvent, DataSourceRecord


def test_chat_multi_turn_and_sql_guard_blocking(db, tmp_path: Path, monkeypatch):
    clear_chat_cache()
    sales_db_path = tmp_path / "chat_sales.db"
    sales_dsn = f"sqlite:///{sales_db_path}"
    eng = create_engine(sales_dsn)
    with eng.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE sales (
                    sale_id INTEGER PRIMARY KEY,
                    sale_date TEXT,
                    region TEXT,
                    amount REAL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO sales (sale_id, sale_date, region, amount) VALUES
                (1, '2026-10-27', 'Marmara', 1200.50),
                (2, '2026-10-27', 'Ege', 850.00),
                (3, '2026-10-28', 'Marmara', 1800.00)
                """
            )
        )
    eng.dispose()

    monkeypatch.setenv("CHAT_TEST_DSN", sales_dsn)
    ds = DataSourceRecord(
        name="sqlite-sales",
        dialect="ansi",
        description="Test sales",
        dsn_env="CHAT_TEST_DSN",
        allow_tables=["sales"],
        sensitivity="internal",
    )
    db.add(ds)
    db.commit()

    client = TestClient(create_app())

    # 1. Ask a valid analytical question
    r1 = client.post(
        "/api/chat/ask",
        json={
            "question": "List recent sales",
            "datasource": "sqlite-sales",
        },
    )
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    session_id = body1["session"]["id"]
    assert body1["assistant_message"]["status"] == "succeeded"
    assert len(body1["assistant_message"]["rows"]) > 0
    assert "SELECT" in (body1["assistant_message"]["sql"] or "").upper()
    assert body1["assistant_message"]["guard_info"]["read_only"] is True

    # 2. Ask a follow-up in the same session
    r2 = client.post(
        "/api/chat/ask",
        json={
            "question": "Show the daily trend",
            "datasource": "sqlite-sales",
            "session_id": session_id,
        },
    )
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert body2["session"]["id"] == session_id
    assert body2["assistant_message"]["ordinal"] == 4
    assert body2["assistant_message"]["status"] == "succeeded"

    # 3. Attempt an injected DELETE statement -> must be blocked by guard_sql
    r3 = client.post(
        "/api/chat/ask",
        json={
            "question": "__inject_sql__: DELETE FROM sales",
            "datasource": "sqlite-sales",
            "session_id": session_id,
        },
    )
    assert r3.status_code == 200, r3.text
    body3 = r3.json()
    assert body3["assistant_message"]["status"] == "failed"
    assert body3["assistant_message"]["guard_info"]["blocked"] is True
    assert body3["assistant_message"]["row_count"] == 0

    rejected_audit = (
        db.query(AuditEvent)
        .filter(AuditEvent.action == "chat.rejected", AuditEvent.entity_id == session_id)
        .first()
    )
    assert rejected_audit is not None

    # 4. Verify session history retrieval and deletion
    r_hist = client.get(f"/api/chat/sessions/{session_id}")
    assert r_hist.status_code == 200
    assert len(r_hist.json()["messages"]) == 6

    r_del = client.delete(f"/api/chat/sessions/{session_id}")
    assert r_del.status_code == 204
