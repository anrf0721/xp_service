"""SQL for procedure versions. Callers own the transaction."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from xp_procedure_service.models.procedure_version import ProcedureVersion


class ProcedureRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, version_id: str) -> ProcedureVersion | None:
        statement = select(ProcedureVersion).where(
            ProcedureVersion.version_id == version_id
        )
        return self._session.scalars(statement).one_or_none()

    def get_current(self, flow_key: str) -> ProcedureVersion | None:
        statement = select(ProcedureVersion).where(
            ProcedureVersion.flow_key == flow_key,
            ProcedureVersion.current_published.is_(True),
            ProcedureVersion.withdrawn.is_(False),
        )
        return self._session.scalars(statement).one_or_none()

    def add_if_absent(self, version: ProcedureVersion) -> bool:
        existing = self.get_by_id(version.version_id)
        if existing is not None:
            return False
        self._session.add(version)
        return True
