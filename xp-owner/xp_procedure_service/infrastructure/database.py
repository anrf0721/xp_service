"""PostgreSQL engine and session factory. Tables are never created here."""

from __future__ import annotations

import os
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session, sessionmaker

from xp_procedure_service.infrastructure.config import Settings


def _url_with_pgoptions(database_url: str) -> str:
    """Forward PGOPTIONS through the URL. psycopg3 ignores the env var."""

    url = make_url(database_url)
    pgoptions = os.environ.get("PGOPTIONS")
    if pgoptions is None or pgoptions.strip() == "":
        return database_url
    query = dict(url.query)
    query["options"] = pgoptions
    return url.set(query=query).render_as_string(hide_password=False)


def create_engine_for(settings: Settings):
    return create_engine(
        _url_with_pgoptions(settings.database_url),
        pool_pre_ping=True,
        hide_parameters=True,
        echo=False,
    )


def create_session_factory(settings: Settings) -> sessionmaker[Session]:
    return sessionmaker(
        bind=create_engine_for(settings),
        autoflush=False,
        expire_on_commit=False,
    )


def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
    finally:
        session.close()
