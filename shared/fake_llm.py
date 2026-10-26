from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from harness.sections import requested_sections
from shared.code_templates import daily_code, simple_code
from shared.spec import slugify

_DATE_NAMES = ("sale_date", "tarih", "islem_tarihi", "txn_date", "gun", "date")
_MEASURE_NAMES = ("amount", "tutar", "tahsilat", "net_amount", "total_amount", "revenue")
_DIM_NAMES = ("region", "bolge", "il", "sube", "product", "urun", "kategori")
_DAILY_HINTS = ("dun", "dunku", "gunluk", "sapma", "ortalama", "onceki", "hafta")


def _fold(text: str) -> str:
    table = str.maketrans("çğıöşüıâîû", "cgiosuiaiu")
    return text.translate(table).lower()


def _ident(name: str) -> str:
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
        raise ValueError(f"geçersiz tanımlayıcı: {name}")
    return name


class FakeLLM:
    """Deterministic stand-in for an OpenAI-compatible model.

    Numbers in the report still come from SQL and the executor. This class only
    chooses the query shape and the code template.
    """

    def __init__(self, fault_rounds: int = 0):
        self._bad_left = fault_rounds

    def complete(self, messages: list[dict]) -> str:
        user = messages[-1]["content"]
        payload = json.loads(user)
        role = payload.get("role")
        if role == "builder":
            return json.dumps(self._build(payload), ensure_ascii=False)
        bad = False
        if payload.get("repair") is None and self._bad_left > 0:
            self._bad_left -= 1
            bad = True
        elif payload.get("repair") is not None and self._bad_left > 0:
            self._bad_left -= 1
            bad = True
        return json.dumps(self._plan(payload, bad=bad), ensure_ascii=False)

    def _build(self, payload: dict) -> dict:
        description = payload.get("description") or ""
        owner = payload.get("owner") or "ekip"
        sources = payload.get("datasources") or []
        folded = _fold(description)
        tools: list[str] = []
        if any(word in folded for word in ("e-posta", "eposta", "email", "mail")):
            tools.append("send_email")
        if "sms" in folded or "kisa mesaj" in folded:
            tools.append("send_sms")
        mode = "manual"
        cron = None
        if any(word in folded for word in ("her sabah", "hafta ici", "hafta ici", "her gun", "cron", "zamanla")):
            mode = "hybrid" if any(word in folded for word in ("gerekirse", "kendisi", "otonom")) else "cron"
            cron = "0 7 * * 1-5"
        if any(word in folded for word in ("kendisi karar", "otonom", "kendi zamanla")) and mode == "manual":
            mode = "self"
        if "hafta ici" in folded or "haftaici" in folded:
            mode = "hybrid" if mode == "manual" else mode
            cron = cron or "0 7 * * 1-5"
        datasources = []
        for source in sources:
            tables = source.get("allow_tables") or []
            catalog = source.get("catalog") or {}
            if not tables:
                tables = [table["name"] for table in catalog.get("tables") or []]
            if not tables:
                continue
            datasources.append({"ref": source["name"], "allowTables": tables})
        if not datasources:
            raise ValueError("taslak için en az bir veri kaynağı gerekli")
        name = slugify(description.split(".")[0][:48] or "yeni-ajan")
        schedule: dict = {"mode": mode, "timeZone": "Europe/Istanbul"}
        if cron:
            schedule["cron"] = cron
        if mode in {"self", "hybrid", "cron"}:
            schedule["selfScheduling"] = {
                "minInterval": "1h",
                "maxInterval": "7d",
                "maxRunsPerDay": 4,
                "window": "07:00-20:00",
            }
        return {
            "apiVersion": "agents.internal/v1",
            "kind": "AgentSpec",
            "metadata": {"name": name, "version": 1, "owner": owner},
            "spec": {
                "goal": description.strip(),
                "model": {"class": "local-default"},
                "datasources": datasources,
                "tools": tools,
                "runtime": {
                    "image": "agent-runtime-py312:0.2.0",
                    "cpu": "500m",
                    "memory": "1Gi",
                    "timeoutSeconds": 900,
                },
                "schedule": schedule,
                "output": {
                    "report": "markdown",
                    "artifacts": ["json", "md", "svg"],
                    "notify": tools,
                    "sections": requested_sections(description),
                },
                "verification": {"crossCheckSql": True, "maxRepairRounds": 2, "numericTolerance": 1.0},
                "dryRunRowLimit": 1000,
            },
        }

    def _plan(self, payload: dict, bad: bool) -> dict:
        catalog = payload.get("catalog") or {}
        dialect = payload.get("dialect") or "postgres"
        goal = payload.get("goal") or ""
        tools = payload.get("tools") or []
        allowlist = payload.get("recipient_allowlist") or ["finans@sirket.local"]
        schedule_mode = payload.get("schedule_mode") or "manual"
        table, columns = _pick_table(catalog)
        date_col = _pick(columns, _DATE_NAMES)
        measure = _pick(columns, _MEASURE_NAMES)
        dimension = _pick(columns, _DIM_NAMES) or (columns[0] if columns else None)
        if table is None or dimension is None or measure is None:
            raise RuntimeError("katalogta ölçü ve boyut kolonu bulunamadı")
        threshold = _threshold(goal)
        daily = date_col is not None and any(hint in _fold(goal) for hint in _DAILY_HINTS)
        if daily:
            sql, checks = _daily_sql(dialect, table, date_col, measure, dimension)
            code = daily_code(100 if bad else 1)
            params = {"deviation_threshold_pct": threshold, "baseline_days": 7}
        else:
            sql, checks = _simple_sql(dialect, table, measure, dimension)
            code = simple_code()
            params = {"deviation_threshold_pct": threshold, "baseline_days": 7}
        recipient = _recipient(goal, allowlist)
        notify = "send_email" in tools and recipient is not None
        schedule_next = None
        if schedule_mode in {"self", "hybrid"} and not payload.get("dry_run"):
            schedule_next = {
                "at": _next_morning().isoformat(),
                "reason": "Sonraki iş sabahı için özet",
            }
        return {
            "reasoning": "Şema özetinden pushdown agregasyon seçildi. Ham satır istenmedi.",
            "sql": sql,
            "python": code,
            "params": params,
            "cross_checks": checks,
            "report_template": _template(payload.get("required_sections") or []),
            "notify": notify,
            "notification": {
                "tool": "send_email",
                "to": recipient,
                "subject": "Günlük satış özeti",
            }
            if notify
            else None,
            "schedule_next": schedule_next,
        }


