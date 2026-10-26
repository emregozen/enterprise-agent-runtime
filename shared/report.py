from __future__ import annotations

import re


def format_number(value) -> str:
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number.is_integer() and abs(number) >= 1:
        rendered = f"{int(number):,}"
    else:
        rendered = f"{number:,.2f}"
    return rendered.replace(",", " ").replace(".", ",").replace(" ", ".")


def format_percent(value) -> str:
    """Always two fractional digits so 0 and 300 render the same way."""
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    rendered = f"{number:,.2f}"
    rendered = rendered.replace(",", " ").replace(".", ",").replace(" ", ".")
    return f"{rendered}%"


_TR_ALPHABET = "abcçdefgğhıijklmnoöprsştuüvyz"
_TR_RANK = {char: index for index, char in enumerate(_TR_ALPHABET)}
_REGION_BASE = {"region", "yesterday_amount", "baseline_daily", "deviation_pct", "sale_count"}
_SHOWN_KEYS = {"yesterday", "grand_total", "sale_count", "regions", "anomalies"}


def turkish_sort_key(text: str) -> tuple:
    """Turkish alphabet order. Oracle binary sort puts İç after Z."""
    folded = text.replace("İ", "i").replace("I", "ı")
    folded = folded.replace("i\u0307", "i")
    chars = []
    for char in folded:
        lower = char.lower()
        chars.append(_TR_RANK.get(lower, 1000 + ord(lower)))
    return tuple(chars)


