"""客服模块是会话事实的权威，并决定候选能不能发布。"""

import uuid
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from person_vehicle import CUSTOMER_KINDS, KIND_DISPLAY, by_secret
from procedure_versions import lock_current, matches
from run_facts import load_run
from schema import (
    COLLECT_CAP_MS,
    COLLECT_PUSH_MS,
    CLAIM_LEASE_MS,
    EXACT_BODY,
    FLOW_KEY,
    MAX_RECLAIMS,
    Claim,
    Conversation,
    Credential,
    FollowUpTask,
    NoticeEvent,
    PublishedReply,
    Refusal,
    Takeover,
    TaskMessage,
    UserMessage,
)

REFUSAL_ORDER = (
    "已进入人工",
    "输入版本已失效",
    "领取编号不匹配",
    "租约已过期",
    "流程版本已不是当前发布版",
    "流程已下架",
    "展示字段违规",
    "执行超时",
    "流程读取失败",
)


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def accept(db: Session, secret: str, client_request_id: str, body: str, clock) -> dict:
    cred = by_secret(db, secret)
    if cred is None or cred.kind not in CUSTOMER_KINDS:
        _refuse(db, None if cred is None else cred.credential_id, None, "身份无权", clock)
        return {"ok": False, "reason": "身份无权"}
    conversation = _locked_conversation(db, cred)
    existing = db.scalar(
        select(UserMessage).where(
            UserMessage.session_id == conversation.session_id,
            UserMessage.client_request_id == client_request_id,
        )
    )
    if existing is not None:
        if existing.body != body:
            _refuse(db, cred.credential_id, conversation.session_id, "请求编号原文不一致", clock)
            return {"ok": False, "reason": "请求编号原文不一致"}
        return {"ok": True, "duplicate": True, "user_visible": _receipt(existing)}
    now = clock.now()
    conversation.version += 1
    message = UserMessage(
        message_id=_id("msg"),
        session_id=conversation.session_id,
        client_request_id=client_request_id,
        version=conversation.version,
        body=body,
        sender_kind=cred.kind,
        accepted_at=now,
    )
    db.add(message)
    db.flush()
    if conversation.bot_allowed:
        _attach_collecting(db, conversation, message, now)
    _event(
        db,
        conversation.session_id,
        "用户消息已受理",
        {
            "消息编号": message.message_id,
            "会话编号": conversation.session_id,
            "会话版本": conversation.version,
            "发送者凭证种类": KIND_DISPLAY[cred.kind],
            "用户原文": body,
            "受理时间": now.isoformat(),
        },
    )
    db.flush()
    return {"ok": True, "duplicate": False, "user_visible": _receipt(message)}


def duplicate_receipt(db: Session, secret: str, client_request_id: str, body: str) -> dict | None:
    cred = by_secret(db, secret)
    if cred is None:
        return None
    conversation = db.scalar(
        select(Conversation).where(Conversation.credential_id == cred.credential_id).with_for_update()
    )
    if conversation is None:
        return None
    existing = db.scalar(
        select(UserMessage).where(
            UserMessage.session_id == conversation.session_id,
            UserMessage.client_request_id == client_request_id,
            UserMessage.body == body,
        )
    )
    if existing is None:
        return None
    return _receipt(existing)


def claim(db: Session, session_id: str, claimer: str, clock) -> dict:
    now = clock.now()
    conversation = db.scalar(
        select(Conversation).where(Conversation.session_id == session_id).with_for_update()
    )
    if conversation is None or not conversation.bot_allowed:
        return {"ok": False, "reason": "已进入人工"}
    task = db.scalar(
        select(FollowUpTask)
        .where(
            FollowUpTask.session_id == session_id,
            FollowUpTask.kind == "collecting",
            FollowUpTask.status == "open",
            FollowUpTask.collect_until <= now,
        )
        .with_for_update()
    )
    if task is None:
        return {"ok": False, "reason": "收集未到点"}
    bodies = _bodies(db, task.task_id)
    if bodies != (EXACT_BODY,):
        task.kind = "human"
        task.status = "attention"
        task.collect_until = None
        db.flush()
        return {"ok": True, "routed": "human", "task_id": task.task_id}
    task.kind = "procedure"
    claim_id = _id("claim")
    task.status = "claimed"
    task.current_claim_id = claim_id
    task.claimed_version = conversation.version
    task.lease_until = now + timedelta(milliseconds=CLAIM_LEASE_MS)
    task.collect_until = None
    db.add(
        Claim(
            claim_id=claim_id,
            task_id=task.task_id,
            claimer=claimer,
            claimed_at=now,
            lease_until=task.lease_until,
            input_version=conversation.version,
            ordinal=1,
        )
    )
    db.flush()
    return {
        "ok": True,
        "routed": "procedure",
        "task_id": task.task_id,
        "claim_id": claim_id,
        "input_version": conversation.version,
    }


