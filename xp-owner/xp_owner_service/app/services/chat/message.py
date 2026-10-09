from datetime import timedelta

from xp_owner_service.app.repositories import messages, turn as turns
from xp_owner_service.app.services.chat.conversation import open_locked
from xp_owner_service.app.services.realtime import record
from xp_owner_service.common import COLLECT_MS, MAX_COLLECT_MS, Rejected, new_id, now
from xp_owner_service.models import ConversationTurn, Message

KINDS = {"owner": "车主", "authorized_user": "授权用车人"}


def receipt(message):
    return {"消息编号": message.id, "会话编号": message.conversation_id, "会话版本": message.revision, "已接收": "是"}


def accept(factory, identity, request_id, body):
    if identity["kind"] not in KINDS:
        raise Rejected("身份无权", 403)
    with factory() as db, db.begin():
        conv = open_locked(db, identity["credential_id"])
        existing = messages.get_request(db, conv.id, request_id)
        if existing is not None:
            if existing.body != body:
                raise Rejected("请求编号原文不一致")
            answer = receipt(existing)
        else:
            at = now()
            conv.input_revision += 1
            msg = messages.insert(db, Message(id=new_id(), conversation_id=conv.id, client_request_id=request_id,
                revision=conv.input_revision, role="USER", credential_kind=identity["kind"], body=body, created_at=at))
            if conv.mode == "AI":
                turn = turns.collecting(db, conv.id)
                if turn is None:
                    turn = turns.insert(db, ConversationTurn(id=new_id(), conversation_id=conv.id, status="COLLECTING", started_at=at,
                        collect_until=at + timedelta(milliseconds=COLLECT_MS), max_collect_until=at + timedelta(milliseconds=MAX_COLLECT_MS), attempts=0))
                else:
                    turn.collect_until = min(turn.collect_until + timedelta(milliseconds=COLLECT_MS), turn.max_collect_until)
                messages.attach(db, turn.id, msg.id)
            record(db, conv.id, "用户消息已受理", {"消息编号": msg.id, "会话编号": conv.id, "会话版本": conv.input_revision,
                "发送者凭证种类": KINDS[identity["kind"]], "用户原文": body, "受理时间": at.isoformat()})
            answer = receipt(msg)
    # Context exit commits all acceptance facts and releases locks before return.
    return answer