def _pick_table(catalog: dict) -> tuple[str | None, list[str]]:
    tables = catalog.get("tables") or []
    preferred = None
    for table in tables:
        if _fold(table.get("name", "")) in {"sales", "tahsilat"}:
            preferred = table
            break
    chosen = preferred or (tables[0] if tables else None)
    if not chosen:
        return None, []
    return chosen["name"], [column["name"] for column in chosen.get("columns") or []]


def _pick(columns: list[str], names: tuple[str, ...]) -> str | None:
    folded = {_fold(column): column for column in columns}
    for name in names:
        if name in folded:
            return folded[name]
    return None


def _threshold(goal: str) -> float:
    match = re.search(r"%\s*(\d+(?:[.,]\d+)?)|yuzde\s*(\d+(?:[.,]\d+)?)", _fold(goal))
    if not match:
        return 10.0
    raw = match.group(1) or match.group(2)
    return float(raw.replace(",", "."))


def _recipient(goal: str, allowlist: list[str]) -> str | None:
    found = re.findall(r"[\w.+-]+@[\w.-]+", goal)
    if found:
        return found[0]
    for item in allowlist:
        if "*" not in item and "?" not in item:
            return item
    return None


def _next_morning() -> datetime:
    zone = ZoneInfo("Europe/Istanbul")
    local = datetime.now(zone)
    target = local.replace(hour=7, minute=0, second=0, microsecond=0)
    if target <= local + timedelta(hours=1):
        target = target + timedelta(days=1)
    while target.weekday() >= 5:
        target += timedelta(days=1)
    return target


