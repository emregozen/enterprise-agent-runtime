from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["DATABASE_URL"] = "postgresql+psycopg://agentrt:agentrt@127.0.0.1:5432/agentrt_test"
os.environ["SALES_DATABASE_URL"] = os.environ["DATABASE_URL"]
os.environ["SALES_ADMIN_URL"] = ""
os.environ["LLM_MODE"] = "fake"
os.environ["RUN_BACKEND"] = "local"
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["SEED_DEMO"] = "false"
os.environ["SEED_SALES_ROWS"] = "0"
os.environ["ARTIFACT_STORE"] = "pvc"
os.environ["ARTIFACT_BACKEND"] = "local"
os.environ["ARTIFACT_DIR"] = str(ROOT / "var" / "test-artifacts")
os.environ["WORK_ROOT"] = str(ROOT / "var" / "test-work")
os.environ["LOG_DIR"] = str(ROOT / "var" / "test-logs")
os.environ["EMAIL_API_URL"] = ""
os.environ["EMAIL_API_TOKEN"] = "super-secret-mail-token"
os.environ["CONTROL_PLANE_PUBLIC_URL"] = "http://127.0.0.1:8841"
os.environ["CONTROL_PLANE_INTERNAL_URL"] = "http://127.0.0.1:8841"

from shared.config import get_settings

get_settings.cache_clear()

import pytest
from sqlalchemy.orm import Session

from control_plane.db import SessionLocal, init_db, reset_engine
from scripts.generate_sales import business_yesterday, iter_rows, load_sales


@pytest.fixture(scope="session", autouse=True)
def _schema():
    reset_engine()
    get_settings.cache_clear()
    init_db()
    yield
    reset_engine()


@pytest.fixture()
def db() -> Session:
    from sqlalchemy import text

    session = SessionLocal()
    session.execute(
        text(
            "TRUNCATE audit_events, artifacts, tool_calls, run_steps, runs, schedules, "
            "agent_versions, agents, datasources RESTART IDENTITY CASCADE"
        )
    )
    session.commit()
    yield session
    session.close()


@pytest.fixture()
def sales(db):
    dsn = os.environ["SALES_DATABASE_URL"]
    load_sales(dsn, 7 * 8 * 2, truncate=True)
    # One raw row outside the model prompt. It sits inside the table but outside the 8-day window.
    import psycopg
    from datasources.base import normalize_pg_dsn

    sentinel_day = business_yesterday() - __import__("datetime").timedelta(days=30)
    with psycopg.connect(normalize_pg_dsn(dsn), autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO sales (sale_id, sale_date, region, product, quantity, unit_price, amount, customer_id)
            VALUES (900000000, %s, 'Marmara', 'Kontör', 1, 123456.78, 123456.78, 1)
            ON CONFLICT (sale_id) DO NOTHING
            """,
            (sentinel_day,),
        )
    yield dsn


@pytest.fixture()
def datasource(db, sales):
    from control_plane.models import DataSourceRecord

    row = DataSourceRecord(
        name="postgres-sales",
        dialect="postgres",
        description="Satış",
        dsn_env="SALES_DATABASE_URL",
        allow_tables=["sales"],
        sensitivity="internal",
    )
    db.add(row)
    db.commit()
    return row


def sample_rows():
    return list(iter_rows(7 * 8 * 2, business_yesterday()))
