"""Current procedure contract. Unavailable is an explicit false, not an error."""

from pydantic import BaseModel


class UnavailableProcedureResponse(BaseModel):
    available: bool = False


class CurrentProcedureResponse(BaseModel):
    available: bool = True
    flow_key: str
    version_id: str
    version_label: str
    title: str
    steps: str
    boundary: str
