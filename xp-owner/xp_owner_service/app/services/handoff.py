from xp_owner_service.app.repositories import conversation as conversations, handoff as handoffs, turn as turns
from xp_owner_service.app.services.realtime import record
from xp_owner_service.common import Rejected, new_id, now
from xp_owner_service.models import Handoff


def takeover(factory, identity, conversation_id, request_id):
    if identity["kind"] != "advisor":
        raise Rejected("身份无权", 403)
    with factory() as db, db.begin():
        conv = conversations.lock(db, conversation_id)
        if conv is None:
            raise Rejected("没有会话", 404)
        if conv.mode == "HUMAN":
            return {"已进入人工": "是", "重复": True}
        if conversations.enter_human(db, conv.id) is None:
            raise Rejected("当前模式不能接管")
        at = now()
        handoffs.insert(db, Handoff(id=new_id(), conversation_id=conv.id, advisor_id=identity["credential_id"], request_id=request_id, created_at=at))
        for turn in turns.unfinished(db, conv.id):
            turn.status, turn.invalidated_reason = "INVALIDATED", "已进入人工"
        record(db, conv.id, "已进入人工", {"会话编号": conv.id, "会话版本": conv.input_revision, "接管时间": at.isoformat()})
    return {"已进入人工": "是", "重复": False}
