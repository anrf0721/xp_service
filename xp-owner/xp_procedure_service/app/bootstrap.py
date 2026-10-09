"""Explicit schema initialization. Never called by ordinary startup."""

from __future__ import annotations

from xp_procedure_service.app.services.procedure_service import ProcedureService
from xp_procedure_service.infrastructure.config import Settings
from xp_procedure_service.infrastructure.database import (
    create_engine_for,
    create_session_factory,
)
from xp_procedure_service.models.base import Base
from xp_procedure_service.models.procedure_version import ProcedureVersion  # noqa: F401


def initialize(settings: Settings) -> None:
    engine = create_engine_for(settings)
    Base.metadata.create_all(engine)
    engine.dispose()
    ProcedureService(create_session_factory(settings)).seed()
