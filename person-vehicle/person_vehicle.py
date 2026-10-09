"""预先存在的凭证种类。没有签发接口，没有 VIN 绑定。"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from schema import Credential

CUSTOMER_KINDS = frozenset({"owner", "authorized_driver"})
KIND_DISPLAY = {
    "owner": "车主",
    "authorized_driver": "授权用车人",
    "advisor": "服务顾问",
    "admin": "管理员",
}


def seed(db: Session, rows: tuple[tuple[str, str, str], ...]) -> None:
    for credential_id, kind, secret in rows:
        exists = db.get(Credential, credential_id)
        if exists is None:
            db.add(Credential(credential_id=credential_id, kind=kind, secret=secret))
    db.flush()


def by_secret(db: Session, secret: str) -> Credential | None:
    return db.scalar(select(Credential).where(Credential.secret == secret))
