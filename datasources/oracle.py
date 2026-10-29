from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlparse

import pyarrow as pa
import pyarrow.parquet as pq

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
        # A SELECT-only user sees nothing in USER_TAB_COLUMNS. Resolve the name
        # through ALL_TABLES, ALL_VIEWS and ALL_SYNONYMS, then read ALL_TAB_COLUMNS.
        grouped: dict[str, list[ColumnInfo]] = {}
        with self.conn.cursor() as cur:
            for name in [item.upper() for item in (allow_tables or self.allow_tables)]:
                owner, _, table = name.rpartition(".")
                cur.execute(_COLUMNS_SQL, {"owner": owner or None, "name": table})
                for column_name, data_type, nullable in cur.fetchall():
                    grouped.setdefault(name, []).append(
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

    def query_rows(self, sql: str, max_rows: int = 100) -> tuple[list[str], list[dict]]:
        guarded = self._guarded(sql)
        assert_select_prefix(guarded)
        cap = max(1, min(int(max_rows), self.max_limit))
        with self.conn.cursor() as cur:
            cur.arraysize = cap
            cur.execute(guarded)
            columns = [item[0].lower() for item in (cur.description or [])]
            chunk = cur.fetchmany(cap)
        return columns, [json_safe_record(columns, row) for row in chunk]

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


_COLUMNS_SQL = """
    WITH target AS (
        SELECT owner, table_name, 1 AS pref FROM all_tables
        WHERE table_name = :name AND owner = NVL(:owner, USER)
        UNION ALL
        SELECT owner, view_name, 1 FROM all_views
        WHERE view_name = :name AND owner = NVL(:owner, USER)
        UNION ALL
        SELECT table_owner, table_name, CASE owner WHEN USER THEN 2 ELSE 3 END FROM all_synonyms
        WHERE :owner IS NULL AND synonym_name = :name AND owner IN (USER, 'PUBLIC')
    ), pick AS (
        SELECT owner, table_name FROM target ORDER BY pref FETCH FIRST 1 ROWS ONLY
    )
    SELECT c.column_name, c.data_type, c.nullable
    FROM all_tab_columns c JOIN pick p ON c.owner = p.owner AND c.table_name = p.table_name
    ORDER BY c.column_id
"""


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
