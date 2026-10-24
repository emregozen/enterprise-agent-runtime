"""Load a reproducible sales table. Default is small; pass --rows 10000000 for the 10M path."""

from __future__ import annotations

import argparse
import random
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg

from datasources.base import normalize_pg_dsn

REGIONS = [
    ("Marmara", 4),
    ("Ege", 3),
    ("İç Anadolu", 3),
    ("Akdeniz", 2),
    ("Karadeniz", 2),
    ("Doğu Anadolu", 1),
    ("Güneydoğu Anadolu", 2),
]
PRODUCTS = ["Kontör", "Hat", "Cihaz", "Aksesuar", "Kurumsal paket"]
BASE_PRICE = {
    "Marmara": 420,
    "Ege": 360,
    "İç Anadolu": 300,
    "Akdeniz": 280,
    "Karadeniz": 240,
    "Doğu Anadolu": 180,
    "Güneydoğu Anadolu": 220,
}

DDL = """
CREATE TABLE IF NOT EXISTS sales (
    sale_id BIGINT PRIMARY KEY,
    sale_date DATE NOT NULL,
    region TEXT NOT NULL,
    product TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price NUMERIC(12, 2) NOT NULL,
    amount NUMERIC(14, 2) NOT NULL,
    customer_id INTEGER NOT NULL
)
"""


def business_yesterday(today: date | None = None) -> date:
    if today is None:
        today = datetime.now(ZoneInfo("Europe/Istanbul")).date()
    return today - timedelta(days=1)


def iter_rows(n: int, yesterday: date, seed: int = 42):
    if n < 1:
        return
    rng = random.Random(seed)
    regions = [name for name, _weight in REGIONS]
    weights = [weight for _name, weight in REGIONS]
    # Guarantee every region has a comparable history, then fill the rest at random.
    structured = []
    sale_id = 1
    for offset in range(8):
        day = yesterday - timedelta(days=offset)
        for region in regions:
            for _ in range(2):
                structured.append((sale_id, day, region, rng))
                sale_id += 1
    produced = 0
    for sale_id, day, region, _rng in structured:
        if produced >= n:
            return
        yield _row(sale_id, day, region, yesterday, rng, stable=True)
        produced += 1
    while produced < n:
        # Older than the 8-day comparison window so the seeded anomaly stays stable.
        day = yesterday - timedelta(days=rng.randrange(8, 90))
        region = rng.choices(regions, weights=weights, k=1)[0]
        yield _row(produced + 1, day, region, yesterday, rng)
        produced += 1


def _row(sale_id: int, day: date, region: str, yesterday: date, rng: random.Random, stable: bool = False):
    product = PRODUCTS[rng.randrange(len(PRODUCTS))]
    if stable:
        quantity = 2
        unit = float(BASE_PRICE[region])
    else:
        quantity = rng.randint(1, 6)
        unit = round(BASE_PRICE[region] * rng.uniform(0.98, 1.02), 2)
    amount = round(quantity * unit, 2)
    if day == yesterday and region == "Doğu Anadolu":
        amount = round(amount * 4, 2)
        unit = round(amount / quantity, 2)
    customer_id = rng.randint(1000, 99999)
    return (sale_id, day, region, product, quantity, unit, amount, customer_id)


def ensure_schema(conn) -> None:
    conn.execute("SET TIME ZONE 'Europe/Istanbul'")
    conn.execute(DDL)
    conn.execute("CREATE INDEX IF NOT EXISTS sales_sale_date_region_idx ON sales (sale_date, region)")


def ensure_database(admin_dsn: str, name: str = "sales") -> str:
    """Create `name` if needed and return an admin DSN that points at it."""
    from urllib.parse import urlsplit, urlunsplit

    from psycopg import sql

    dsn = normalize_pg_dsn(admin_dsn)
    parts = urlsplit(dsn)
    target = urlunsplit((parts.scheme, parts.netloc, f"/{name}", parts.query, parts.fragment))
    current = parts.path.lstrip("/")
    maintenance = []
    for candidate in ("postgres", current, "template1"):
        if candidate and candidate != name and candidate not in maintenance:
            maintenance.append(candidate)
    last_error: Exception | None = None
    for maint in maintenance:
        maint_dsn = urlunsplit((parts.scheme, parts.netloc, f"/{maint}", parts.query, parts.fragment))
        try:
            with psycopg.connect(maint_dsn, autocommit=True) as conn:
                exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone()
                if not exists:
                    conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
            return target
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    try:
        with psycopg.connect(target, autocommit=True) as conn:
            conn.execute("SELECT 1")
        return target
    except Exception as exc:  # noqa: BLE001
        raise last_error or exc


def load_sales(dsn: str, rows: int, truncate: bool = False) -> int:
    with psycopg.connect(normalize_pg_dsn(dsn), autocommit=True) as conn:
        ensure_schema(conn)
        if truncate:
            conn.execute("TRUNCATE sales")
        else:
            existing = conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
            if existing:
                return int(existing)
        yesterday = business_yesterday()
        with conn.cursor() as cur:
            with cur.copy(
                "COPY sales (sale_id, sale_date, region, product, quantity, unit_price, amount, customer_id) FROM STDIN"
            ) as copy:
                for row in iter_rows(rows, yesterday):
                    copy.write_row(row)
        conn.execute("ANALYZE sales")
        return int(conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0])


def grant_read_only(admin_dsn: str, password: str = "sales_ro") -> None:
    from psycopg import sql

    with psycopg.connect(normalize_pg_dsn(admin_dsn), autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = 'sales_ro'").fetchone()
        if not exists:
            conn.execute(sql.SQL("CREATE ROLE sales_ro LOGIN PASSWORD {}").format(sql.Literal(password)))
        conn.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO sales_ro").format(sql.Identifier(conn.info.dbname)))
        conn.execute("GRANT USAGE ON SCHEMA public TO sales_ro")
        conn.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO sales_ro")
        conn.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO sales_ro")
        conn.execute("ALTER ROLE sales_ro SET default_transaction_read_only = on")


def main() -> None:
    parser = argparse.ArgumentParser(description="Satış örnek verisini yükle")
    parser.add_argument("--database-url", default="postgresql://agentrt:agentrt@127.0.0.1:5432/sales")
    parser.add_argument("--rows", type=int, default=20_000)
    parser.add_argument("--truncate", action="store_true")
    parser.add_argument("--grant-read-only", action="store_true")
    args = parser.parse_args()
    count = load_sales(args.database_url, args.rows, truncate=args.truncate)
    if args.grant_read_only:
        grant_read_only(args.database_url)
    print(f"sales rows: {count}")


if __name__ == "__main__":
    main()
