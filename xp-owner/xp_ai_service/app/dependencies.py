"""Request-scoped dependencies. Routers use these only for identity and wiring."""

from __future__ import annotations

import hmac
from collections.abc import Iterator

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from xp_ai_service.app.settings import Settings, load_settings
from xp_ai_service.infrastructure.database import create_engine_from_url, create_session_factory
from xp_ai_service.infrastructure.procedure_client import ProcedureClient

_settings: Settings | None = None
_session_factory = None
_procedure_client: ProcedureClient | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def get_session_factory(settings: Settings = Depends(get_settings)):
    global _session_factory
    if _session_factory is None:
        engine = create_engine_from_url(settings.database_url)
        _session_factory = create_session_factory(engine)
    return _session_factory


def get_db_session(session_factory=Depends(get_session_factory)) -> Iterator[Session]:
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def get_procedure_client(settings: Settings = Depends(get_settings)) -> ProcedureClient:
    global _procedure_client
    if _procedure_client is None:
        _procedure_client = ProcedureClient(
            base_url=settings.procedure_url,
            token=settings.internal_service_token,
            flow_key=settings.flow_key,
        )
    return _procedure_client


def require_internal_token(
    x_internal_service_token: str | None = Header(default=None, alias="X-Internal-Service-Token"),
    settings: Settings = Depends(get_settings),
) -> None:
    supplied = x_internal_service_token or ""
    if not hmac.compare_digest(supplied, settings.internal_service_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")