def render_report(template: str, output: dict) -> str:
    regions = sorted(output.get("regions") or [], key=lambda item: turkish_sort_key(str(item.get("region") or "")))
    lines = [
        "| Bölge | Tutar | Karşılaştırma | Sapma | Adet |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for region in regions:
        lines.append(
            "| {name} | {amount} | {base} | {dev} | {count} |".format(
                name=region.get("region") or "—",
                amount=format_number(region.get("yesterday_amount")),
                base=format_number(region.get("baseline_daily")),
                dev=format_percent(region.get("deviation_pct")),
                count=region.get("sale_count", 0),
            )
        )
    region_table = "\n".join(lines) if regions else "_Satır yok._"
    anomalies = output.get("anomalies") or []
    if not anomalies:
        anomaly_section = "Eşiği aşan bölge yok."
    else:
        bits = []
        for item in anomalies:
            direction = "yüksek" if item.get("direction") == "yuksek" else "düşük"
            bits.append(
                f"- **{item.get('region')}**: {format_percent(item.get('deviation_pct'))} ({direction})"
            )
        anomaly_section = "\n".join(bits)
    values = {
        "yesterday": output.get("yesterday") or "—",
        "grand_total": format_number(output.get("grand_total")),
        "sale_count": output.get("sale_count", 0),
        "region_table": region_table,
        "anomaly_section": anomaly_section,
        "anomaly_count": len(anomalies),
    }

    def replace(match: re.Match) -> str:
        key = match.group(1).strip()
        if key in values:
            return str(values[key])
        if key in output and not isinstance(output[key], (dict, list)):
            return str(output[key])
        return "—"

    return re.sub(r"\{\{\s*([^{}]+)\s*\}\}", replace, template)


def compose_report(template: str, output: dict, checks: list[dict] | None = None) -> str:
    """Render the model template, then add computed stats and the real verify result."""
    body = render_report(template, output).rstrip()
    extra = _extra_stats(output, body)
    if extra:
        body = f"{body}\n\n{extra}"
    return _replace_verification(body, checks or []).rstrip() + "\n"


def _extra_stats(output: dict, already: str) -> str:
    chunks: list[str] = []
    regions = output.get("regions") or []
    if regions and isinstance(regions[0], dict):
        extra_keys = [key for key in regions[0] if key not in _REGION_BASE]
        if extra_keys and not _values_shown(already, regions, extra_keys):
            ordered = sorted(regions, key=lambda item: turkish_sort_key(str(item.get("region") or "")))
            chunks.append("### Ek ölçüler\n" + _dict_table(ordered, ["region", *extra_keys]))
    for key, value in output.items():
        if key in _SHOWN_KEYS or isinstance(value, (dict,)):
            if isinstance(value, dict):
                block = _render_block(key, value)
                if block and not _values_shown(already, [value], list(value)):
                    chunks.append(block)
            continue
        if key in _SHOWN_KEYS:
            continue
        block = _render_block(key, value)
        if block and not _values_shown(already, value if isinstance(value, list) else [value], None):
            chunks.append(block)
    return "\n\n".join(chunks)


def _values_shown(already: str, rows, keys) -> bool:
    if not isinstance(rows, list):
        return False
    for row in rows:
        if isinstance(row, dict):
            chosen = keys or [key for key in row if key not in {"region", "name"}]
            for key in chosen:
                rendered = format_number(row.get(key)) if not isinstance(row.get(key), str) else str(row.get(key))
                if rendered and rendered not in {"—", "0"} and rendered not in already:
                    return False
        elif not isinstance(row, (dict, list)):
            rendered = format_number(row) if not isinstance(row, str) else str(row)
            if rendered and rendered not in already:
                return False
    return bool(rows)


def _render_block(key: str, value) -> str:
    title = key.replace("_", " ")
    if isinstance(value, list) and value and isinstance(value[0], dict):
        columns = list(value[0].keys())
        rows = value
        if "region" in columns:
            rows = sorted(value, key=lambda item: turkish_sort_key(str(item.get("region") or "")))
        return f"### {title}\n{_dict_table(rows, columns)}"
    if isinstance(value, list):
        lines = "\n".join(f"- {_plain(item)}" for item in value) or "_Satır yok._"
        return f"### {title}\n{lines}"
    if isinstance(value, dict):
        return f"### {title}\n" + "\n".join(f"- **{name}:** {_plain(item)}" for name, item in value.items())
    if isinstance(value, (int, float, str)):
        return f"### {title}\n{_plain(value)}"
    return ""


def _dict_table(rows: list[dict], columns: list[str]) -> str:
    head = "| " + " | ".join(columns) + " |"
    rule = "| " + " | ".join("---" for _ in columns) + " |"
    body = []
    for row in rows:
        cells = []
        for column in columns:
            value = row.get(column)
            cells.append(_plain(value) if column in {"region", "name"} or isinstance(value, str) else format_number(value))
        body.append("| " + " | ".join(cells) + " |")
    return "\n".join([head, rule, *body])


def _plain(value) -> str:
    if value is None:
        return "—"
    return str(value)


def verification_markdown(checks: list[dict]) -> str:
    if not checks:
        return "### Doğrulama\nÇapraz kontrol çalışmadı. Karşılaştırılan sayı yok."
    failed = [item for item in checks if not item.get("ok")]
    lines = ["### Doğrulama", "Çapraz kontrol **başarısız**." if failed else "Çapraz kontrol **geçti**."]
    for item in checks:
        name = item.get("name") or "kontrol"
        if item.get("error") and "sql_value" not in item:
            lines.append(f"- {name}: **kaldı** — {item['error']}")
            continue
        left = format_number(item.get("sql_value"))
        right = format_number(item.get("code_value"))
        word = "geçti" if item.get("ok") else "kaldı"
        lines.append(f"- {name}: SQL {left}, kod {right} — **{word}**")
    return "\n".join(lines)


def _replace_verification(body: str, checks: list[dict]) -> str:
    section = verification_markdown(checks)
    pattern = re.compile(r"(?ms)^#{2,3}[ \t]+Doğrulama[^\n]*\n.*?(?=^#{1,3}[ \t]|\Z)")
    if pattern.search(body):
        return pattern.sub(section + "\n", body)
    return body.rstrip() + "\n\n" + section + "\n"


def dig(payload: dict, path: str):
    if not path.startswith("$"):
        raise ValueError(path)
    body = path[1:]
    if body.startswith("."):
        body = body[1:]
    current = payload
    if not body:
        return current
    for part in body.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def values_close(expected, actual, abs_tol: float = 1.0, rel_tol: float = 1e-4) -> bool:
    if expected is None or actual is None:
        return expected == actual
    try:
        left = float(expected)
        right = float(actual)
    except (TypeError, ValueError):
        return expected == actual
    if left == right:
        return True
    if float(left).is_integer() and float(right).is_integer() and abs(left - right) < 0.5:
        return int(round(left)) == int(round(right))
    return abs(left - right) <= max(abs_tol, rel_tol * max(abs(left), abs(right)))
