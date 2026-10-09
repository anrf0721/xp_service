"""Constant-time internal token comparison. Empty values never match."""

from __future__ import annotations

import secrets


def tokens_match(presented: str, expected: str) -> bool:
    if presented == "" or expected == "":
        return False
    return secrets.compare_digest(presented, expected)
