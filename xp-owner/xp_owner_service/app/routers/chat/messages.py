from fastapi import APIRouter, Depends

from xp_owner_service.app.dependencies import factory, user_identity
from xp_owner_service.app.schemas import MessageInput
from xp_owner_service.app.services.chat.message import accept

router = APIRouter(prefix="/chat")


@router.post("/messages")
def post_message(body: MessageInput, identity=Depends(user_identity), db_factory=Depends(factory)):
    return accept(db_factory, identity, body.client_request_id, body.body)
