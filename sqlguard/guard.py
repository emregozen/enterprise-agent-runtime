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
    mapping = {"postgresql": "postgres", "postgres": "postgres", "oracle": "oracle", "ansi": ""}
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
    """True only for aggregates of this SELECT, not a scalar subquery inside it."""
    if select.args.get("group"):
        return True
    for agg in select.find_all(exp.AggFunc):
        if agg.find_ancestor(exp.Select) is select:
            return True
    return False


def _literal_int(expression) -> int | None:
    if isinstance(expression, exp.Literal) and not expression.is_string:
        return int(expression.this)
    return None


def _limit_value(select: exp.Select) -> int | None:
    fetch_limit = _fetch_limit(select)
    rownum = _rownum_limit(select)
    if fetch_limit is None:
        return rownum
    if rownum is None:
        return fetch_limit
    if fetch_limit < 0 or rownum < 0:
        return -1
    return min(fetch_limit, rownum)


def _fetch_limit(select: exp.Select) -> int | None:
    limit = select.args.get("limit")
    if limit is None:
        return None
    if isinstance(limit, exp.Fetch):
        options = limit.args.get("limit_options")
        if options is not None and (options.args.get("percent") or options.args.get("with_ties")):
            return -1
        count = _literal_int(limit.args.get("count"))
        return count if count is not None else -1
    expression = limit.args.get("expression")
    count = _literal_int(expression)
    return count if count is not None else -1


def _is_rownum(expression) -> bool:
    return isinstance(expression, exp.Column) and expression.name.lower() == "rownum"


def _rownum_compare(node) -> int | None:
    if not isinstance(node, (exp.LTE, exp.LT, exp.GTE, exp.GT, exp.EQ)):
        return None
    left, right = node.args.get("this"), node.args.get("expression")
    if _is_rownum(left):
        number = _literal_int(right)
        if number is None:
            return None
        if isinstance(node, exp.LT):
            return number - 1
        if isinstance(node, exp.EQ):
            return 1
        return number
    if _is_rownum(right):
        number = _literal_int(left)
        if number is None:
            return None
        if isinstance(node, exp.GT):
            return number - 1
        if isinstance(node, exp.EQ):
            return 1
        return number
    return None


def _rownum_limit(select: exp.Select) -> int | None:
    """ROWNUM bound in a top-level AND. A bound inside OR does not limit every row."""
    where = select.args.get("where")
    if where is None:
        return None
    found: list[int] = []

    def walk(node, under_or: bool) -> None:
        if isinstance(node, exp.Or):
            walk(node.this, True)
            walk(node.expression, True)
            return
        if isinstance(node, exp.And):
            walk(node.this, under_or)
            walk(node.expression, under_or)
            return
        if isinstance(node, exp.Paren):
            walk(node.this, under_or)
            return
        if under_or:
            return
        limit = _rownum_compare(node)
        if limit is not None:
            found.append(limit)

    walk(where.this, False)
    if not found:
        return None
    if any(item < 1 for item in found):
        return -1
    return min(found)


def _cte_name(select: exp.Select) -> str | None:
    parent = select.parent
    if isinstance(parent, exp.CTE) and parent.this is select and parent.alias:
        return parent.alias.lower()
    return None


def _bounded(statement: exp.Expression, select: exp.Select, max_limit: int, depth: int = 0) -> bool:
    """True when this SELECT cannot leak an unlimited raw row set.

    A raw CTE or derived table is bounded only when every SELECT that reads it is bounded.
    """
    if depth > 16:
        return False
    if _is_aggregate(select):
        return True
    limit = _limit_value(select)
    if limit is not None and 1 <= limit <= max_limit:
        return True
    name = _cte_name(select)
    if name:
        readers = [
            other
            for other in statement.find_all(exp.Select)
            if any(table.name.lower() == name and not table.db for table in _direct_tables(other))
        ]
        return bool(readers) and all(_bounded(statement, other, max_limit, depth + 1) for other in readers)
    sub = select.parent
    if isinstance(sub, exp.Subquery) and isinstance(sub.parent, (exp.From, exp.Join)):
        outer = sub.parent.find_ancestor(exp.Select)
        return outer is not None and _bounded(statement, outer, max_limit, depth + 1)
    return False


def _outer_selects(statement: exp.Expression) -> list[exp.Select]:
    if isinstance(statement, exp.Union):
        found: list[exp.Select] = []
        for child in (statement.this, statement.expression):
            if child is not None:
                found.extend(_outer_selects(child))
        return found
    if isinstance(statement, exp.Select):
        return [statement]
    return []


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
    outer_ids = {id(item) for item in _outer_selects(statement)}
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
        if id(select) in outer_ids and _is_aggregate(select):
            saw_aggregate = True
        if _is_aggregate(select):
            continue
        if _bounded(statement, select, max_limit):
            continue
        limit = _limit_value(select)
        if limit is None:
            where = f" (CTE {_cte_name(select)})" if _cte_name(select) else ""
            return GuardResult(False, raw, f"Ham SELECT için LIMIT zorunlu; agregasyon yok{where}")
        if limit < 1 or limit > max_limit:
            return GuardResult(False, raw, f"LIMIT 1 ile {max_limit} arasında olmalı")
    if not tables:
        return GuardResult(False, raw, "Sorguda izinli bir tablo yok")
    return GuardResult(True, raw, None, tables, saw_aggregate)
