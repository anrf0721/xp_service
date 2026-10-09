"""Process configuration. Secrets stay in settings and never enter logs or responses."""

from __future__ import annotations

import os
from dataclasses import dataclass


DEFAULT_BIND_HOST = "127.0.0.1"
DEFAULT_PROCEDURE_URL = "http://127.0.0.1:8001"
DEFAULT_FLOW_KEY = "App预约保养步骤"


class SettingsError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    internal_service_token: str
    bind_host: str
    procedure_url: str
    flow_key: str


def _required(name: str) -> str:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        raise SettingsError(f"{name} is required")
    return value


def load_settings() -> Settings:
    database_url = _required("XP_AI_DATABASE_URL")
    if not database_url.startswith("postgresql"):
        raise SettingsError("XP_AI_DATABASE_URL must be a PostgreSQL URL")
    token = _required("XP_INTERNAL_SERVICE_TOKEN")
    bind_host = os.environ.get("XP_BIND_HOST", DEFAULT_BIND_HOST).strip() or DEFAULT_BIND_HOST
    procedure_url = os.environ.get("XP_PROCEDURE_URL", DEFAULT_PROCEDURE_URL).strip()
    if not procedure_url:
        procedure_url = DEFAULT_PROCEDURE_URL
    return Settings(
        database_url=database_url,
        internal_service_token=token,
        bind_host=bind_host,
        procedure_url=procedure_url.rstrip("/"),
        flow_key=DEFAULT_FLOW_KEY,
    )
