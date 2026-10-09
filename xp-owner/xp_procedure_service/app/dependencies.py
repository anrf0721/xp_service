"""FastAPI dependencies. Routers ask the service, not the database."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from xp_procedure_service.app.services.auth_service import AuthService
from xp_procedure_service.app.services.procedure_service import ProcedureService
from xp_procedure_service.infrastructure.database import session_scope


def get_auth_service(request: Request) -> AuthService:
    return request.app.state.auth_service


def get_procedure_service(request: Request) -> ProcedureService:
    return request.app.state.procedure_service


def require_internal_token(
    x_internal_service_token: Annotated[str | None, Header()] = None,
    auth_service: AuthService = Depends(get_auth_service),
) -> None:
    if not auth_service.is_authorized(x_internal_service_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="unauthorized",
        )


def get_session(request: Request) -> Iterator[Session]:
    yield from session_scope(request.app.state.session_factory)
