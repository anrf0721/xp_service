from fastapi import APIRouter, Depends

from xp_owner_service.app.dependencies import factory, internal_identity
from xp_owner_service.app.schemas import ClaimInput, PublishInput
from xp_owner_service.app.services.chat.turn import claim_next, published_reply
from xp_owner_service.worker.ai.worker import publish_request, run_once

router = APIRouter(prefix="/internal", dependencies=[Depends(internal_identity)])


@router.post("/turns/claim")
def claim(body: ClaimInput, db_factory=Depends(factory)):
    return claim_next(db_factory, body.conversation_id, body.worker_id)


@router.post("/results/publish")
def publish(body: PublishInput, db_factory=Depends(factory)):
    return publish_request(db_factory, body.claim_id, body.request_id)


@router.get("/turns/{turn_id}/reply")
def reply(turn_id: str, db_factory=Depends(factory)):
    return published_reply(db_factory, turn_id)


@router.post("/worker/tick")
def tick(db_factory=Depends(factory)):
    return {"results": run_once(db_factory)}
