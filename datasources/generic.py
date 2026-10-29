from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from datasources.base import (
    ColumnInfo,
    FetchResult,
    PlanInfo,
    SchemaCatalog,
    TableInfo,
    arrow_record,
    assert_select_prefix,
    json_safe_record,
)
from sqlguard import guard_sql


class GenericSource:
    """SQLAlchemy fallback for databases without a native Arrow plugin.

    The dialect string is passed to the SQL guard. Read-only session flags are
    applied when the server accepts them (PostgreSQL) and ignored otherwise.
    """

    def __init__(self, dsn: str, *, dialect: str, allow_tables: list[str], statement_timeout_ms: int, max_limit: int):
        self.dialect = dialect
        self.allow_tables = list(allow_tables)
        self.max_limit = max_limit
        self.statement_timeout_ms = statement_timeout_ms
        self.engine: Engine = create_engine(dsn, pool_pre_ping=True)

    def close(self) -> None:
        self.engine.dispose()

    def _connect(self):
        conn = self.engine.connect()
        for statement in (
            "SET default_transaction_read_only = on",
            f"SET statement_timeout = {int(self.statement_timeout_ms)}",
        ):
            try:
                conn.execute(text(statement))
            except Exception:
                conn.rollback()
        return conn

    def _guarded(self, sql: str) -> str:
        result = guard_sql(sql, dialect=self.dialect, allow_tables=self.allow_tables, max_limit=self.max_limit)
        if not result.ok:
            raise PermissionError(result.reason or "SQL reddedildi")
        return result.sql

    def introspect(self, allow_tables: list[str] | None = None) -> SchemaCatalog:
        from sqlalchemy import inspect

        wanted = {item.lower() for item in (allow_tables or self.allow_tables)}
        inspector = inspect(self.engine)
        tables: list[TableInfo] = []
        for name in inspector.get_table_names():
            if name.lower() not in wanted:
                continue
            columns = [
                ColumnInfo(name=col["name"], type=str(col["type"]), nullable=bool(col.get("nullable", True)))
                for col in inspector.get_columns(name)
            ]
            tables.append(TableInfo(name=name, columns=columns))
        return SchemaCatalog(dialect=self.dialect, tables=tables)

    def explain(self, sql: str) -> PlanInfo:
        return PlanInfo(False, None, "genel bağlayıcı EXPLAIN uygulamıyor")

    def scalar(self, sql: str):
        guarded = self._guarded(sql)
        assert_select_prefix(guarded)
        with self._connect() as conn:
            row = conn.execute(text(guarded)).first()
        if row is None:
            return None
        return row[0]

    def query_rows(self, sql: str, max_rows: int = 100) -> tuple[list[str], list[dict]]:
        guarded = self._guarded(sql)
        assert_select_prefix(guarded)
        cap = max(1, min(int(max_rows), self.max_limit))
        with self._connect() as conn:
            result = conn.execute(text(guarded))
            columns = list(result.keys())
            chunk = result.fetchmany(cap)
        return columns, [json_safe_record(columns, row) for row in chunk]

    def fetch_to_parquet(self, sql: str, path: str, batch_rows: int) -> FetchResult:
        guarded = self._guarded(sql)
        assert_select_prefix(guarded)
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        writer: pq.ParquetWriter | None = None
        count = 0
        columns: list[str] = []
        with self._connect() as conn:
            result = conn.execution_options(stream_results=True, max_row_buffer=batch_rows).execute(text(guarded))
            columns = list(result.keys())
            while True:
                chunk = result.fetchmany(batch_rows)
                if not chunk:
                    break
                batch = pa.RecordBatch.from_pylist([arrow_record(columns, row) for row in chunk])
                if writer is None:
                    writer = pq.ParquetWriter(destination, batch.schema)
                writer.write_batch(batch)
                count += len(chunk)
        if writer is None:
            pq.write_table(pa.table({name: pa.array([], type=pa.large_string()) for name in columns} or {"_empty": []}), destination)
        else:
            writer.close()
        return FetchResult(row_count=count, columns=columns, parquet_path=str(destination))
