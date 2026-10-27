"""Turn a fixed delivery target into a message. Placeholders never come from the model."""

from __future__ import annotations

import html
import json
import re
from datetime import datetime
from email.utils import formataddr
from zoneinfo import ZoneInfo

_PLACEHOLDER = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")


def fill_template(template: str, values: dict) -> str:
    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            return match.group(0)
        value = values[key]
        start, end = match.start(), match.end()
        quoted = start > 0 and template[start - 1] == '"' and end < len(template) and template[end] == '"'
        if quoted:
            text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            return json.dumps(text, ensure_ascii=False)[1:-1]
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False)

    return _PLACEHOLDER.sub(repl, template)


def run_date(moment: datetime | None) -> str:
    when = moment or datetime.now(ZoneInfo("Europe/Istanbul"))
    if when.tzinfo is None:
        when = when.replace(tzinfo=ZoneInfo("UTC"))
    return when.astimezone(ZoneInfo("Europe/Istanbul")).date().isoformat()


def render_subject(template: str, *, agent_name: str, moment: datetime | None, run_id: str, status: str) -> str:
    text = fill_template(
        template or "{{agent_name}} – {{run_date}}",
        {
            "agent_name": agent_name,
            "run_date": run_date(moment),
            "run_id": run_id,
            "status": status,
        },
    )
    return " ".join(text.split())[:300]


def markdown_to_html(text: str) -> str:
    blocks = []
    for block in re.split(r"\n{2,}", text or ""):
        stripped = block.strip()
        if not stripped:
            continue
        if stripped.startswith("# "):
            blocks.append(f"<h2>{html.escape(stripped[2:].strip())}</h2>")
            continue
        if stripped.startswith("## "):
            blocks.append(f"<h3>{html.escape(stripped[3:].strip())}</h3>")
            continue
        escaped = html.escape(stripped).replace("\n", "<br>")
        escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
        blocks.append(f"<p>{escaped}</p>")
    body = "\n".join(blocks) or "<p></p>"
    return f"<!DOCTYPE html><html><body>{body}</body></html>"


def format_from(name: str, address: str) -> str:
    if name and name.strip():
        return formataddr((name.strip(), address))
    return address


def message_parts(
    *,
    content: str,
    attachment: str,
    report_markdown: str,
    report_url: str,
    artifacts: list[dict],
) -> tuple[str, str, list[dict]]:
    """Return html, plain text, and attachments ({filename, content_type, data})."""
    report = report_markdown or ""
    html_report = markdown_to_html(report)
    if content == "link":
        html_body = f'<p><a href="{html.escape(report_url)}">Open the run</a></p>'
        return html_body, report_url, []
    if content == "attachment":
        if attachment == "md":
            files = [{"filename": "report.md", "content_type": "text/markdown", "data": report.encode()}]
        else:
            files = [{"filename": "report.html", "content_type": "text/html", "data": html_report.encode()}]
        note = "The report is attached."
        return f"<p>{note}</p>", note, files
    if content == "artifacts":
        files = [
            {
                "filename": item["filename"],
                "content_type": item.get("content_type") or "application/octet-stream",
                "data": item["data"],
            }
            for item in artifacts
        ]
        note = "Run artifacts are attached."
        return f"<p>{html.escape(note)}</p>\n{html_report}", report or note, files
    return html_report, report, []
