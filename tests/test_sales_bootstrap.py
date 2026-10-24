import psycopg

from datasources.base import normalize_pg_dsn
from scripts.generate_sales import ensure_database


def test_ensure_database_is_idempotent():
    admin = "postgresql://agentrt:agentrt@127.0.0.1:5432/agentrt"
    name = "agentrt_sales_boot"
    first = ensure_database(admin, name)
    second = ensure_database(first, name)
    assert first.endswith(f"/{name}")
    assert second.endswith(f"/{name}")
    with psycopg.connect(normalize_pg_dsn(admin), autocommit=True) as conn:
        conn.execute(f'DROP DATABASE "{name}"')
