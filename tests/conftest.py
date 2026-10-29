from __future__ import annotations

import os
import socket
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _detect_postgres_port() -> int | None:
    for port in (5432, 54329):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                return port
        except OSError:
            continue
    return None


_PG_PORT = _detect_postgres_port()
if _PG_PORT is not None:
    os.environ["DATABASE_URL"] = f"postgresql+psycopg://agentrt:agentrt@127.0.0.1:{_PG_PORT}/agentrt_test"
    os.environ["SALES_DATABASE_URL"] = os.environ["DATABASE_URL"]
else:
    _sqlite_dir = ROOT / "var"
    _sqlite_dir.mkdir(parents=True, exist_ok=True)
    _sqlite_path = _sqlite_dir / "test-control-plane.db"
    if _sqlite_path.exists():
        _sqlite_path.unlink()
    os.environ["DATABASE_URL"] = f"sqlite:///{_sqlite_path}"
    os.environ["SALES_DATABASE_URL"] = "postgresql+psycopg://agentrt:agentrt@127.0.0.1:5432/agentrt_test"
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
os.environ["CONFIG_MASTER_KEY"] = "test-master-key-agent-runtime-poc"

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

    from control_plane.db import Base, get_engine
    from control_plane.migrate import ensure_default_group_sql

    engine = get_engine()
    session = SessionLocal()
    if engine.dialect.name == "postgresql":
        session.execute(
            text(
                "TRUNCATE chat_messages, chat_sessions, delivery_logs, delivery_channels, audit_events, artifacts, tool_calls, run_steps, llm_calls, runs, schedules, "
                "agent_versions, agents, llm_providers, datasources, secret_providers, auth_sessions, group_memberships, users, groups RESTART IDENTITY CASCADE"
            )
        )
        session.execute(text(ensure_default_group_sql()))
    else:
        session.execute(text("DROP TRIGGER IF EXISTS audit_events_no_delete"))
        for table in reversed(Base.metadata.sorted_tables):
            session.execute(table.delete())
        session.execute(
            text(
                """
                CREATE TRIGGER IF NOT EXISTS audit_events_no_delete
                BEFORE DELETE ON audit_events
                BEGIN
                  SELECT RAISE(ABORT, 'audit_events is append-only');
                END
                """
            )
        )
        ensure_default_group_sql(session.connection())
    session.commit()
    yield session
    session.close()


@pytest.fixture()
def sales(db):
    if _PG_PORT is None:
        pytest.skip("PostgreSQL yerel ortamda çalışmıyor")
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
def datasource(db, request):
    if _PG_PORT is not None:
        request.getfixturevalue("sales")
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
