"""Recipient domains are fixed by the channel. The model cannot widen them."""

from __future__ import annotations


def domain_of(address: str) -> str:
    return address.rsplit("@", 1)[-1].lower().strip().strip(".")


def domain_allowed(address: str, allow: list[str]) -> bool:
    domain = domain_of(address)
    if not domain or not allow:
        return False
    for item in allow:
        rule = str(item).lower().strip().lstrip("@")
        if not rule:
            continue
        if rule.startswith("*."):
            suffix = rule[2:]
            if domain == suffix or domain.endswith("." + suffix):
                return True
        elif domain == rule:
            return True
    return False


def reject_recipients(addresses: list[str], allow: list[str]) -> list[str]:
    return [item for item in addresses if not domain_allowed(item, allow)]
