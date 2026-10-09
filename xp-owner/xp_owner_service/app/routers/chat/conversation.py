from fastapi import APIRouter, Depends, Query

from xp_owner_service.app.dependencies import advisor_identity, factory, user_identity
from xp_owner_service.app.services.chat.conversation import current
from xp_owner_service.app.services.realtime import fetch

router = APIRouter()


@router.get("/chat/conversation")
def current_conversation(identity=Depends(user_identity), db_factory=Depends(factory)):
    return current(db_factory, identity)


@router.get("/chat/conversations/{conversation_id}/events")
def user_events(conversation_id: str, after_seq: int = Query(default=0, ge=0), identity=Depends(user_identity), db_factory=Depends(factory)):
    return fetch(db_factory, identity, conversation_id, after_seq)


@router.get("/advisor/conversations/{conversation_id}/events")
def advisor_events(conversation_id: str, after_seq: int = Query(default=0, ge=0), identity=Depends(advisor_identity), db_factory=Depends(factory)):
    return fetch(db_factory, identity, conversation_id, after_seq, advisor=True)
