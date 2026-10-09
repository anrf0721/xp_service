"""Explicit schema initialization. Never called by ordinary startup."""

from __future__ import annotations

from xp_account_service.infrastructure.config import Settings, load_seed_secrets
from xp_account_service.infrastructure.database import (
    create_engine_for,
    create_session_factory,
)
from xp_account_service.app.services.credential_service import CredentialService
from xp_account_service.models.base import Base
from xp_account_service.models.credential import Credential  # noqa: F401


def initialize(settings: Settings) -> None:
    engine = create_engine_for(settings)
    Base.metadata.create_all(engine)
    engine.dispose()
    secrets_by_kind = load_seed_secrets()
    service = CredentialService(create_session_factory(settings))
    service.seed(secrets_by_kind)
