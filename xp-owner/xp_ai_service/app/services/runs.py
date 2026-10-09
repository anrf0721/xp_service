"""Create or return a unique agent run, copying procedure text only."""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from xp_ai_service.app.repositories.runs import RunRepository
from xp_ai_service.app.schemas.runs import RunCreate, RunRead
from xp_ai_service.common.errors import ConflictError
from xp_ai_service.infrastructure.procedure_client import ProcedureClient, ProcedureRead
from xp_ai_service.models.agent_run import AgentRun


FAILURE_UNAVAILABLE = "流程已下架"
FAILURE_READ = "流程读取失败"


class RunService:
    def __init__(self, session: Session, procedure_client: ProcedureClient) -> None:
        self._session = session
        self._repository = RunRepository(session)
        self._procedure_client = procedure_client

    def get_by_request_id(self, request_id: str) -> RunRead | None:
        row = self._repository.get_by_request_id(request_id)
        if row is None:
            return None
        return _to_read(row)

    def create_or_get(self, payload: RunCreate) -> RunRead:
        existing = self._repository.get_by_request_id(payload.request_id)
        if existing is not None:
            _require_same_input(existing, payload)
            return _to_read(existing)

        procedure = self._procedure_client.read_current()
        values = _copy_fields(payload, procedure)
        try:
            self._repository.insert(values)
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            winner = self._repository.get_by_request_id(payload.request_id)
            if winner is None:
                raise
            _require_same_input(winner, payload)
            return _to_read(winner)
        except Exception:
            self._session.rollback()
            raise

        created = self._repository.get_by_request_id(payload.request_id)
        if created is None:
            raise RuntimeError("inserted run could not be read")
        return _to_read(created)


def _require_same_input(row: AgentRun, payload: RunCreate) -> None:
    if (
        row.turn_id != payload.turn_id
        or row.claim_id != payload.claim_id
        or row.snapshot_revision != payload.snapshot_revision
    ):
        raise ConflictError("request_id already exists with different input")


def _copy_fields(payload: RunCreate, procedure: ProcedureRead) -> dict[str, object]:
    values: dict[str, object] = {
        "request_id": payload.request_id,
        "turn_id": payload.turn_id,
        "claim_id": payload.claim_id,
        "snapshot_revision": payload.snapshot_revision,
        "flow_key": None,
        "cited_version_id": None,
        "version_label": None,
        "title": None,
        "steps": None,
        "boundary": None,
        "failure_reason": None,
    }
    if procedure.failure_reason is not None:
        values["failure_reason"] = procedure.failure_reason
        return values
    if not procedure.available:
        values["failure_reason"] = FAILURE_UNAVAILABLE
        return values
    values["flow_key"] = procedure.flow_key
    values["cited_version_id"] = procedure.version_id
    values["version_label"] = procedure.version_label
    values["title"] = procedure.title
    values["steps"] = procedure.steps
    values["boundary"] = procedure.boundary
    return values


def _to_read(row: AgentRun) -> RunRead:
    return RunRead(
        run_id=row.id,
        request_id=row.request_id,
        turn_id=row.turn_id,
        claim_id=row.claim_id,
        snapshot_revision=row.snapshot_revision,
        flow_key=row.flow_key,
        cited_version_id=row.cited_version_id,
        version_label=row.version_label,
        title=row.title,
        steps=row.steps,
        boundary=row.boundary,
        failure_reason=row.failure_reason,
    )
