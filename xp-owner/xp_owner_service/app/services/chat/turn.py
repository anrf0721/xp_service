from datetime import timedelta

from xp_owner_service.app.repositories import conversation as conversations, messages, turn as turns
from xp_owner_service.app.services.realtime import record
from xp_owner_service.common import EXACT_QUESTION, LEASE_SECONDS, MAX_ATTEMPTS, new_id, now
from xp_owner_service.models import Claim


def unpublished(db, conv, turn, claim, reason):
    if claim.failure_reason == reason:
        return
    claim.failure_reason = reason
    record(db, conv.id, "运行未发布", {"任务编号": turn.id, "领取编号": claim.id, "运行编号": claim.run_id,
        "失败原因": reason, "输入会话版本": claim.snapshot_revision, "拒绝时的当前会话版本": conv.input_revision,
        "引用的流程版本编号": claim.cited_version_id})


def claim_next(factory, conversation_id, worker_id):
    with factory() as db, db.begin():
        conv = conversations.lock(db, conversation_id)
        if conv is None or conv.mode != "AI":
            return {"claimed": False, "reason": "已进入人工"}
        at = now()
        active = turns.running(db, conversation_id)
        if active is not None:
            if turns.published(db, active.id) is not None:
                return {"claimed": False, "reason": "已有已发布回复"}
            if active.locked_until > at:
                return {"claimed": False, "reason": "已有运行轮次"}
            old_claim = turns.claim(db, active.current_claim_id)
            if active.snapshot_revision != conv.input_revision:
                active.status, active.invalidated_reason = "SUPERSEDED", "输入版本已失效"
                unpublished(db, conv, active, old_claim, "输入版本已失效")
                db.flush()
                return {"claimed": False, "reason": "输入版本已失效"}
            if active.attempts >= MAX_ATTEMPTS:
                active.status, active.invalidated_reason = "TIMED_OUT", "执行超时"
                unpublished(db, conv, active, old_claim, "执行超时")
                db.flush()
                return {"claimed": False, "reason": "执行超时"}
            turn = active
        else:
            turn = turns.collecting(db, conversation_id)
            if turn is None or turn.collect_until > at:
                return {"claimed": False, "reason": "收集未到点"}
            originals = messages.for_turn(db, turn.id)
            if len(originals) != 1 or originals[0].body != EXACT_QUESTION:
                turn.status = "ATTENTION"
                return {"claimed": False, "reason": "需要人工关注", "turn_id": turn.id}
        snapshot = conv.input_revision if turn.snapshot_revision is None else turn.snapshot_revision
        claim_id, request_id = new_id(), new_id()
        ordinal, until = turn.attempts + 1, at + timedelta(seconds=LEASE_SECONDS)
        changed = turns.conditional_claim(db, turn.id, turn.status, turn.current_claim_id, turn.attempts,
            status="RUNNING", current_claim_id=claim_id, attempts=ordinal, locked_by=worker_id, locked_until=until,
            snapshot_revision=snapshot, collect_until=None)
        if changed is None:
            return {"claimed": False, "reason": "领取未成功"}
        turns.insert(db, Claim(id=claim_id, turn_id=turn.id, request_id=request_id, snapshot_revision=snapshot,
            ordinal=ordinal, claimed_at=at, locked_until=until))
        answer = {"claimed": True, "turn_id": turn.id, "claim_id": claim_id, "request_id": request_id,
            "snapshot_revision": snapshot, "locked_until": until.isoformat(), "attempt": ordinal}
    return answer


def candidates(factory):
    with factory() as db, db.begin():
        return turns.candidate_conversations(db, now())


def published_reply(factory, turn_id):
    with factory() as db, db.begin():
        reply = turns.published(db, turn_id)
        return {"published": reply is not None}
