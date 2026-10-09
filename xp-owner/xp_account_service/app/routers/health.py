"""Liveness probe. No secrets, URLs, or token material."""

from fastapi import FastAPI

from xp_account_service import SERVICE_NAME
from xp_account_service.app.schemas.health import HealthResponse


def register(app: FastAPI) -> None:
    app.add_api_route("/health", health, methods=["GET"], response_model=HealthResponse)


def health() -> HealthResponse:
    return HealthResponse(service=SERVICE_NAME, status="ok")
