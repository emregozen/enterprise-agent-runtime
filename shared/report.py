from __future__ import annotations

import re

from shared.spec import fold_tr


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
_MAX_TABLE_ROWS = 15
_RAW_KEYS = {"rows", "raw", "raw_rows", "records", "preview", "dump", "detail_rows", "all_rows"}
_POINTER = re.compile(r"yukari|asagi|bkz|bakin|tabloda|ustte|yukarda")


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
    body = tighten_report(body)
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
        if isinstance(value, list) and (len(value) > _MAX_TABLE_ROWS or key.lower() in _RAW_KEYS):
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


def tighten_report(body: str) -> str:
    """Drop raw dumps, repeated region tables, and sections that only point upward."""
    sections = _split_sections(body)
    cleaned = []
    for heading, text in sections:
        text = _drop_long_tables(text)
        cleaned.append((heading, text))
    cleaned = _drop_redundant_tables(cleaned)
    kept = []
    for heading, text in cleaned:
        text = _drop_pointer_lines(text)
        if heading and not _section_has_substance(text):
            continue
        kept.append((heading, text))
    return _join_sections(kept).rstrip() + "\n"


def report_sections(body: str) -> list[tuple[str, str]]:
    return _split_sections(body)


def section_has_substance(body: str) -> bool:
    return _section_has_substance(body)


def _split_sections(body: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    heading = ""
    chunk: list[str] = []
    for line in body.splitlines():
        if re.match(r"^#{1,3}[ \t]+\S", line) and chunk:
            sections.append((heading, "\n".join(chunk).strip()))
            heading = line
            chunk = []
            continue
        if re.match(r"^#{1,3}[ \t]+\S", line) and not chunk:
            heading = line
            continue
        chunk.append(line)
    sections.append((heading, "\n".join(chunk).strip()))
    return sections


def _join_sections(sections: list[tuple[str, str]]) -> str:
    parts = []
    for heading, text in sections:
        block = "\n\n".join(part for part in (heading.strip(), text.strip()) if part)
        if block:
            parts.append(block)
    return "\n\n".join(parts)


def _markdown_tables(text: str) -> list[tuple[str, list[list[str]]]]:
    found = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        if not lines[index].lstrip().startswith("|"):
            index += 1
            continue
        start = index
        while index < len(lines) and lines[index].lstrip().startswith("|"):
            index += 1
        block = "\n".join(lines[start:index])
        rows = []
        for line in lines[start:index]:
            rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
        if len(rows) >= 2 and _is_separator(rows[1]):
            data = rows[2:]
        else:
            data = rows[1:]
        found.append((block, data))
    return found


def _is_separator(cells: list[str]) -> bool:
    if not cells:
        return False
    return all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells if cell)


def _drop_long_tables(text: str) -> str:
    for block, data in _markdown_tables(text):
        if len(data) > _MAX_TABLE_ROWS:
            text = text.replace(block, "")
    return text


def _numeric_tokens(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:[.\s]\d{3})*(?:,\d+)?", text))


def _drop_redundant_tables(sections: list[tuple[str, str]]) -> list[tuple[str, str]]:
    located: list[tuple[int, str, frozenset[str], set[str]]] = []
    for index, (_heading, text) in enumerate(sections):
        for block, data in _markdown_tables(text):
            labels = frozenset(row[0].strip().lower() for row in data if row and row[0].strip())
            located.append((index, block, labels, _numeric_tokens(block)))
    drop: set[tuple[int, str]] = set()
    for left, (index, block, labels, numbers) in enumerate(located):
        for right, (_other, _block, other_labels, other_numbers) in enumerate(located):
            if left == right or not labels or labels != other_labels:
                continue
            if numbers < other_numbers or (numbers == other_numbers and left > right):
                drop.add((index, block))
    result = []
    for index, (heading, text) in enumerate(sections):
        for other, block in drop:
            if other == index:
                text = text.replace(block, "")
        result.append((heading, text))
    return result


def _is_pointer_line(line: str) -> bool:
    folded = fold_tr(line)
    if not _POINTER.search(folded):
        return False
    without_count = re.sub(r"\d+\s*satir", "", folded)
    return not re.search(r"\d", without_count)


def _drop_pointer_lines(text: str) -> str:
    kept = [line for line in text.splitlines() if not _is_pointer_line(line)]
    return "\n".join(kept).strip()


def _section_has_substance(body: str) -> bool:
    text = body.strip()
    if not text:
        return False
    if any(line.lstrip().startswith("|") for line in text.splitlines()):
        return True
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return False
    return not all(_is_pointer_line(line) for line in lines)


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
