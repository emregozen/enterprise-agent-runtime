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


def render_report(template: str, output: dict) -> str:
    regions = output.get("regions") or []
    lines = [
        "| Bölge | Tutar | Karşılaştırma | Sapma | Adet |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for region in regions:
        lines.append(
            "| {name} | {amount} | {base} | {dev}% | {count} |".format(
                name=region.get("region") or "—",
                amount=format_number(region.get("yesterday_amount")),
                base=format_number(region.get("baseline_daily")),
                dev=format_number(region.get("deviation_pct")),
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
                f"- **{item.get('region')}**: %{format_number(item.get('deviation_pct'))} ({direction})"
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
