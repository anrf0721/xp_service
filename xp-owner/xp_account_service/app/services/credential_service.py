"""Verify secrets and seed credentials. Owns the database transaction."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from xp_account_service.app.repositories.credential_repository import (
    CredentialRepository,
)
from xp_account_service.common.errors import InvalidCredentialError
from xp_account_service.infrastructure.security import digest_secret, secrets_match
from xp_account_service.models.credential import Credential

SEED_CREDENTIALS: tuple[tuple[str, str], ...] = (
    ("seed-owner", "owner"),
    ("seed-authorized-user", "authorized_user"),
    ("seed-advisor", "advisor"),
)


@dataclass(frozen=True, slots=True)
class VerifiedCredential:
    credential_id: str
    kind: str


class CredentialService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def verify(self, secret: str) -> VerifiedCredential:
        if secret is None or secret == "":
            raise InvalidCredentialError("invalid credential")
        session = self._session_factory()
        try:
            presented = digest_secret(secret)
            credential = CredentialRepository(session).get_by_secret_digest(presented)
            if credential is None or not secrets_match(secret, credential.secret):
                raise InvalidCredentialError("invalid credential")
            return VerifiedCredential(
                credential_id=credential.credential_id,
                kind=credential.kind,
            )
        finally:
            session.close()

    def seed(self, secrets_by_kind: dict[str, str]) -> None:
        """Insert missing seed rows. Existing rows are left unchanged."""

        session = self._session_factory()
        try:
            repository = CredentialRepository(session)
            for credential_id, kind in SEED_CREDENTIALS:
                secret = secrets_by_kind.get(kind)
                if secret is None or secret.strip() == "":
                    raise ValueError(f"seed secret for {kind} is empty")
                repository.add_if_absent(
                    Credential(
                        credential_id=credential_id,
                        kind=kind,
                        secret=digest_secret(secret),
                    )
                )
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
