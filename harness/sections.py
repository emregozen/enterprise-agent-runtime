"""Report sections the goal or the spec asked for. The run does not finish while one is missing."""

from __future__ import annotations

from shared.spec import fold_tr

_RULES: tuple[tuple[tuple[str, ...], str, tuple[str, ...]], ...] = (
    (("aylik", "12 ay", "son 12 ay", "ay baz", "ay kiril"), "Aylık kırılım", ("aylik", "ay baz")),
    (("top 5", "top-5", "ilk 5", "en yuksek 5", "en cok 5"), "İlk 5", ("ilk 5", "top 5", "top-5")),
    (("medyan", "p95", "yuzdelik"), "Dağılım", ("medyan", "p95", "dagilim")),
    (("haftalik",), "Haftalık", ("haftalik",)),
    (("kanal",), "Kanal", ("kanal",)),
    (("bolge",), "Bölge", ("bolge",)),
    (("sapma", "anomali"), "Sapma", ("sapma", "anomali")),
)


def requested_sections(goal: str, spec: dict | None = None) -> list[str]:
    found: list[str] = []
    output = ((spec or {}).get("spec") or {}).get("output") or {}
    if isinstance(output, dict):
        for item in output.get("sections") or []:
            title = str(item).strip()
            if title and title not in found:
                found.append(title)
    folded = fold_tr(goal or "")
    for keys, title, _aliases in _RULES:
        if title not in found and any(key in folded for key in keys):
            found.append(title)
    return found


def missing_sections(report: str, sections: list[str]) -> list[str]:
    folded = fold_tr(report or "")
    aliases = {title: alias for _keys, title, alias in _RULES}
    missing = []
    for title in sections:
        tokens = aliases.get(title) or (fold_tr(title),)
        if not any(token in folded for token in tokens):
            missing.append(title)
    return missing