def _daily_sql(dialect: str, table: str, date_col: str, measure: str, dimension: str) -> tuple[str, list[dict]]:
    table_sql = _ident(table)
    date_sql = _ident(date_col)
    measure_sql = _ident(measure)
    dim_sql = _ident(dimension)
    if dialect == "oracle":
        yesterday = f"TRUNC(SYSDATE) - 1"
        window = f"{date_sql} >= TRUNC(SYSDATE) - 8 AND {date_sql} < TRUNC(SYSDATE)"
        cast_amount = f"CAST(SUM({measure_sql}) AS BINARY_DOUBLE)"
        cast_count = f"CAST(COUNT(*) AS NUMBER)"
    else:
        yesterday = "(CURRENT_DATE - INTERVAL '1 day')::date"
        window = (
            f"{date_sql} >= (CURRENT_DATE - INTERVAL '8 days')::date AND {date_sql} < CURRENT_DATE"
        )
        cast_amount = f"SUM({measure_sql})::float8"
        cast_count = "COUNT(*)::bigint"
    sql = (
        f"SELECT {dim_sql} AS region, {date_sql} AS sale_date, "
        f"{cast_amount} AS total_amount, {cast_count} AS sale_count "
        f"FROM {table_sql} WHERE {window} "
        f"GROUP BY {dim_sql}, {date_sql} ORDER BY {dim_sql}, {date_sql}"
    )
    checks = [
        {
            "name": "grand_total",
            "sql": f"SELECT COALESCE({cast_amount}, 0) AS grand_total FROM {table_sql} WHERE {date_sql} = {yesterday}",
            "json_path": "$.grand_total",
        },
        {
            "name": "sale_count",
            "sql": f"SELECT COALESCE({cast_count}, 0) AS sale_count FROM {table_sql} WHERE {date_sql} = {yesterday}",
            "json_path": "$.sale_count",
        },
    ]
    return sql, checks


def _simple_sql(dialect: str, table: str, measure: str, dimension: str) -> tuple[str, list[dict]]:
    table_sql = _ident(table)
    measure_sql = _ident(measure)
    dim_sql = _ident(dimension)
    if dialect == "oracle":
        cast_amount = f"CAST(SUM({measure_sql}) AS BINARY_DOUBLE)"
        cast_count = "CAST(COUNT(*) AS NUMBER)"
    else:
        cast_amount = f"SUM({measure_sql})::float8"
        cast_count = "COUNT(*)::bigint"
    sql = (
        f"SELECT {dim_sql} AS region, {cast_amount} AS total_amount, {cast_count} AS sale_count "
        f"FROM {table_sql} GROUP BY {dim_sql} ORDER BY total_amount DESC"
    )
    checks = [
        {
            "name": "grand_total",
            "sql": f"SELECT COALESCE({cast_amount}, 0) AS grand_total FROM {table_sql}",
            "json_path": "$.grand_total",
        },
        {
            "name": "sale_count",
            "sql": f"SELECT COALESCE({cast_count}, 0) AS sale_count FROM {table_sql}",
            "json_path": "$.sale_count",
        },
    ]
    return sql, checks


def _template(required: list | None = None) -> str:
    body = (
        "# Günlük satış özeti\n\n"
        "**Tarih:** {{yesterday}}\n\n"
        "**Genel toplam:** {{grand_total}}\n\n"
        "**Satış adedi:** {{sale_count}}\n\n"
        "## Bölgeler\n\n"
        "{{region_table}}\n\n"
        "## Sapmalar\n\n"
        "{{anomaly_section}}\n\n"
        "Rakamlar veritabanındaki SQL ile üretildi ve pod içinde çalışan kodun çıktısından yazıldı.\n"
    )
    folded = _fold(body)
    extra = []
    for title in required or []:
        token = _fold(str(title))
        if token and token not in folded:
            extra.append(f"\n## {title}\n")
            folded = f"{folded}\n{token}"
    return body + "".join(extra)
