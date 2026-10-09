import os
from secrets import compare_digest

from fastapi import Header, HTTPException

from xp_owner_service.common import Rejected
from xp_owner_service.infrastructure.database import sessions
from xp_owner_service.infrastructure.http import verify_credential


def internal_identity(x_internal_service_token: str = Header(default="")):
    expected = os.environ["XP_INTERNAL_SERVICE_TOKEN"]
    if not expected or not compare_digest(x_internal_service_token.encode(), expected.encode()):
        raise HTTPException(401, detail="内部身份无权")


def credential(authorization: str = Header(default="")):
    if not authorization.startswith("Bearer "):
        raise Rejected("身份无权", 403)
    return verify_credential(authorization[7:])


def user_identity(authorization: str = Header(default="")):
    identity = credential(authorization)
    if identity["kind"] not in ("owner", "authorized_user"):
        raise Rejected("身份无权", 403)
    return identity


def advisor_identity(authorization: str = Header(default="")):
    identity = credential(authorization)
    if identity["kind"] != "advisor":
        raise Rejected("身份无权", 403)
    return identity


def factory():
    return sessions()
