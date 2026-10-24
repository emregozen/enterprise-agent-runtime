from __future__ import annotations

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp

_BANNED_NAMES = (
    "Insert",
    "Update",
    "Delete",
    "Drop",
    "Create",
    "Alter",
    "Command",
    "Merge",
    "Copy",
    "Grant",
    "Analyze",
)
_BANNED = tuple(getattr(exp, name) for name in _BANNED_NAMES if hasattr(exp, name))
_BLOCKED_FUNCTIONS = {
    "pg_read_file",
    "pg_read_binary_file",
    "pg_ls_dir",
    "pg_stat_file",
    "lo_import",
    "lo_export",
    "lo_from_bytea",
    "dblink",
    "dblink_exec",
    "pg_sleep",
    "pg_terminate_backend",
    "pg_cancel_backend",
    "pg_read_server_files",
    "utl_http",
    "utl_file",
    "utl_tcp",
    "utl_smtp",
    "dbms_java",
    "dbms_scheduler",
    "dbms_pipe",
    "dbms_lob",
}


@dataclass
class GuardResult:
    ok: bool
    sql: str
    reason: str | None = None
    tables: list[str] = field(default_factory=list)
    aggregate: bool = False


def _dialect(name: str) -> str:
    mapping = {"postgresql": "postgres", "postgres": "postgres", "oracle": "oracle"}
    return mapping.get(name.lower(), name.lower() or "postgres")


def _fn_name(node: exp.Func) -> str:
    name = getattr(node, "name", None) or ""
    if not name:
        name = node.sql_name() or ""
    return str(name).lower()


def _direct_tables(select: exp.Select) -> list[exp.Table]:
    nodes = []
    if select.args.get("from_") is not None:
        nodes.append(select.args["from_"])
    nodes.extend(select.args.get("joins") or [])
    tables: list[exp.Table] = []
    for node in nodes:
        for table in node.find_all(exp.Table):
            if table.find_ancestor(exp.Select) is select:
                tables.append(table)
    return tables


def _is_aggregate(select: exp.Select) -> bool:
    if select.args.get("group"):
        return True
    for agg in select.find_all(exp.AggFunc):
        if agg.find_ancestor(exp.Select) is select:
            return True
    return False


def _limit_value(select: exp.Select) -> int | None:
    limit = select.args.get("limit")
    if limit is None:
        return None
    expression = limit.args.get("expression")
    if isinstance(expression, exp.Literal) and not expression.is_string:
        return int(expression.this)
    return -1


def _allowed(table: exp.Table, allow: set[str]) -> bool:
    name = table.name.lower()
    db = (table.db or "").lower()
    full = f"{db}.{name}" if db else name
    return name in allow or full in allow


def guard_sql(sql: str, *, dialect: str, allow_tables: list[str], max_limit: int) -> GuardResult:
    """Accept a single read-only SELECT that is aggregated or explicitly limited."""
    raw = sql.strip().rstrip(";").strip()
    if not raw:
        return GuardResult(False, raw, "SQL boş")
    if len(raw) > 20_000:
        return GuardResult(False, raw, "SQL 20000 karakterden uzun")
    if "\x00" in raw:
        return GuardResult(False, raw, "SQL geçersiz karakter içeriyor")
    try:
        statements = [item for item in sqlglot.parse(raw, read=_dialect(dialect)) if item is not None]
    except sqlglot.errors.ParseError as exc:
        return GuardResult(False, raw, f"SQL ayrıştırılamadı: {exc}")
    if len(statements) != 1:
        return GuardResult(False, raw, "Yalnızca tek bir ifade çalıştırılabilir")
    statement = statements[0]
    if not isinstance(statement, (exp.Select, exp.Union)):
        return GuardResult(False, raw, "Yalnızca SELECT sorgularına izin verilir")
    for node in statement.walk():
        if isinstance(node, _BANNED):
            return GuardResult(False, raw, f"Yasak ifade: {type(node).__name__}")
    cte_names = {cte.alias.lower() for cte in statement.find_all(exp.CTE) if cte.alias}
    for fn in statement.find_all(exp.Func):
        name = _fn_name(fn)
        if name in _BLOCKED_FUNCTIONS or name.startswith("dbms_") or name.startswith("utl_"):
            return GuardResult(False, raw, f"Yasak fonksiyon: {name}")
    allow = {item.lower() for item in allow_tables}
    tables: list[str] = []
    saw_aggregate = False
    for select in statement.find_all(exp.Select):
        if select.args.get("into"):
            return GuardResult(False, raw, "SELECT INTO yasak")
        if select.args.get("locks"):
            return GuardResult(False, raw, "FOR UPDATE/SHARE yasak")
        physical = []
        for table in _direct_tables(select):
            if table.name.lower() in cte_names:
                continue
            physical.append(table)
        if not physical:
            continue
        for table in physical:
            if not _allowed(table, allow):
                return GuardResult(False, raw, f"Tablo izinli değil: {table.name}")
            tables.append(table.name.lower())
        if _is_aggregate(select):
            saw_aggregate = True
            continue
        limit = _limit_value(select)
        if limit is None:
            return GuardResult(False, raw, "Ham SELECT için LIMIT zorunlu; agregasyon yok")
        if limit < 1 or limit > max_limit:
            return GuardResult(False, raw, f"LIMIT 1 ile {max_limit} arasında olmalı")
    if not tables:
        return GuardResult(False, raw, "Sorguda izinli bir tablo yok")
    return GuardResult(True, raw, None, tables, saw_aggregate)
