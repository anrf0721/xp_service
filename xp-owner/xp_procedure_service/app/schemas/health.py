"""Health payload. Contains no configuration or token material."""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    service: str
    status: str
