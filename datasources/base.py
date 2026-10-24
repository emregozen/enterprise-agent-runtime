from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol


@dataclass
class ColumnInfo:
    name: str
    type: str
    nullable: bool = True


@dataclass
class TableInfo:
    name: str
    columns: list[ColumnInfo]


@dataclass
class SchemaCatalog:
    dialect: str
    tables: list[TableInfo] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "dialect": self.dialect,
            "tables": [
                {
                    "name": table.name,
                    "columns": [
                        {"name": column.name, "type": column.type, "nullable": column.nullable}
                        for column in table.columns
                    ],
                }
                for table in self.tables
            ],
        }


@dataclass
class PlanInfo:
    supported: bool
    cost: float | None = None
    detail: str = ""


@dataclass
class FetchResult:
    row_count: int
    columns: list[str]
    parquet_path: str


class DataSource(Protocol):
    dialect: str

    def introspect(self, allow_tables: list[str]) -> SchemaCatalog: ...

    def explain(self, sql: str) -> PlanInfo: ...

    def fetch_to_parquet(self, sql: str, path: str, batch_rows: int) -> FetchResult: ...

    def scalar(self, sql: str): ...

    def close(self) -> None: ...


def arrow_record(columns: list[str], row) -> dict:
    """Stable Arrow values. Decimal precision must not change between batches."""
    values = {}
    for name, value in zip(columns, row, strict=True):
        if isinstance(value, Decimal):
            value = float(value)
        values[name] = value
    return values


def normalize_pg_dsn(dsn: str) -> str:
    return (
        dsn.replace("postgresql+psycopg://", "postgresql://", 1)
        .replace("postgresql+psycopg2://", "postgresql://", 1)
    )


def assert_select_prefix(sql: str) -> None:
    head = sql.lstrip().lower()
    if head.startswith("select") or head.startswith("with") or head.startswith("explain"):
        return
    raise PermissionError("bağlayıcı yalnızca SELECT veya EXPLAIN çalıştırır")


def open_source(dialect: str, dsn: str, *, allow_tables: list[str], statement_timeout_ms: int, max_limit: int):
    kind = dialect.lower()
    if kind in {"postgres", "postgresql"}:
        from datasources.postgres import PostgresSource

        return PostgresSource(dsn, allow_tables=allow_tables, statement_timeout_ms=statement_timeout_ms, max_limit=max_limit)
    if kind == "oracle":
        from datasources.oracle import OracleSource

        return OracleSource(dsn, allow_tables=allow_tables, statement_timeout_ms=statement_timeout_ms, max_limit=max_limit)
    from datasources.generic import GenericSource

    return GenericSource(
        dsn,
        dialect=kind or "ansi",
        allow_tables=allow_tables,
        statement_timeout_ms=statement_timeout_ms,
        max_limit=max_limit,
    )
