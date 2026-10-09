"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from xp_ai_service.app.dependencies import get_settings
from xp_ai_service.app.routers.health import router as health_router
from xp_ai_service.app.routers.internal_runs import router as internal_runs_router


class HideUnhandledErrorMiddleware(BaseHTTPMiddleware):
    """Stop call_next exceptions before ServerErrorMiddleware can log them."""

    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)
        except Exception:
            return JSONResponse(status_code=500, content={"detail": "internal error"})


def create_app() -> FastAPI:
    # Validate required configuration at process composition time. Schema is not created here.
    get_settings()
    application = FastAPI(title="xp_ai_service")
    application.add_middleware(HideUnhandledErrorMiddleware)
    application.include_router(health_router)
    application.include_router(internal_runs_router)

    @application.exception_handler(RequestValidationError)
    async def hide_validation_input(_request: Request, _exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": "invalid request"})

    return application


app = create_app()
