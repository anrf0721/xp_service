from xp_owner_service.app.repositories import conversation as conversations, outbox
from xp_owner_service.common import Rejected, new_id
from xp_owner_service.models import ConversationEvent, RealtimeOutbox

BASE = {"事件编号", "事件序号", "事件种类"}
PUBLISHED = {"回复种类", "流程键", "版本编号", "版本标签", "标题", "步骤", "边界句"}
TAKEN = {"会话编号", "会话版本", "接管时间"}
ACCEPTED = {"消息编号", "会话编号", "会话版本", "发送者凭证种类", "用户原文", "受理时间"}
UNPUBLISHED = {"任务编号", "领取编号", "运行编号", "失败原因", "输入会话版本", "拒绝时的当前会话版本", "引用的流程版本编号"}
ADVISOR_EXTRA = {"任务编号", "领取编号", "运行编号"}


def record(db, conversation_id, kind, payload):
    event = outbox.insert_event(db, ConversationEvent(id=new_id(), conversation_id=conversation_id, kind=kind, payload=payload))
    body = {"事件编号": event.id, "事件序号": event.sequence, "事件种类": kind, **payload}
    outbox.insert_outbox(db, RealtimeOutbox(id=new_id(), event_id=event.id, conversation_id=conversation_id, kind=kind, payload=body, delivered=False))
    return event


def fetch(factory, identity, conversation_id, after_seq, advisor=False):
    with factory() as db, db.begin():
        conv = conversations.lock(db, conversation_id)
        if conv is None:
            raise Rejected("没有会话", 404)
        if advisor:
            if identity["kind"] != "advisor":
                raise Rejected("身份无权", 403)
        elif identity["kind"] not in ("owner", "authorized_user") or conv.credential_id != identity["credential_id"]:
            raise Rejected("身份无权", 403)
        items, seen = [], set()
        for event in outbox.events_after(db, conversation_id, after_seq):
            keys = None
            if event.kind == "回复已发布":
                keys = PUBLISHED | (ADVISOR_EXTRA if advisor else set())
            elif event.kind == "已进入人工":
                keys = TAKEN
            elif advisor and event.kind == "用户消息已受理":
                keys = ACCEPTED
            elif advisor and event.kind == "运行未发布":
                keys = UNPUBLISHED
            if keys is not None and event.id not in seen:
                seen.add(event.id)
                items.append({"事件编号": event.id, "事件序号": event.sequence, "事件种类": event.kind, **{key: event.payload[key] for key in keys}})
        return {"items": items}
