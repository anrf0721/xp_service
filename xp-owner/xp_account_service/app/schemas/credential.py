"""Credential verification contract. The secret is request-only."""

from pydantic import BaseModel, ConfigDict, Field


class VerifyCredentialRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    secret: str = Field(min_length=1)


class VerifyCredentialResponse(BaseModel):
    credential_id: str
    kind: str
