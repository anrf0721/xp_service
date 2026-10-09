"""SQL for credentials. Callers own the transaction."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from xp_account_service.models.credential import Credential


class CredentialRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_secret_digest(self, secret_digest: str) -> Credential | None:
        statement = select(Credential).where(Credential.secret == secret_digest)
        return self._session.scalars(statement).one_or_none()

    def get_by_id(self, credential_id: str) -> Credential | None:
        statement = select(Credential).where(Credential.credential_id == credential_id)
        return self._session.scalars(statement).one_or_none()

    def add_if_absent(self, credential: Credential) -> bool:
        existing = self.get_by_id(credential.credential_id)
        if existing is not None:
            return False
        self._session.add(credential)
        return True