def reclaim(db: Session, task_id: str, claimer: str, clock) -> dict:
    now = clock.now()
    task = db.scalar(select(FollowUpTask).where(FollowUpTask.task_id == task_id).with_for_update())
    if task is None:
        return {"ok": False, "reason": "领取未成功"}
    conversation = db.scalar(
        select(Conversation).where(Conversation.session_id == task.session_id).with_for_update()
    )
    if (
        task.kind != "procedure"
        or task.status != "claimed"
        or not conversation.bot_allowed
        or task.lease_until is None
        or task.lease_until > now
        or task.reclaim_count >= MAX_RECLAIMS
    ):
        if task.reclaim_count >= MAX_RECLAIMS and task.lease_until is not None and task.lease_until <= now:
            return expire_final(db, task_id, clock)
        return {"ok": False, "reason": "重新领取未成功"}
    claim_id = _id("claim")
    updated = db.execute(
        update(FollowUpTask)
        .where(
            FollowUpTask.task_id == task_id,
            FollowUpTask.status == "claimed",
            FollowUpTask.current_claim_id.is_not(None),
            FollowUpTask.lease_until <= now,
            FollowUpTask.reclaim_count < MAX_RECLAIMS,
        )
        .values(
            current_claim_id=claim_id,
            lease_until=now + timedelta(milliseconds=CLAIM_LEASE_MS),
            reclaim_count=FollowUpTask.reclaim_count + 1,
            claimed_version=conversation.version,
        )
    )
    if updated.rowcount != 1:
        return {"ok": False, "reason": "重新领取未成功"}
    db.add(
        Claim(
            claim_id=claim_id,
            task_id=task_id,
            claimer=claimer,
            claimed_at=now,
            lease_until=now + timedelta(milliseconds=CLAIM_LEASE_MS),
            input_version=conversation.version,
            ordinal=2,
        )
    )
    db.flush()
    return {"ok": True, "claim_id": claim_id, "task_id": task_id, "input_version": conversation.version}


def expire_final(db: Session, task_id: str, clock) -> dict:
    task = db.scalar(select(FollowUpTask).where(FollowUpTask.task_id == task_id).with_for_update())
    conversation = db.scalar(
        select(Conversation).where(Conversation.session_id == task.session_id).with_for_update()
    )
    if task.reclaim_count < MAX_RECLAIMS or task.lease_until > clock.now() or task.status == "published":
        return {"ok": False, "reason": "尚未最终超时"}
    if task.status == "invalidated" and task.invalidated_reason == "执行超时":
        return {"ok": True, "duplicate": True}
    task.status = "invalidated"
    task.invalidated_reason = "执行超时"
    run_id = None
    if task.current_claim_id:
        run = load_run(db, task.current_claim_id)
        run_id = None if run is None else run.run_id
    _event(
        db,
        task.session_id,
        "运行未发布",
        _unpublished_payload(task, conversation, task.current_claim_id, run_id, "执行超时", None),
    )
    db.flush()
    return {"ok": True, "reason": "执行超时"}


def publish(db: Session, claim_id: str, clock) -> dict:
    claim = db.get(Claim, claim_id)
    if claim is None:
        _refuse(db, None, None, "领取编号不匹配", clock)
        return {"ok": False, "reason": "领取编号不匹配"}
    task_row = db.scalar(select(FollowUpTask.session_id).where(FollowUpTask.task_id == claim.task_id))
    conversation = db.scalar(
        select(Conversation).where(Conversation.session_id == task_row).with_for_update()
    )
    task = db.scalar(
        select(FollowUpTask).where(FollowUpTask.task_id == claim.task_id).with_for_update()
    )
    procedure = lock_current(db, FLOW_KEY)
    run = load_run(db, claim_id)
    if task.current_claim_id != claim_id:
        _refuse(db, None, conversation.session_id, "领取编号不匹配", clock)
        return {"ok": False, "reason": "领取编号不匹配", "left_task": True}
    existing_reply = db.scalar(select(PublishedReply).where(PublishedReply.task_id == task.task_id))
    if existing_reply is not None:
        return {"ok": True, "duplicate": True}
    refusal = _first_refusal(conversation, task, claim, procedure, run, False, clock)
    if refusal is None:
        fields = {
            "回复种类": "已审核流程说明",
            "流程键": procedure.flow_key,
            "版本编号": procedure.version_id,
            "版本标签": procedure.version_label,
            "标题": procedure.title,
            "步骤": procedure.steps,
            "边界句": procedure.boundary,
        }
        db.add(
            PublishedReply(
                reply_id=_id("reply"),
                task_id=task.task_id,
                claim_id=claim_id,
                run_id=run.run_id,
                session_id=conversation.session_id,
                input_version=claim.input_version,
                version_id=procedure.version_id,
                fields_json=fields,
            )
        )
        task.status = "published"
        _event(
            db,
            conversation.session_id,
            "回复已发布",
            {
                **fields,
                "任务编号": task.task_id,
                "领取编号": claim_id,
                "运行编号": run.run_id,
            },
        )
        db.flush()
        return {"ok": True}
    task.status = "invalidated"
    task.invalidated_reason = refusal
    _event(
        db,
        conversation.session_id,
        "运行未发布",
        _unpublished_payload(task, conversation, claim_id, None if run is None else run.run_id, refusal, run),
    )
    db.flush()
    return {"ok": False, "reason": refusal}


