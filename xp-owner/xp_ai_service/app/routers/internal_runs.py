"""Internal run routes. Identity is checked here; transactions stay in the service."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from xp_ai_service.app.dependencies import get_db_session, get_procedure_client, require_internal_token
from xp_ai_service.app.schemas.runs import RunCreate, RunRead
from xp_ai_service.app.services.runs import RunService
from xp_ai_service.infrastructure.procedure_client import ProcedureClient

router = APIRouter(prefix="/internal", dependencies=[Depends(require_internal_token)])


def get_run_service(
    session: Session = Depends(get_db_session),
    procedure_client: ProcedureClient = Depends(get_procedure_client),
) -> RunService:
    return RunService(session, procedure_client)


@router.post("/runs", response_model=RunRead)
def create_run(payload: RunCreate, service: RunService = Depends(get_run_service)) -> RunRead:
    try:
        return service.create_or_get(payload)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/runs/by-request/{request_id}", response_model=RunRead)
def get_run_by_request(request_id: str, service: RunService = Depends(get_run_service)) -> RunRead:
    found = service.get_by_request_id(request_id)
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    return found
