import os

import httpx

from xp_owner_service.common import FLOW_KEY, Rejected


def headers():
    token = os.environ["XP_INTERNAL_SERVICE_TOKEN"]
    if not token:
        raise RuntimeError("Internal service token is required")
    return {"X-Internal-Service-Token": token}


def verify_credential(secret):
    try:
        response = httpx.post(
            os.environ.get("XP_ACCOUNT_URL", "http://127.0.0.1:8003") + "/internal/credentials/verify",
            json={"secret": secret}, headers=headers(), timeout=5, trust_env=False,
        )
        if response.status_code == 401:
            raise Rejected("身份无权", 403)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError:
        raise Rejected("凭证服务暂不可用", 503) from None


def current_procedure():
    response = httpx.get(
        os.environ.get("XP_PROCEDURE_URL", "http://127.0.0.1:8001") + "/internal/procedures/current",
        params={"flow_key": FLOW_KEY}, headers=headers(), timeout=5, trust_env=False,
    )
    response.raise_for_status()
    return response.json()
