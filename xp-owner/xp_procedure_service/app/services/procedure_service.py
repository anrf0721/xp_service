"""Read the current published version and seed the placeholder. Owns transactions."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from xp_procedure_service.app.repositories.procedure_repository import (
    ProcedureRepository,
)
from xp_procedure_service.models.procedure_version import ProcedureVersion

PLACEHOLDER_VERSION_ID = "placeholder-v1"
PLACEHOLDER_VERSION_LABEL = "占位审核版"
PLACEHOLDER_FLOW_KEY = "App预约保养步骤"
PLACEHOLDER_TITLE = "App 预约保养步骤"
PLACEHOLDER_STEPS = (
    "【非官方占位】此处不是小鹏官方步骤。上线前必须替换为人工审核原句。"
)
PLACEHOLDER_BOUNDARY = (
    "这只说明 App 里的预约步骤，不表示已经预约成功，也不表示这台车在保。"
)


@dataclass(frozen=True, slots=True)
class CurrentProcedure:
    available: bool
    flow_key: str = ""
    version_id: str = ""
    version_label: str = ""
    title: str = ""
    steps: str = ""
    boundary: str = ""


class ProcedureService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def current(self, flow_key: str) -> CurrentProcedure:
        session = self._session_factory()
        try:
            version = ProcedureRepository(session).get_current(flow_key)
            if version is None:
                return CurrentProcedure(available=False)
            return CurrentProcedure(
                available=True,
                flow_key=version.flow_key,
                version_id=version.version_id,
                version_label=version.version_label,
                title=version.title,
                steps=version.steps,
                boundary=version.boundary,
            )
        finally:
            session.close()

    def seed(self) -> None:
        """Insert the fixed placeholder if its id is absent. Never rewrite it."""

        session = self._session_factory()
        try:
            ProcedureRepository(session).add_if_absent(
                ProcedureVersion(
                    version_id=PLACEHOLDER_VERSION_ID,
                    version_label=PLACEHOLDER_VERSION_LABEL,
                    flow_key=PLACEHOLDER_FLOW_KEY,
                    title=PLACEHOLDER_TITLE,
                    steps=PLACEHOLDER_STEPS,
                    boundary=PLACEHOLDER_BOUNDARY,
                    current_published=True,
                    withdrawn=False,
                )
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
