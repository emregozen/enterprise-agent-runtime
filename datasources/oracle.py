from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlparse

import pyarrow as pa
import pyarrow.parquet as pq

from datasources.base import ColumnInfo, FetchResult, PlanInfo, SchemaCatalog, TableInfo, arrow_record, assert_select_prefix
from sqlguard import guard_sql


class OracleSource:
    """Oracle connector. Thin mode (no Instant Client). The DB user should be SELECT-only.

    python-oracledb's fetch_df_batches() is used when the installed driver exposes it;
    otherwise rows are pulled with fetchmany and written as Arrow batches.
    """

    dialect = "oracle"

    def __init__(self, dsn: str, *, allow_tables: list[str], statement_timeout_ms: int, max_limit: int):
        import oracledb

        self.allow_tables = list(allow_tables)
        self.max_limit = max_limit
        user, password, connect_dsn = _parse_oracle_dsn(dsn)
        self.conn = oracledb.connect(
            user=user,
            password=password,
            dsn=connect_dsn,
            tcp_connect_timeout=5,
            retry_count=0,
        )
        if hasattr(self.conn, "call_timeout"):
            self.conn.call_timeout = int(statement_timeout_ms)

    def close(self) -> None:
        self.conn.close()

    def _guarded(self, sql: str) -> str:
        result = guard_sql(sql, dialect=self.dialect, allow_tables=self.allow_tables, max_limit=self.max_limit)
        if not result.ok:
            raise PermissionError(result.reason or "SQL reddedildi")
        return result.sql

    def introspect(self, allow_tables: list[str] | None = None) -> SchemaCatalog:
        tables = [item.upper() for item in (allow_tables or self.allow_tables)]
        binds = ",".join(f":t{i}" for i in range(len(tables))) or "NULL"
        sql = f"""
            SELECT table_name, column_name, data_type, nullable
            FROM user_tab_columns
            WHERE table_name IN ({binds})
            ORDER BY table_name, column_id
        """
        params = {f"t{i}": name for i, name in enumerate(tables)}
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        grouped: dict[str, list[ColumnInfo]] = {}
        for table_name, column_name, data_type, nullable in rows:
            grouped.setdefault(table_name, []).append(
                ColumnInfo(name=column_name, type=data_type, nullable=(nullable == "Y"))
            )
        return SchemaCatalog(
            dialect=self.dialect,
            tables=[TableInfo(name=name, columns=cols) for name, cols in grouped.items()],
        )

    def explain(self, sql: str) -> PlanInfo:
        # EXPLAIN PLAN writes to a plan table and is often denied for a read-only user.
        return PlanInfo(False, None, "Oracle EXPLAIN PLAN salt-okunur kullanıcıda atlandı")

    def scalar(self, sql: str):
        guarded = self._guarded(sql)
        assert_select_prefix(guarded)
        with self.conn.cursor() as cur:
            cur.execute(guarded)
            row = cur.fetchone()
        if row is None:
            return None
        return row[0]

    def fetch_to_parquet(self, sql: str, path: str, batch_rows: int) -> FetchResult:
        guarded = self._guarded(sql)
        assert_select_prefix(guarded)
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self.conn.cursor() as cur:
            cur.arraysize = max(int(batch_rows), 1)
            cur.execute(guarded)
            columns = [item[0].lower() for item in (cur.description or [])]
            writer: pq.ParquetWriter | None = None
            count = 0
            if hasattr(cur, "fetch_df_batches"):
                frames = cur.fetch_df_batches(size=batch_rows)
                for frame in frames:
                    table = _oracle_frame_to_table(frame)
                    for batch in table.to_batches():
                        if writer is None:
                            writer = pq.ParquetWriter(destination, batch.schema)
                        writer.write_batch(batch)
                        count += batch.num_rows
            else:
                while True:
                    chunk = cur.fetchmany(batch_rows)
                    if not chunk:
                        break
                    batch = pa.RecordBatch.from_pylist([arrow_record(columns, row) for row in chunk])
                    if writer is None:
                        writer = pq.ParquetWriter(destination, batch.schema)
                    writer.write_batch(batch)
                    count += len(chunk)
            if writer is None:
                pq.write_table(
                    pa.table({name: pa.array([], type=pa.large_string()) for name in columns} or {"_empty": []}),
                    destination,
                )
            else:
                writer.close()
        return FetchResult(row_count=count, columns=columns, parquet_path=str(destination))


def _oracle_frame_to_table(frame):
    try:
        return pa.table(frame)
    except Exception:
        if hasattr(frame, "to_arrow"):
            return frame.to_arrow()
        if hasattr(frame, "to_pandas"):
            return pa.Table.from_pandas(frame.to_pandas())
        raise


def _parse_oracle_dsn(dsn: str) -> tuple[str, str, str]:
    if "://" not in dsn:
        raise ValueError("Oracle DSN oracle://kullanici:parola@host:1521/SERVIS biçiminde olmalı")
    parsed = urlparse(dsn)
    user = unquote(parsed.username or "")
    password = unquote(parsed.password or "")
    host = parsed.hostname or "localhost"
    port = parsed.port or 1521
    service = parsed.path.lstrip("/") or "FREEPDB1"
    if not user:
        raise ValueError("Oracle DSN kullanıcı içermiyor")
    connect = f"{host}:{port}/{service}"
    return user, password, connect
