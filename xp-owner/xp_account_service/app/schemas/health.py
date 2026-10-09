"""Health payload. Contains no configuration or secret material."""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    service: str
    status: str
