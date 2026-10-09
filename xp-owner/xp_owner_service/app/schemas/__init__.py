from pydantic import BaseModel, ConfigDict, Field


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MessageInput(Input):
    client_request_id: str = Field(min_length=1, max_length=128)
    body: str = Field(min_length=1)


class HandoffInput(Input):
    conversation_id: str
    request_id: str = Field(min_length=1, max_length=128)


class ClaimInput(Input):
    conversation_id: str
    worker_id: str = Field(default="owner-worker", min_length=1, max_length=128)


class PublishInput(Input):
    claim_id: str
    request_id: str
