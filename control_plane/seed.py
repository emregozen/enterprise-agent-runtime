from __future__ import annotations

import logging

from control_plane.db import SessionLocal
from control_plane.models import Agent, DataSourceRecord
from control_plane.service import create_agent
from shared.config import get_settings

log = logging.getLogger("control-plane.seed")

EXAMPLE_SPEC = {
    "apiVersion": "agents.internal/v1",
    "kind": "AgentSpec",
    "metadata": {"name": "gunluk-satis-ozeti", "version": 1, "owner": "finans-ekibi"},
    "spec": {
        "goal": "Dünkü satışları bölge bazında özetle, toplam tutarı hesapla, yüzde 10'dan büyük sapmaları açıkla ve finans@sirket.local adresine e-posta gönder.",
        "model": {"class": "local-default"},
        "datasources": [{"ref": "postgres-sales", "allowTables": ["sales"]}],
        "tools": ["send_email"],
        "runtime": {"image": "agent-runtime-py312:0.2.0", "cpu": "500m", "memory": "1Gi", "timeoutSeconds": 900},
        "schedule": {
            "mode": "hybrid",
            "cron": "0 7 * * 1-5",
            "timeZone": "Europe/Istanbul",
            "selfScheduling": {"minInterval": "1h", "maxInterval": "7d", "maxRunsPerDay": 4, "window": "07:00-20:00"},
        },
        "output": {"report": "markdown", "artifacts": ["json", "md", "svg"], "notify": ["send_email"]},
        "verification": {"crossCheckSql": True, "maxRepairRounds": 2, "numericTolerance": 1.0},
        "dryRunRowLimit": 1000,
    },
}


def seed() -> None:
    settings = get_settings()
    if settings.seed_sales_rows > 0 and settings.sales_admin_url:
        try:
            from scripts.generate_sales import ensure_database, grant_read_only, load_sales

            sales_dsn = ensure_database(settings.sales_admin_url, "sales")
            count = load_sales(sales_dsn, settings.seed_sales_rows)
            grant_read_only(sales_dsn, settings.sales_ro_password)
            log.info("sales rows available: %s", count)
        except Exception:
            log.exception("sample sales load failed")
    db = SessionLocal()
    try:
        from control_plane.auth import ensure_default_group
        from control_plane.migrate import DEFAULT_GROUP_ID

        ensure_default_group(db)
        if settings.sales_database_url and db.query(DataSourceRecord).filter(DataSourceRecord.name == "postgres-sales").one_or_none() is None:
            db.add(
                DataSourceRecord(
                    name="postgres-sales",
                    dialect="postgres",
                    description="Satış raporlama tablosu. Koşum oturumu salt okunur açılır.",
                    dsn_env="SALES_DATABASE_URL",
                    allow_tables=["sales"],
                    sensitivity="internal",
                    owner_group_id=DEFAULT_GROUP_ID,
                )
            )
            db.commit()
        from control_plane.catalog import seed_llm_from_env

        seed_llm_from_env(db, settings)
        if settings.seed_demo and db.query(Agent).count() == 0:
            if db.query(DataSourceRecord).filter(DataSourceRecord.name == "postgres-sales").one_or_none():
                create_agent(db, EXAMPLE_SPEC, publish=True, actor="seed", owner_group_id=DEFAULT_GROUP_ID)
                log.info("seeded gunluk-satis-ozeti")
    finally:
        db.close()
