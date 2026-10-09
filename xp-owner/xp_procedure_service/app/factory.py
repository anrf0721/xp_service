"""Application factory. Does not create tables or open a listening socket."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from xp_procedure_service import SERVICE_NAME
from xp_procedure_service.app.routers import health, internal
from xp_procedure_service.app.services.auth_service import AuthService
from xp_procedure_service.app.services.procedure_service import ProcedureService
from xp_procedure_service.infrastructure.config import Settings
from xp_procedure_service.infrastructure.database import create_session_factory

logger = logging.getLogger("xp_procedure_service")


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title=SERVICE_NAME, docs_url=None, redoc_url=None, openapi_url=None)
    session_factory = create_session_factory(settings)
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.auth_service = AuthService(settings.internal_service_token)
    app.state.procedure_service = ProcedureService(session_factory)
    health.register(app)
    internal.register(app)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
        del request, exc
        return JSONResponse(status_code=422, content={"detail": "invalid request"})

    @app.middleware("http")
    async def hide_unexpected_errors(request: Request, call_next):
        try:
            return await call_next(request)
        except Exception as exc:
            logger.error(
                "unhandled %s on %s %s",
                type(exc).__name__,
                request.method,
                request.url.path,
            )
            return JSONResponse(status_code=500, content={"detail": "internal error"})

    return app
