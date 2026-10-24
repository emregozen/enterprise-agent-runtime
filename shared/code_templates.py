from __future__ import annotations

DAILY_ANALYSIS = r'''
import json
import os
from pathlib import Path
from xml.sax.saxutils import escape

import duckdb

workdir = Path(os.environ.get("WORKDIR", "."))
params = json.loads((workdir / "params.json").read_text(encoding="utf-8"))
threshold = float(params.get("deviation_threshold_pct", 10))
baseline_days = int(params.get("baseline_days", 7))
multiplier = int(__MULTIPLIER__)

con = duckdb.connect(database=":memory:")
frame = con.execute(
    """
    SELECT region,
           CAST(sale_date AS DATE) AS sale_date,
           CAST(total_amount AS DOUBLE) AS total_amount,
           CAST(sale_count AS BIGINT) AS sale_count
    FROM read_parquet(?)
    """,
    [str(workdir / "input.parquet")],
).fetchall()

by_region = {}
dates = set()
for region, sale_date, total_amount, sale_count in frame:
    by_region.setdefault(region, []).append((sale_date, float(total_amount or 0), int(sale_count or 0)))
    dates.add(sale_date)

regions_out = []
anomalies = []
grand = 0.0
count = 0
yesterday = None
if dates:
    yesterday = max(dates)
    for region in sorted(by_region):
        y_amount = 0.0
        y_count = 0
        prior = []
        for sale_date, amount, sale_count in by_region[region]:
            if sale_date == yesterday:
                y_amount += amount
                y_count += sale_count
            else:
                prior.append(amount)
        baseline = (sum(prior) / baseline_days) if baseline_days else 0.0
        if baseline:
            deviation = (y_amount - baseline) / baseline * 100.0
        else:
            deviation = 0.0 if y_amount == 0 else 100.0
        grand += y_amount * multiplier
        count += y_count
        regions_out.append(
            {
                "region": region,
                "yesterday_amount": y_amount,
                "baseline_daily": baseline,
                "deviation_pct": deviation,
                "sale_count": y_count,
            }
        )
        if abs(deviation) >= threshold:
            anomalies.append(
                {
                    "region": region,
                    "deviation_pct": deviation,
                    "direction": "yuksek" if deviation > 0 else "dusuk",
                }
            )

output = {
    "yesterday": yesterday.isoformat() if yesterday else None,
    "grand_total": grand,
    "sale_count": count,
    "regions": regions_out,
    "anomalies": anomalies,
}
(workdir / "output.json").write_text(json.dumps(output, ensure_ascii=False), encoding="utf-8")

try:
    width = 640
    height = 40 + 36 * max(len(regions_out), 1)
    max_amount = max([item["yesterday_amount"] for item in regions_out] or [1]) or 1
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#f6f3ee"/>',
        '<text x="16" y="24" font-family="sans-serif" font-size="14" fill="#1e1a14">Dünkü tutar</text>',
    ]
    for index, item in enumerate(regions_out):
        y = 40 + index * 36
        bar = int((item["yesterday_amount"] / max_amount) * 360)
        parts.append(f'<text x="16" y="{y + 16}" font-family="sans-serif" font-size="12" fill="#1e1a14">{escape(str(item["region"]))}</text>')
        parts.append(f'<rect x="180" y="{y}" width="{bar}" height="20" fill="#0c5c4c"/>')
    parts.append("</svg>")
    (workdir / "chart.svg").write_text("".join(parts), encoding="utf-8")
except Exception:
    pass
'''

SIMPLE_ANALYSIS = r'''
import json
import os
from pathlib import Path

import duckdb

workdir = Path(os.environ.get("WORKDIR", "."))
con = duckdb.connect(database=":memory:")
frame = con.execute(
    """
    SELECT region,
           CAST(total_amount AS DOUBLE) AS total_amount,
           CAST(sale_count AS BIGINT) AS sale_count
    FROM read_parquet(?)
    ORDER BY total_amount DESC
    """,
    [str(workdir / "input.parquet")],
).fetchall()

regions = []
grand = 0.0
count = 0
for region, total_amount, sale_count in frame:
    amount = float(total_amount or 0)
    sale_count = int(sale_count or 0)
    grand += amount
    count += sale_count
    regions.append(
        {
            "region": region,
            "yesterday_amount": amount,
            "baseline_daily": 0,
            "deviation_pct": 0,
            "sale_count": sale_count,
        }
    )

output = {
    "yesterday": None,
    "grand_total": grand,
    "sale_count": count,
    "regions": regions,
    "anomalies": [],
}
(workdir / "output.json").write_text(json.dumps(output, ensure_ascii=False), encoding="utf-8")
'''


def daily_code(multiplier: int = 1) -> str:
    return DAILY_ANALYSIS.replace("__MULTIPLIER__", str(int(multiplier)))


def simple_code() -> str:
    return SIMPLE_ANALYSIS
