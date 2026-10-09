"""同一进程里的四个模块。HTTP 只做身份校验和一次事务提交。

受理接口不等待领取、运行和发布。密钥只用于查找凭证，不进入响应。
"""

import sys
from pathlib import Path

from fastapi import FastAPI, Header
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parent
for name in ("session-facts", "run-facts", "person-vehicle", "procedure-versions"):
    sys.path.insert(0, str(ROOT / name))
sys.path.insert(0, str(ROOT))

from clock import Clock
from schema import FLOW_KEY
from session_facts import (
    accept,
    claim,
    duplicate_receipt,
    expire_final,
    fetch_advisor,
    fetch_user,
    publish,
    publish_unknown,
    reclaim,
    session_id_for,
    takeover_session,
)
from run_facts import write_run

clock = Clock()
SessionFactory = None
app = FastAPI()


class MessageIn(BaseModel):
    client_request_id: str
    body: str


class SessionIn(BaseModel):
    session_id: str
    request_id: str | None = None


class ClaimIn(BaseModel):
    claim_id: str
    read_failed: bool = False
    elapsed_ms: int = 0


class TaskIn(BaseModel):
    task_id: str


def configure(factory, shared_clock: Clock) -> None:
    global SessionFactory, clock
    SessionFactory = factory
    clock = shared_clock


def _db() -> Session:
    if SessionFactory is None:
        raise RuntimeError("数据库会话尚未配置")
    return SessionFactory()


def _secret(authorization: str | None) -> str:
    if not authorization:
        return ""
    prefix = "Bearer "
    return authorization[len(prefix):] if authorization.startswith(prefix) else ""


@app.post("/messages")
def post_message(body: MessageIn, authorization: str | None = Header(default=None)):
    db = _db()
    try:
        result = accept(db, _secret(authorization), body.client_request_id, body.body, clock)
        db.commit()
        return result
    except IntegrityError:
        db.rollback()
        receipt = duplicate_receipt(db, _secret(authorization), body.client_request_id, body.body)
        if receipt is None:
            return {"ok": False, "reason": "并发受理冲突"}
        return {"ok": True, "duplicate": True, "user_visible": receipt}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@app.post("/sessions/{session_id}/claim")
def post_claim(session_id: str):
    db = _db()
    try:
        result = claim(db, session_id, "runner", clock)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@app.post("/claims/{claim_id}/run")
def post_run(claim_id: str, body: ClaimIn):
    db = _db()
    try:
        result = write_run(db, claim_id, read_failed=body.read_failed, elapsed_ms=body.elapsed_ms)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@app.post("/claims/{claim_id}/publish")
def post_publish(claim_id: str):
    db = _db()
    try:
        result = publish(db, claim_id, clock)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@app.post("/tasks/{task_id}/reclaim")
def post_reclaim(task_id: str):
    db = _db()
    try:
        result = reclaim(db, task_id, "runner", clock)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@app.post("/tasks/{task_id}/expire")
def post_expire(task_id: str):
    db = _db()
    try:
        result = expire_final(db, task_id, clock)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@app.get("/tasks/{task_id}/reply")
def get_reply(task_id: str):
    db = _db()
    try:
        return publish_unknown(db, task_id)
    finally:
        db.close()


@app.post("/takeover")
def post_takeover(body: SessionIn, authorization: str | None = Header(default=None)):
    db = _db()
    try:
        result = takeover_session(db, _secret(authorization), body.session_id, body.request_id or "", clock)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@app.get("/user-events")
def get_user_events(after_seq: int = 0, authorization: str | None = Header(default=None)):
    db = _db()
    try:
        return fetch_user(db, _secret(authorization), after_seq)
    finally:
        db.close()


@app.get("/advisor-events")
def get_advisor_events(session_id: str, after_seq: int = 0, authorization: str | None = Header(default=None)):
    db = _db()
    try:
        return fetch_advisor(db, _secret(authorization), session_id, after_seq)
    finally:
        db.close()


@app.get("/session")
def get_session(authorization: str | None = Header(default=None)):
    db = _db()
    try:
        return {"session_id": session_id_for(db, _secret(authorization)), "flow_key": FLOW_KEY}
    finally:
        db.close()