def publish_unknown(db: Session, task_id: str) -> dict:
    reply = db.scalar(select(PublishedReply).where(PublishedReply.task_id == task_id))
    if reply is None:
        return {"ok": False, "结果": "不明"}
    return {"ok": True, "reply_id": reply.reply_id}


def takeover(db: Session, secret: str, request_id: str, clock) -> dict:
    cred = by_secret(db, secret)
    if cred is None or cred.kind != "advisor":
        _refuse(db, None if cred is None else cred.credential_id, None, "身份无权", clock)
        return {"ok": False, "reason": "身份无权"}
    conversations = db.scalars(select(Conversation).order_by(Conversation.session_id)).all()
    if not conversations:
        return {"ok": False, "reason": "没有会话"}
    done = []
    for conversation in conversations:
        locked = db.scalar(
            select(Conversation)
            .where(Conversation.session_id == conversation.session_id)
            .with_for_update()
        )
        inserted = db.execute(
            pg_insert(Takeover)
            .values(session_id=locked.session_id, request_id=request_id)
            .on_conflict_do_nothing(index_elements=["session_id", "request_id"])
        )
        if inserted.rowcount != 1:
            done.append({"session_id": locked.session_id, "duplicate": True})
            continue
        updated = db.execute(
            update(Conversation)
            .where(Conversation.session_id == locked.session_id, Conversation.bot_allowed.is_(True))
            .values(bot_allowed=False)
        )
        if updated.rowcount != 1:
            done.append({"session_id": locked.session_id, "duplicate": True})
            continue
        db.execute(
            update(FollowUpTask)
            .where(
                FollowUpTask.session_id == locked.session_id,
                FollowUpTask.status.in_(("open", "claimed")),
                FollowUpTask.kind.in_(("collecting", "procedure")),
            )
            .values(status="invalidated", invalidated_reason="已进入人工")
        )
        _event(
            db,
            locked.session_id,
            "已进入人工",
            {
                "会话编号": locked.session_id,
                "会话版本": locked.version,
                "接管时间": clock.now().isoformat(),
            },
        )
        done.append({"session_id": locked.session_id, "duplicate": False})
    db.flush()
    return {"ok": True, "sessions": done}


def takeover_session(db: Session, secret: str, session_id: str, request_id: str, clock) -> dict:
    cred = by_secret(db, secret)
    if cred is None or cred.kind != "advisor":
        _refuse(db, None if cred is None else cred.credential_id, session_id, "身份无权", clock)
        return {"ok": False, "reason": "身份无权"}
    locked = db.scalar(
        select(Conversation).where(Conversation.session_id == session_id).with_for_update()
    )
    if locked is None:
        return {"ok": False, "reason": "没有会话"}
    if not locked.bot_allowed:
        return {"ok": True, "duplicate": True, "session_id": session_id}
    db.add(Takeover(session_id=session_id, request_id=request_id))
    locked.bot_allowed = False
    db.execute(
        update(FollowUpTask)
        .where(
            FollowUpTask.session_id == session_id,
            FollowUpTask.status.in_(("open", "claimed")),
            FollowUpTask.kind.in_(("collecting", "procedure")),
        )
        .values(status="invalidated", invalidated_reason="已进入人工")
    )
    _event(
        db,
        session_id,
        "已进入人工",
        {"会话编号": session_id, "会话版本": locked.version, "接管时间": clock.now().isoformat()},
    )
    db.flush()
    return {"ok": True, "duplicate": False, "session_id": session_id}


