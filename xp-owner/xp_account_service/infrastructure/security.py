"""Irreversible secret digests and constant-time comparisons."""

from __future__ import annotations

import hashlib
import secrets

_DIGEST_PREFIX = "sha256$"


def digest_secret(secret: str) -> str:
    """Store only a one-way digest. The plaintext never persists."""

    if secret is None or secret == "":
        raise ValueError("secret must not be empty")
    digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()
    return f"{_DIGEST_PREFIX}{digest}"


def secrets_match(presented: str, stored_digest: str) -> bool:
    """Compare a presented secret to a stored digest in constant time."""

    if not stored_digest.startswith(_DIGEST_PREFIX):
        return False
    presented_digest = digest_secret(presented)
    return secrets.compare_digest(presented_digest, stored_digest)


def tokens_match(presented: str, expected: str) -> bool:
    if presented == "" or expected == "":
        return False
    return secrets.compare_digest(presented, expected)
