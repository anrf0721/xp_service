"""Run wire models. Extra fields are forbidden so callers cannot inject failure flags."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    turn_id: str = Field(min_length=1)
    claim_id: str = Field(min_length=1)
    snapshot_revision: int


class RunRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    request_id: str
    turn_id: str
    claim_id: str
    snapshot_revision: int
    flow_key: str | None = None
    cited_version_id: str | None = None
    version_label: str | None = None
    title: str | None = None
    steps: str | None = None
    boundary: str | None = None
    failure_reason: str | None = None
