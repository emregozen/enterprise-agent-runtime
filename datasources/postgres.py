from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import psycopg
from psycopg.rows import dict_row

from datasources.base import (
    ColumnInfo,
    FetchResult,
    PlanInfo,
    SchemaCatalog,
    TableInfo,
    arrow_record,
    assert_select_prefix,
    json_safe_record,
    normalize_pg_dsn,
)
from sqlguard import guard_sql

_OID_ARROW = {
    16: pa.bool_(),
    20: pa.int64(),
    21: pa.int16(),
    23: pa.int32(),
    700: pa.float32(),
    701: pa.float64(),
    1700: pa.float64(),
    1082: pa.date32(),
    1114: pa.timestamp("us"),
    1184: pa.timestamp("us", tz="UTC"),
    25: pa.large_string(),
    1043: pa.large_string(),
    17: pa.large_binary(),
}


class PostgresSource:
    dialect = "postgres"

    def __init__(self, dsn: str, *, allow_tables: list[str], statement_timeout_ms: int, max_limit: int):
        self.allow_tables = list(allow_tables)
        self.max_limit = max_limit
        self.conn = psycopg.connect(normalize_pg_dsn(dsn), autocommit=True)
        self.conn.execute("SET default_transaction_read_only = on")
        self.conn.execute(f"SET statement_timeout = {int(statement_timeout_ms)}")
        self.conn.execute("SET TIME ZONE 'Europe/Istanbul'")

    def close(self) -> None:
        self.conn.close()

    def _guarded(self, sql: str) -> str:
        result = guard_sql(sql, dialect=self.dialect, allow_tables=self.allow_tables, max_limit=self.max_limit)
        if not result.ok:
            raise PermissionError(result.reason or "SQL reddedildi")
        return result.sql

    def introspect(self, allow_tables: list[str] | None = None) -> SchemaCatalog:
        tables = allow_tables or self.allow_tables
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT table_name, column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = ANY(%s)
                ORDER BY table_name, ordinal_position
                """,
                (list(tables),),
            )
            rows = cur.fetchall()
        grouped: dict[str, list[ColumnInfo]] = {}
        for row in rows:
            grouped.setdefault(row["table_name"], []).append(
                ColumnInfo(name=row["column_name"], type=row["data_type"], nullable=row["is_nullable"] == "YES")
            )
        return SchemaCatalog(
            dialect=self.dialect,
            tables=[TableInfo(name=name, columns=cols) for name, cols in grouped.items()],
        )

    def explain(self, sql: str) -> PlanInfo:
        guarded = self._guarded(sql)
        try:
            with self.conn.cursor() as cur:
                cur.execute("EXPLAIN (FORMAT JSON) " + guarded)
                raw = cur.fetchone()[0]
            plan = raw[0]["Plan"] if isinstance(raw, list) else raw["Plan"]
            return PlanInfo(True, float(plan.get("Total Cost", 0)), "postgres json plan")
        except Exception as exc:
            self.conn.rollback()
            return PlanInfo(False, None, f"explain başarısız: {exc.__class__.__name__}")

    def scalar(self, sql: str):
        guarded = self._guarded(sql)
        with self.conn.cursor() as cur:
            cur.execute(guarded)
            row = cur.fetchone()
        if row is None:
            return None
        return row[0]

    def query_rows(self, sql: str, max_rows: int = 100) -> tuple[list[str], list[dict]]:
        guarded = self._guarded(sql)
        assert_select_prefix(guarded)
        cap = max(1, min(int(max_rows), self.max_limit))
        with self.conn.cursor() as cur:
            cur.execute(guarded)
            description = cur.description or []
            columns = [item.name for item in description]
            chunk = cur.fetchmany(cap)
        return columns, [json_safe_record(columns, row) for row in chunk]

    def fetch_to_parquet(self, sql: str, path: str, batch_rows: int) -> FetchResult:
        guarded = self._guarded(sql)
        assert_select_prefix(guarded)
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        writer: pq.ParquetWriter | None = None
        count = 0
        columns: list[str] = []
        with self.conn.transaction():
            with self.conn.cursor(name="agent_batch") as cur:
                cur.itersize = max(int(batch_rows), 1)
                cur.execute(guarded)
                description = cur.description or []
                columns = [item.name for item in description]
                while True:
                    chunk = cur.fetchmany(batch_rows)
                    if not chunk:
                        if writer is None:
                            _write_empty(destination, description)
                        break
                    batch = pa.RecordBatch.from_pylist([arrow_record(columns, row) for row in chunk])
                    if writer is None:
                        writer = pq.ParquetWriter(destination, batch.schema)
                    writer.write_batch(batch)
                    count += len(chunk)
        if writer is not None:
            writer.close()
        return FetchResult(row_count=count, columns=columns, parquet_path=str(destination))


def _write_empty(path: Path, description) -> None:
    if not description:
        pq.write_table(pa.table({"_empty": pa.array([], type=pa.int32())}), path)
        return
    arrays = []
    fields = []
    for item in description:
        arrow_type = _OID_ARROW.get(getattr(item, "type_code", None), pa.large_string())
        fields.append(pa.field(item.name, arrow_type))
        arrays.append(pa.array([], type=arrow_type))
    pq.write_table(pa.table(arrays, schema=pa.schema(fields)), path)
