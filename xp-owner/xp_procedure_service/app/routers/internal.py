"""Internal procedure routes. Every route requires the service token."""

from typing import Annotated

from fastapi import Depends, FastAPI, Query

from xp_procedure_service.app.dependencies import (
    get_procedure_service,
    require_internal_token,
)
from xp_procedure_service.app.schemas.procedure import (
    CurrentProcedureResponse,
    UnavailableProcedureResponse,
)
from xp_procedure_service.app.services.procedure_service import ProcedureService

def register(app: FastAPI) -> None:
    app.add_api_route(
        "/internal/procedures/current",
        current_procedure,
        methods=["GET"],
        response_model=CurrentProcedureResponse | UnavailableProcedureResponse,
        dependencies=[Depends(require_internal_token)],
    )


def current_procedure(
    flow_key: Annotated[str, Query(min_length=1)],
    procedure_service: ProcedureService = Depends(get_procedure_service),
) -> CurrentProcedureResponse | UnavailableProcedureResponse:
    current = procedure_service.current(flow_key)
    if not current.available:
        return UnavailableProcedureResponse(available=False)
    return CurrentProcedureResponse(
        available=True,
        flow_key=current.flow_key,
        version_id=current.version_id,
        version_label=current.version_label,
        title=current.title,
        steps=current.steps,
        boundary=current.boundary,
    )
