import os

import httpx

from xp_owner_service.infrastructure.http import headers


def _url():
    return os.environ.get("XP_AI_URL", "http://127.0.0.1:8002")


def read_run(request_id):
    try:
        response = httpx.get(_url() + "/internal/runs/by-request/" + request_id, headers=headers(), timeout=5, trust_env=False)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError):
        return None


def execute(claim):
    data = {key: claim[key] for key in ("request_id", "turn_id", "claim_id", "snapshot_revision")}
    try:
        response = httpx.post(_url() + "/internal/runs", json=data, headers=headers(), timeout=10, trust_env=False)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError):
        # An ambiguous response is resolved only by the same idempotency key.
        # Missing facts leave the lease untouched; they do not create a failure.
        return read_run(claim["request_id"])
