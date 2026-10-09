from fastapi import APIRouter, Depends

from xp_owner_service.app.dependencies import advisor_identity, factory
from xp_owner_service.app.schemas import HandoffInput
from xp_owner_service.app.services.handoff import takeover

router = APIRouter()


@router.post("/handoff")
def handoff(body: HandoffInput, identity=Depends(advisor_identity), db_factory=Depends(factory)):
    return takeover(db_factory, identity, body.conversation_id, body.request_id)