def fetch_user(db: Session, secret: str, after_seq: int = 0) -> dict:
    cred = by_secret(db, secret)
    if cred is None or cred.kind not in CUSTOMER_KINDS:
        return {"ok": False, "reason": "身份无权", "items": []}
    conversation = db.scalar(select(Conversation).where(Conversation.credential_id == cred.credential_id))
    if conversation is None:
        return {"ok": True, "items": []}
    rows = db.scalars(
        select(NoticeEvent)
        .where(
            NoticeEvent.session_id == conversation.session_id,
            NoticeEvent.seq > after_seq,
            NoticeEvent.kind.in_(("回复已发布", "已进入人工")),
        )
        .order_by(NoticeEvent.seq)
    ).all()
    return {"ok": True, "items": [_user_item(row) for row in _dedupe(rows)]}


def fetch_advisor(db: Session, secret: str, session_id: str, after_seq: int = 0) -> dict:
    cred = by_secret(db, secret)
    if cred is None or cred.kind != "advisor":
        return {"ok": False, "reason": "身份无权", "items": []}
    rows = db.scalars(
        select(NoticeEvent)
        .where(NoticeEvent.session_id == session_id, NoticeEvent.seq > after_seq)
        .order_by(NoticeEvent.seq)
    ).all()
    return {"ok": True, "items": [_advisor_item(row) for row in _dedupe(rows)]}


def counts(db: Session) -> dict:
    def n(model) -> int:
        return db.scalar(select(func.count()).select_from(model))

    return {
        "messages": n(UserMessage),
        "tasks": n(FollowUpTask),
        "events": n(NoticeEvent),
        "runs": n(__import__("schema").RunRecord),
        "replies": n(PublishedReply),
        "claims": n(Claim),
    }


def _locked_conversation(db: Session, cred: Credential) -> Conversation:
    conversation = db.scalar(
        select(Conversation).where(Conversation.credential_id == cred.credential_id).with_for_update()
    )
    if conversation is not None:
        return conversation
    conversation = Conversation(
        session_id=_id("sess"),
        credential_id=cred.credential_id,
        sender_kind=cred.kind,
        version=0,
        bot_allowed=True,
    )
    db.add(conversation)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise
    return db.scalar(
        select(Conversation).where(Conversation.session_id == conversation.session_id).with_for_update()
    )


def _attach_collecting(db: Session, conversation: Conversation, message: UserMessage, now) -> None:
    task = db.scalar(
        select(FollowUpTask)
        .where(
            FollowUpTask.session_id == conversation.session_id,
            FollowUpTask.kind == "collecting",
            FollowUpTask.status == "open",
        )
        .with_for_update()
    )
    if task is None:
        task = FollowUpTask(
            task_id=_id("task"),
            session_id=conversation.session_id,
            kind="collecting",
            status="open",
            opened_at=now,
            collect_until=now + timedelta(milliseconds=COLLECT_PUSH_MS),
            reclaim_count=0,
        )
        db.add(task)
        db.flush()
        position = 1
    else:
        cap = task.opened_at + timedelta(milliseconds=COLLECT_CAP_MS)
        pushed = now + timedelta(milliseconds=COLLECT_PUSH_MS)
        task.collect_until = pushed if pushed < cap else cap
        position = db.scalar(
            select(func.coalesce(func.max(TaskMessage.position), 0) + 1).where(
                TaskMessage.task_id == task.task_id
            )
        )
    db.add(TaskMessage(task_id=task.task_id, message_id=message.message_id, position=position))


def _bodies(db: Session, task_id: str) -> tuple[str, ...]:
    rows = db.execute(
        select(UserMessage.body)
        .join(TaskMessage, TaskMessage.message_id == UserMessage.message_id)
        .where(TaskMessage.task_id == task_id)
        .order_by(TaskMessage.position)
    ).all()
    return tuple(row[0] for row in rows)


def _first_refusal(conversation, task, claim, procedure, run, reply_exists, clock) -> str | None:
    if not conversation.bot_allowed or task.invalidated_reason == "已进入人工":
        return "已进入人工"
    if claim.input_version != conversation.version or task.claimed_version != conversation.version:
        return "输入版本已失效"
    if task.current_claim_id != claim.claim_id:
        return "领取编号不匹配"
    if task.lease_until is None or task.lease_until <= clock.now():
        return "租约已过期"
    if procedure is None:
        return "流程已下架"
    if run is None:
        return "流程读取失败"
    if run.failure_reason == "执行超时":
        return "执行超时"
    if run.failure_reason == "流程读取失败":
        return "流程读取失败"
    if run.failure_reason == "流程已下架" or run.cited_version_id is None:
        return "流程已下架"
    if not procedure.current_published or procedure.withdrawn or procedure.version_id != run.cited_version_id:
        return "流程版本已不是当前发布版" if procedure.version_id != run.cited_version_id or not procedure.current_published else "流程已下架"
    if not matches(procedure, run) or run.steps != procedure.steps or run.title != procedure.title or run.boundary != procedure.boundary:
        return "展示字段违规"
    if reply_exists or task.status == "published":
        return "任务已有可见结果"
    return None


