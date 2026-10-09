"""Environment configuration. Secrets are read once and never logged."""

from __future__ import annotations

import os
from dataclasses import dataclass

from xp_account_service.common.errors import ConfigurationError

DATABASE_URL_ENV = "XP_ACCOUNT_DATABASE_URL"
INTERNAL_TOKEN_ENV = "XP_INTERNAL_SERVICE_TOKEN"
BIND_HOST_ENV = "XP_BIND_HOST"
DEFAULT_BIND_HOST = "127.0.0.1"
DEFAULT_PORT = 8003

OWNER_SECRET_ENV = "XP_OWNER_SECRET"
AUTHORIZED_USER_SECRET_ENV = "XP_AUTHORIZED_USER_SECRET"
ADVISOR_SECRET_ENV = "XP_ADVISOR_SECRET"

_FORBIDDEN_DATABASE_NAMES = frozenset({"customer_service"})


def _required(name: str) -> str:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        raise ConfigurationError(f"required environment variable {name} is empty")
    return raw


def database_name(url: str) -> str:
    """Return only the URL database name. User, host, and query are ignored."""

    from sqlalchemy.engine.url import make_url

    name = make_url(url).database
    if name is None or name.strip() == "":
        raise ConfigurationError(f"{DATABASE_URL_ENV} has no database name")
    return name


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    internal_service_token: str
    bind_host: str
    port: int

    def public_view(self) -> dict[str, str | int]:
        return {"bind_host": self.bind_host, "port": self.port}


def load_settings() -> Settings:
    database_url = _required(DATABASE_URL_ENV)
    lowered = database_url.lower()
    if not (
        lowered.startswith("postgresql://")
        or lowered.startswith("postgresql+")
        or lowered.startswith("postgres://")
    ):
        raise ConfigurationError(f"{DATABASE_URL_ENV} must be a PostgreSQL URL")
    if database_name(database_url) in _FORBIDDEN_DATABASE_NAMES:
        raise ConfigurationError(
            f"{DATABASE_URL_ENV} must not target the customer_service database"
        )
    token = _required(INTERNAL_TOKEN_ENV)
    bind_host = os.environ.get(BIND_HOST_ENV, DEFAULT_BIND_HOST).strip()
    if bind_host == "":
        bind_host = DEFAULT_BIND_HOST
    return Settings(
        database_url=database_url,
        internal_service_token=token,
        bind_host=bind_host,
        port=DEFAULT_PORT,
    )


def load_seed_secrets() -> dict[str, str]:
    """Read the three required seed secrets. Values are never defaulted."""

    return {
        "owner": _required(OWNER_SECRET_ENV),
        "authorized_user": _required(AUTHORIZED_USER_SECRET_ENV),
        "advisor": _required(ADVISOR_SECRET_ENV),
    }
