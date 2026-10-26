"""Errors safe to show to an operator. Messages must not contain secret values."""

from __future__ import annotations


class SecretProviderError(Exception):
    pass
