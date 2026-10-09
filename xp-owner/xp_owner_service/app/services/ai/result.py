from xp_owner_service.app.repositories import conversation as conversations, turn as turns
from xp_owner_service.app.services.chat.turn import unpublished
from xp_owner_service.app.services.realtime import record
from xp_owner_service.common import FLOW_KEY, Rejected, new_id, now
from xp_owner_service.infrastructure.http import current_procedure
from xp_owner_service.models import PublishedReply


def first_failure(conv, turn, claim, run, current, read_failed):
    if claim.snapshot_revision != conv.input_revision:
        return "输入版本已失效"
    if turn.current_claim_id != claim.id:
        return "领取编号不匹配"
    if turn.locked_until is None or turn.locked_until <= now():
        return "租约已过期"
    if conv.mode != "AI":
        return "已进入人工"
    if current is not None and current.get("available") and run.get("cited_version_id") is not None and current.get("version_id") != run.get("cited_version_id"):
        return "流程版本已不是当前发布版"
    if current is not None and not current.get("available"):
        return "流程已下架"
    if run.get("failure_reason") == "流程已下架":
        return "流程已下架"
    if run.get("failure_reason") is None and current is not None and current.get("available"):
        pairs = (("title", "title"), ("steps", "steps"), ("boundary", "boundary"), ("version_label", "version_label"), ("cited_version_id", "version_id"))
        if (run.get("flow_key") != FLOW_KEY or current.get("flow_key") != FLOW_KEY
                or any(type(run.get(left)) is not str or run[left] != current.get(right) for left, right in pairs)
                or run.get("request_id") != claim.request_id or run.get("claim_id") != claim.id
                or run.get("turn_id") != turn.id or run.get("snapshot_revision") != claim.snapshot_revision
                or not isinstance(run.get("run_id"), str) or turn.status != "RUNNING"):
            return "展示字段违规"
    if turn.status == "TIMED_OUT":
        return "执行超时"
    if read_failed or run.get("failure_reason") == "流程读取失败":
        return "流程读取失败"
    if turn.status != "RUNNING":
        return "展示字段违规"
    return None


def publish(factory, claim_id, run):
    with factory() as db, db.begin():
        claim = turns.claim(db, claim_id)
        if claim is None:
            raise Rejected("领取编号不匹配", 404)
        original = turns.get(db, claim.turn_id)
        conv = conversations.lock(db, original.conversation_id)
        turn = turns.lock(db, claim.turn_id)
        if turns.published(db, turn.id) is not None:
            return {"published": True, "duplicate": True}
        # A superseded worker must not mutate the new claimant or append a failure.
        if turn.current_claim_id != claim.id:
            reason = "输入版本已失效" if claim.snapshot_revision != conv.input_revision else "领取编号不匹配"
            return {"published": False, "reason": reason}
        if run is None:
            return {"published": False, "pending": True}
        if claim.failure_reason is not None and turn.status != "RUNNING":
            return {"published": False, "reason": claim.failure_reason, "duplicate": True}
        # This is an HTTP reread, never a cross-database SELECT FOR UPDATE.
        current, read_failed = None, False
        try:
            current = current_procedure()
            if not isinstance(current, dict) or type(current.get("available")) is not bool:
                current, read_failed = None, True
        except Exception:
            read_failed = True
        reason = first_failure(conv, turn, claim, run, current, read_failed)
        claim.run_id, claim.cited_version_id = run.get("run_id"), run.get("cited_version_id")
        if reason is not None:
            unpublished(db, conv, turn, claim, reason)
            if reason == "输入版本已失效":
                turn.status, turn.invalidated_reason = "SUPERSEDED", reason
            elif reason == "已进入人工":
                turn.status, turn.invalidated_reason = "INVALIDATED", reason
            elif reason != "租约已过期":
                turn.status, turn.invalidated_reason = "FAILED", reason
            answer = {"published": False, "reason": reason}
        else:
            fields = {"回复种类": "已审核流程说明", "流程键": FLOW_KEY, "版本编号": current["version_id"],
                "版本标签": current["version_label"], "标题": current["title"], "步骤": current["steps"], "边界句": current["boundary"]}
            turns.insert(db, PublishedReply(id=new_id(), turn_id=turn.id, conversation_id=conv.id, claim_id=claim.id, run_id=run["run_id"], fields=fields))
            turn.status = "PUBLISHED"
            record(db, conv.id, "回复已发布", {**fields, "任务编号": turn.id, "领取编号": claim.id, "运行编号": run["run_id"]})
            answer = {"published": True, "duplicate": False}
    return answer
