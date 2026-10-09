"""Agent run queries and inserts."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from xp_ai_service.models.agent_run import AgentRun


class RunRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_request_id(self, request_id: str) -> AgentRun | None:
        statement = select(AgentRun).where(AgentRun.request_id == request_id)
        return self._session.execute(statement).scalar_one_or_none()

    def insert(self, values: dict[str, object]) -> AgentRun:
        row = AgentRun(**values)
        self._session.add(row)
        self._session.flush()
        return row