def _unpublished_payload(task, conversation, claim_id, run_id, refusal, run) -> dict:
    return {
        "任务编号": task.task_id,
        "领取编号": claim_id,
        "运行编号": run_id,
        "失败原因": refusal,
        "输入会话版本": None if claim_id is None else task.claimed_version,
        "拒绝时的当前会话版本": conversation.version,
        "引用的流程版本编号": None if run is None else run.cited_version_id,
    }


def _event(db: Session, session_id: str, kind: str, payload: dict) -> None:
    seq = db.scalar(
        select(func.coalesce(func.max(NoticeEvent.seq), 0) + 1).where(NoticeEvent.session_id == session_id)
    )
    body = dict(payload)
    body["事件种类"] = kind
    db.add(
        NoticeEvent(
            event_id=_id("ev"),
            session_id=session_id,
            seq=seq,
            kind=kind,
            payload=body,
        )
    )


def _receipt(message: UserMessage) -> dict:
    return {
        "消息编号": message.message_id,
        "会话编号": message.session_id,
        "会话版本": message.version,
        "已接收": "是",
    }


def _refuse(db: Session, credential_id, session_id, reason: str, clock) -> None:
    db.add(
        Refusal(
            refusal_id=_id("refusal"),
            credential_id=credential_id,
            session_id=session_id,
            reason=reason,
            refused_at=clock.now(),
        )
    )
    db.flush()


def _dedupe(rows):
    seen = set()
    result = []
    for row in rows:
        if row.event_id in seen:
            continue
        seen.add(row.event_id)
        result.append(row)
    return result


def _user_item(row: NoticeEvent) -> dict:
    payload = row.payload
    if row.kind == "回复已发布":
        return {
            "事件编号": row.event_id,
            "事件序号": row.seq,
            "事件种类": "回复已发布",
            "回复种类": "已审核流程说明",
            "流程键": FLOW_KEY,
            "版本编号": payload["版本编号"],
            "版本标签": payload["版本标签"],
            "标题": payload["标题"],
            "步骤": payload["步骤"],
            "边界句": payload["边界句"],
        }
    return {
        "事件编号": row.event_id,
        "事件序号": row.seq,
        "事件种类": "已进入人工",
        "会话编号": payload["会话编号"],
        "会话版本": payload["会话版本"],
        "接管时间": payload["接管时间"],
    }


def _advisor_item(row: NoticeEvent) -> dict:
    payload = row.payload
    base = {"事件编号": row.event_id, "事件序号": row.seq, "事件种类": row.kind}
    if row.kind == "用户消息已受理":
        base.update(
            {
                "消息编号": payload["消息编号"],
                "会话编号": payload["会话编号"],
                "会话版本": payload["会话版本"],
                "发送者凭证种类": payload["发送者凭证种类"],
                "用户原文": payload["用户原文"],
                "受理时间": payload["受理时间"],
            }
        )
        return base
    if row.kind == "回复已发布":
        visible = _user_item(row)
        visible.update(
            {
                "任务编号": payload["任务编号"],
                "领取编号": payload["领取编号"],
                "运行编号": payload["运行编号"],
            }
        )
        return visible
    if row.kind == "已进入人工":
        return _user_item(row)
    if row.kind == "运行未发布":
        base.update(
            {
                "任务编号": payload["任务编号"],
                "领取编号": payload["领取编号"],
                "运行编号": payload["运行编号"],
                "失败原因": payload["失败原因"],
                "输入会话版本": payload["输入会话版本"],
                "拒绝时的当前会话版本": payload["拒绝时的当前会话版本"],
                "引用的流程版本编号": payload["引用的流程版本编号"],
            }
        )
        return base
    raise RuntimeError("未列明的事件种类")


def session_id_for(db: Session, secret: str) -> str | None:
    cred = by_secret(db, secret)
    if cred is None:
        return None
    conversation = db.scalar(select(Conversation).where(Conversation.credential_id == cred.credential_id))
    return None if conversation is None else conversation.session_id


def credential_of(db: Session, secret: str) -> Credential | None:
    return by_secret(db, secret)
