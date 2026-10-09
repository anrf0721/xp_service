"""PostgreSQL engine. Parameters are hidden. Only the customer_service database is forbidden."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.engine.url import URL
from sqlalchemy.orm import Session, sessionmaker

from xp_ai_service.models.base import Base

FORBIDDEN_DATABASE = "customer_service"


class DatabaseUrlError(ValueError):
    """Raised when the database URL is not an allowed PostgreSQL URL."""


def parse_postgres_url(url: str) -> URL:
    try:
        parsed = make_url(url)
    except Exception as exc:
        raise DatabaseUrlError("database URL is invalid") from exc
    driver = parsed.drivername.lower()
    if driver not in {"postgresql", "postgresql+psycopg"}:
        raise DatabaseUrlError("database URL must use the postgresql driver")
    database = parsed.database
    if database is not None and database.lower() == FORBIDDEN_DATABASE:
        raise DatabaseUrlError("customer_service database is forbidden")
    return parsed


def assert_postgres_url(url: str) -> None:
    parse_postgres_url(url)


def create_engine_from_url(url: str) -> Engine:
    parsed = parse_postgres_url(url)
    if parsed.drivername.lower() == "postgresql":
        parsed = parsed.set(drivername="postgresql+psycopg")
    return create_engine(parsed, hide_parameters=True, pool_pre_ping=True)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def initialize_schema(engine: Engine) -> None:
    Base.metadata.create_all(engine)
