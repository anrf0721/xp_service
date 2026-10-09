"""运行记录的权威。只读流程版本，按领取编号写运行记录。

不写已发布回复，不改流程说明，不生成步骤正文。
同一领取编号重试 0 次。
"""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from procedure_versions import read_current
from schema import FLOW_KEY, Claim, RunRecord


def write_run(db: Session, claim_id: str, *, read_failed: bool = False, elapsed_ms: int = 0) -> dict:
    claim = db.get(Claim, claim_id)
    if claim is None:
        return {"ok": False, "reason": "领取编号不匹配"}
    existing = db.scalar(select(RunRecord).where(RunRecord.claim_id == claim_id))
    if existing is not None:
        return {"ok": True, "duplicate": True, "run_id": existing.run_id}
    if elapsed_ms > 8000:
        row = RunRecord(
            run_id=f"run-{claim_id}",
            claim_id=claim_id,
            task_id=claim.task_id,
            input_version=claim.input_version,
            failure_reason="执行超时",
            state="done",
        )
        db.add(row)
        db.flush()
        return {"ok": True, "duplicate": False, "run_id": row.run_id, "failure_reason": "执行超时"}
    cited = None
    failure = None
    if read_failed:
        failure = "流程读取失败"
    else:
        cited = read_current(db, FLOW_KEY)
        if cited is None:
            failure = "流程已下架"
    row = RunRecord(
        run_id=f"run-{claim_id}",
        claim_id=claim_id,
        task_id=claim.task_id,
        input_version=claim.input_version,
        cited_version_id=None if cited is None else cited.version_id,
        title=None if cited is None else cited.title,
        steps=None if cited is None else cited.steps,
        boundary=None if cited is None else cited.boundary,
        version_label=None if cited is None else cited.version_label,
        failure_reason=failure,
        state="done",
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        winner = db.scalar(select(RunRecord).where(RunRecord.claim_id == claim_id))
        return {"ok": True, "duplicate": True, "run_id": None if winner is None else winner.run_id}
    return {"ok": True, "duplicate": False, "run_id": row.run_id, "failure_reason": failure}


def load_run(db: Session, claim_id: str) -> RunRecord | None:
    return db.scalar(select(RunRecord).where(RunRecord.claim_id == claim_id))
