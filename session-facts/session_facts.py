"""客服系统是会话事实的权威。

发消息接口只做身份校验、参数校验和数据库提交，不等待工具读取。
发布只在本库的同一事务里裁决会话条件。它不调用工具，也不改预约记录。
投递成败不在受理事务里，没有投递回调可以回滚已提交事件。
"""

import json
import sqlite3
import uuid
from pathlib import Path

from sqlite_util import connect, immediate

ACCEPT_TIMEOUT_MS = 1500
LOOKUP_TIMEOUT_MS = 1500
LOOKUP_RETRY_LIMIT = 3
PUBLISH_TIMEOUT_MS = 1500
CLAIM_LEASE_MS = 20000
EXACT_BODY = "维保是否预约成功"
VISIBLE_REPLY_KEYS = frozenset(
    {"事件编号", "事件序号", "事件种类", "回复种类", "预约编号", "是否预约成功"}
)
RECEIPT_KEYS = frozenset({"消息编号", "会话编号", "会话版本", "已接收"})


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class SessionFacts:
    def __init__(self, path: Path, person, clock):
        self.path = Path(path)
        self.person = person
        self.clock = clock
        with connect(self.path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    owner_credential_id TEXT NOT NULL,
                    owner_kind TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    bot_allowed INTEGER NOT NULL CHECK (bot_allowed IN (0, 1))
                );
                CREATE TABLE IF NOT EXISTS messages (
                    message_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    client_request_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    body TEXT NOT NULL,
                    appointment_id TEXT,
                    sender_kind TEXT NOT NULL,
                    accepted_at INTEGER NOT NULL,
                    UNIQUE (session_id, client_request_id),
                    UNIQUE (session_id, version)
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    input_version INTEGER NOT NULL,
                    kind TEXT NOT NULL CHECK (kind IN ('read_query', 'human_attention')),
                    expected_appointment_id TEXT,
                    status TEXT NOT NULL CHECK (
                        status IN ('pending', 'claimed', 'published', 'invalidated', 'human')
                    ),
                    current_claim_id TEXT,
                    lease_until INTEGER,
                    invalidated_reason TEXT
                );
                CREATE TABLE IF NOT EXISTS claims (
                    claim_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    claimed_at INTEGER NOT NULL,
                    lease_until INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS published_replies (
                    reply_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL UNIQUE,
                    claim_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    input_version INTEGER NOT NULL,
                    fields_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS publish_decisions (
                    decision_id TEXT PRIMARY KEY,
                    claim_id TEXT NOT NULL UNIQUE,
                    task_id TEXT NOT NULL,
                    run_id TEXT,
                    input_version INTEGER,
                    current_version INTEGER,
                    outcome TEXT NOT NULL CHECK (outcome IN ('published', 'refused')),
                    refusal TEXT,
                    basis_rechecked INTEGER NOT NULL CHECK (basis_rechecked IN (0, 1))
                );
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    UNIQUE (session_id, seq)
                );
                CREATE TABLE IF NOT EXISTS takeovers (
                    session_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    PRIMARY KEY (session_id, request_id)
                );
                CREATE TABLE IF NOT EXISTS refusals (
                    refusal_id TEXT PRIMARY KEY,
                    credential_id TEXT,
                    session_id TEXT,
                    reason TEXT NOT NULL,
                    refused_at INTEGER NOT NULL
                );
                """
            )

    def accept_message(
        self,
        credential_id: str,
        session_id: str,
        client_request_id: str,
        body: str,
        appointment_id: str | None = None,
        elapsed_ms: int = 0,
        fail_before_commit: bool = False,
    ) -> dict:
        if elapsed_ms > ACCEPT_TIMEOUT_MS:
            return {"ok": False, "结果": "不明", "user_visible": None}
        cred = self.person.get(credential_id)
        if cred is None or cred["kind"] not in {"owner", "authorized_driver"}:
            self._refuse(credential_id, session_id, "身份无权")
            return {"ok": False, "reason": "身份无权", "user_visible": None}
        appointment_id = appointment_id or None
        try:
            with connect(self.path) as conn:
                with immediate(conn):
                    self._ensure_session(conn, session_id, credential_id, cred["kind"])
                    existing = conn.execute(
                        """
                        SELECT message_id, version FROM messages
                        WHERE session_id = ? AND client_request_id = ?
                        """,
                        (session_id, client_request_id),
                    ).fetchone()
                    if existing is not None:
                        receipt = self._receipt(existing["message_id"], session_id, existing["version"])
                        return {
                            "ok": True,
                            "duplicate": True,
                            "user_visible": receipt,
                            "internal": None,
                        }
                    version = self._bump(conn, session_id)
                    message_id = _id("msg")
                    task_id = _id("task")
                    accepted_at = self.clock.now()
                    read_query = (
                        cred["kind"] == "owner"
                        and body == EXACT_BODY
                        and appointment_id is not None
                    )
                    kind = "read_query" if read_query else "human_attention"
                    status = "pending" if read_query else "human"
                    conn.execute(
                        """
                        INSERT INTO messages (
                            message_id, session_id, client_request_id, version, body,
                            appointment_id, sender_kind, accepted_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            message_id,
                            session_id,
                            client_request_id,
                            version,
                            body,
                            appointment_id,
                            cred["kind"],
                            accepted_at,
                        ),
                    )
                    conn.execute(
                        """
                        INSERT INTO tasks (
                            task_id, session_id, message_id, input_version, kind,
                            expected_appointment_id, status
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            task_id,
                            session_id,
                            message_id,
                            version,
                            kind,
                            appointment_id if read_query else None,
                            status,
                        ),
                    )
                    self._event(
                        conn,
                        session_id,
                        "用户消息已受理",
                        {
                            "消息编号": message_id,
                            "会话编号": session_id,
                            "会话版本": version,
                            "发送者凭证种类": self.person.display_kind(cred["kind"]),
                            "用户原文": body,
                            "受理时间": str(accepted_at),
                        },
                    )
                    if fail_before_commit:
                        raise TimeoutError("受理提交超时")
                    receipt = self._receipt(message_id, session_id, version)
                    internal = {
                        "task_id": task_id,
                        "message_id": message_id,
                        "version": version,
                        "kind": kind,
                        "expected_appointment_id": appointment_id if read_query else None,
                        "sender_kind": cred["kind"],
                        "sender_credential_id": credential_id,
                        "body": body,
                    }
        except TimeoutError:
            return {"ok": False, "结果": "不明", "user_visible": None}
        return {"ok": True, "duplicate": False, "user_visible": receipt, "internal": internal}

    def lookup_receipt(
        self,
        credential_id: str,
        session_id: str,
        client_request_id: str,
        elapsed_ms: int = 0,
    ) -> dict:
        if elapsed_ms > LOOKUP_TIMEOUT_MS:
            return {"ok": False, "结果": "不明", "user_visible": None}
        cred = self.person.get(credential_id)
        if cred is None or cred["kind"] not in {"owner", "authorized_driver"}:
            return {"ok": False, "reason": "身份无权", "user_visible": None}
        with connect(self.path) as conn:
            session = conn.execute(
                "SELECT owner_credential_id FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if session is not None and session["owner_credential_id"] != credential_id:
                return {"ok": False, "reason": "身份无权", "user_visible": None}
            if session is None:
                return {"ok": False, "结果": "不明", "user_visible": None}
            row = conn.execute(
                """
                SELECT message_id, version FROM messages
                WHERE session_id = ? AND client_request_id = ?
                """,
                (session_id, client_request_id),
            ).fetchone()
        if row is None:
            return {"ok": False, "结果": "不明", "user_visible": None}
        return {
            "ok": True,
            "user_visible": self._receipt(row["message_id"], session_id, row["version"]),
        }

    def claim_task(self, task_id: str, claim_id: str, now_ms: int) -> dict:
        lease_until = now_ms + CLAIM_LEASE_MS
        with connect(self.path) as conn:
            with immediate(conn):
                updated = conn.execute(
                    """
                    UPDATE tasks
                    SET status = 'claimed', current_claim_id = ?, lease_until = ?
                    WHERE task_id = ?
                      AND status = 'pending'
                      AND kind = 'read_query'
                      AND current_claim_id IS NULL
                    """,
                    (claim_id, lease_until, task_id),
                )
                if updated.rowcount != 1:
                    return {"ok": False, "reason": "领取未成功"}
                conn.execute(
                    """
                    INSERT INTO claims (claim_id, task_id, claimed_at, lease_until)
                    VALUES (?, ?, ?, ?)
                    """,
                    (claim_id, task_id, now_ms, lease_until),
                )
                task = self._task(conn, task_id)
        return {"ok": True, "claim_id": claim_id, "task": task}

    def reclaim_task(self, task_id: str, new_claim_id: str, now_ms: int) -> dict:
        lease_until = now_ms + CLAIM_LEASE_MS
        with connect(self.path) as conn:
            with immediate(conn):
                updated = conn.execute(
                    """
                    UPDATE tasks
                    SET current_claim_id = ?, lease_until = ?, status = 'claimed'
                    WHERE task_id = ?
                      AND status = 'claimed'
                      AND kind = 'read_query'
                      AND lease_until <= ?
                      AND current_claim_id IS NOT NULL
                      AND current_claim_id != ?
                    """,
                    (new_claim_id, lease_until, task_id, now_ms, new_claim_id),
                )
                if updated.rowcount != 1:
                    return {"ok": False, "reason": "重新领取未成功"}
                conn.execute(
                    """
                    INSERT INTO claims (claim_id, task_id, claimed_at, lease_until)
                    VALUES (?, ?, ?, ?)
                    """,
                    (new_claim_id, task_id, now_ms, lease_until),
                )
                task = self._task(conn, task_id)
        return {"ok": True, "claim_id": new_claim_id, "task": task}

    def publish(self, claim_id: str, now_ms: int, load_run, elapsed_ms: int = 0) -> dict:
        if elapsed_ms > PUBLISH_TIMEOUT_MS:
            return {"ok": False, "结果": "不明", "user_visible": None}
        try:
            run = load_run(claim_id)
            load_failed = False
        except Exception:
            run = None
            load_failed = True
        with connect(self.path) as conn:
            with immediate(conn):
                prior = conn.execute(
                    "SELECT outcome, refusal FROM publish_decisions WHERE claim_id = ?",
                    (claim_id,),
                ).fetchone()
                if prior is not None:
                    return {
                        "ok": prior["outcome"] == "published",
                        "duplicate": True,
                        "reason": prior["refusal"],
                        "user_visible": None,
                    }
                claim = conn.execute(
                    "SELECT task_id FROM claims WHERE claim_id = ?",
                    (claim_id,),
                ).fetchone()
                if claim is None:
                    self._refuse_in(conn, None, None, "领取编号不匹配")
                    return {"ok": False, "reason": "领取编号不匹配", "user_visible": None}
                task = self._task(conn, claim["task_id"])
                session = conn.execute(
                    "SELECT * FROM sessions WHERE session_id = ?",
                    (task["session_id"],),
                ).fetchone()
                reply_exists = conn.execute(
                    "SELECT 1 AS n FROM published_replies WHERE task_id = ?",
                    (task["task_id"],),
                ).fetchone()
                refusal = self._first_refusal(
                    session, task, claim_id, now_ms, run, reply_exists is not None, load_failed
                )
                if refusal is None:
                    fields = {
                        "预约编号": run["output_fields"]["预约编号"],
                        "是否预约成功": run["output_fields"]["是否预约成功"],
                    }
                    reply_id = _id("reply")
                    conn.execute(
                        """
                        INSERT INTO published_replies (
                            reply_id, task_id, claim_id, run_id, session_id,
                            input_version, fields_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            reply_id,
                            task["task_id"],
                            claim_id,
                            run["run_id"],
                            task["session_id"],
                            task["input_version"],
                            _dump(fields),
                        ),
                    )
                    conn.execute(
                        """
                        INSERT INTO publish_decisions (
                            decision_id, claim_id, task_id, run_id, input_version,
                            current_version, outcome, refusal, basis_rechecked
                        ) VALUES (?, ?, ?, ?, ?, ?, 'published', NULL, 0)
                        """,
                        (
                            _id("decision"),
                            claim_id,
                            task["task_id"],
                            run["run_id"],
                            task["input_version"],
                            session["version"],
                        ),
                    )
                    conn.execute(
                        """
                        UPDATE tasks
                        SET status = 'published'
                        WHERE task_id = ? AND current_claim_id = ? AND status = 'claimed'
                        """,
                        (task["task_id"], claim_id),
                    )
                    self._event(
                        conn,
                        task["session_id"],
                        "回复已发布",
                        {
                            "回复种类": "预约状态查询",
                            "预约编号": fields["预约编号"],
                            "是否预约成功": fields["是否预约成功"],
                            "任务编号": task["task_id"],
                            "领取编号": claim_id,
                            "运行编号": run["run_id"],
                            "输入会话版本": task["input_version"],
                        },
                    )
                    return {"ok": True, "reason": None, "user_visible": None}
                conn.execute(
                    """
                    INSERT INTO publish_decisions (
                        decision_id, claim_id, task_id, run_id, input_version,
                        current_version, outcome, refusal, basis_rechecked
                    ) VALUES (?, ?, ?, ?, ?, ?, 'refused', ?, 0)
                    """,
                    (
                        _id("decision"),
                        claim_id,
                        task["task_id"],
                        None if run is None else run.get("run_id"),
                        task["input_version"],
                        session["version"],
                        refusal,
                    ),
                )
                conn.execute(
                    """
                    UPDATE tasks
                    SET status = 'invalidated', invalidated_reason = ?
                    WHERE task_id = ?
                      AND current_claim_id = ?
                      AND status = 'claimed'
                    """,
                    (refusal, task["task_id"], claim_id),
                )
                payload = {
                    "任务编号": task["task_id"],
                    "领取编号": claim_id,
                    "运行编号": None if run is None else run.get("run_id"),
                    "拒绝原因": refusal,
                    "输入会话版本": task["input_version"],
                    "当前会话版本": session["version"],
                }
                if run is not None and run.get("failure_reason") not in {None, "执行中"}:
                    payload["运行失败原因"] = run["failure_reason"]
                self._event(conn, task["session_id"], "运行未发布", payload)
        return {"ok": False, "reason": refusal, "user_visible": None}

    def takeover(self, credential_id: str, session_id: str, request_id: str) -> dict:
        cred = self.person.get(credential_id)
        if cred is None or cred["kind"] != "advisor":
            self._refuse(credential_id, session_id, "身份无权")
            return {"ok": False, "reason": "身份无权"}
        with connect(self.path) as conn:
            with immediate(conn):
                session = conn.execute(
                    "SELECT * FROM sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                if session is None:
                    self._refuse_in(conn, credential_id, session_id, "身份无权")
                    return {"ok": False, "reason": "身份无权"}
                inserted = conn.execute(
                    """
                    INSERT INTO takeovers (session_id, request_id)
                    VALUES (?, ?)
                    ON CONFLICT DO NOTHING
                    """,
                    (session_id, request_id),
                )
                if inserted.rowcount != 1:
                    return {"ok": True, "duplicate": True}
                updated = conn.execute(
                    """
                    UPDATE sessions
                    SET bot_allowed = 0
                    WHERE session_id = ? AND bot_allowed = 1
                    """,
                    (session_id,),
                )
                if updated.rowcount != 1:
                    return {"ok": True, "duplicate": True}
                conn.execute(
                    """
                    UPDATE tasks
                    SET status = 'invalidated', invalidated_reason = '已进入人工'
                    WHERE session_id = ?
                      AND kind = 'read_query'
                      AND status IN ('pending', 'claimed')
                    """,
                    (session_id,),
                )
                version = conn.execute(
                    "SELECT version FROM sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()["version"]
                self._event(
                    conn,
                    session_id,
                    "已进入人工",
                    {"会话编号": session_id, "会话版本": version, "接管时间": str(self.clock.now())},
                )
        return {"ok": True, "duplicate": False}

    def fetch_user(self, credential_id: str, session_id: str, after_seq: int = 0) -> dict:
        cred = self.person.get(credential_id)
        if cred is None or cred["kind"] not in {"owner", "authorized_driver"}:
            return {"ok": False, "reason": "身份无权", "items": []}
        with connect(self.path) as conn:
            session = conn.execute(
                "SELECT owner_credential_id FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if session is None or session["owner_credential_id"] != credential_id:
                return {"ok": False, "reason": "身份无权", "items": []}
            rows = conn.execute(
                """
                SELECT event_id, seq, kind, payload FROM events
                WHERE session_id = ? AND seq > ? AND kind = '回复已发布'
                ORDER BY seq
                """,
                (session_id, after_seq),
            ).fetchall()
        items = []
        seen = set()
        for row in rows:
            if row["event_id"] in seen:
                continue
            seen.add(row["event_id"])
            payload = json.loads(row["payload"])
            visible = {
                "事件编号": row["event_id"],
                "事件序号": row["seq"],
                "事件种类": "回复已发布",
                "回复种类": "预约状态查询",
                "预约编号": payload["预约编号"],
                "是否预约成功": payload["是否预约成功"],
            }
            if set(visible) != VISIBLE_REPLY_KEYS:
                raise RuntimeError("用户可见字段超出允许范围")
            items.append(visible)
        return {"ok": True, "items": items}

    def fetch_advisor(self, credential_id: str, session_id: str, after_seq: int = 0) -> dict:
        cred = self.person.get(credential_id)
        if cred is None or cred["kind"] != "advisor":
            self._refuse(credential_id, session_id, "身份无权")
            return {"ok": False, "reason": "身份无权", "items": []}
        with connect(self.path) as conn:
            rows = conn.execute(
                """
                SELECT event_id, seq, kind, payload FROM events
                WHERE session_id = ? AND seq > ?
                ORDER BY seq
                """,
                (session_id, after_seq),
            ).fetchall()
        items = []
        seen = set()
        for row in rows:
            if row["event_id"] in seen:
                continue
            seen.add(row["event_id"])
            payload = json.loads(row["payload"])
            items.append(self._advisor_item(row["event_id"], row["seq"], row["kind"], payload))
        return {"ok": True, "items": items}

    def counts(self) -> dict:
        with connect(self.path) as conn:
            def n(table: str) -> int:
                return conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]

            return {
                "messages": n("messages"),
                "tasks": n("tasks"),
                "claims": n("claims"),
                "replies": n("published_replies"),
                "events": n("events"),
                "decisions": n("publish_decisions"),
                "refusals": n("refusals"),
            }

    def task(self, task_id: str):
        with connect(self.path) as conn:
            return self._task(conn, task_id)

    def _ensure_session(self, conn, session_id: str, credential_id: str, kind: str) -> None:
        conn.execute(
            """
            INSERT INTO sessions (
                session_id, owner_credential_id, owner_kind, version, bot_allowed
            ) VALUES (?, ?, ?, 0, 1)
            ON CONFLICT(session_id) DO NOTHING
            """,
            (session_id, credential_id, kind),
        )
        owner = conn.execute(
            "SELECT owner_credential_id FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if owner["owner_credential_id"] != credential_id:
            raise PermissionError("身份无权")

    def _bump(self, conn, session_id: str) -> int:
        conn.execute(
            "UPDATE sessions SET version = version + 1 WHERE session_id = ?",
            (session_id,),
        )
        return conn.execute(
            "SELECT version FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()["version"]

    def _event(self, conn, session_id: str, kind: str, payload: dict) -> None:
        seq = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 AS seq FROM events WHERE session_id = ?",
            (session_id,),
        ).fetchone()["seq"]
        body = dict(payload)
        body["事件种类"] = kind
        conn.execute(
            """
            INSERT INTO events (event_id, session_id, seq, kind, payload)
            VALUES (?, ?, ?, ?, ?)
            """,
            (_id("ev"), session_id, seq, kind, _dump(body)),
        )

    def _task(self, conn, task_id: str):
        row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        return None if row is None else dict(row)

    def _receipt(self, message_id: str, session_id: str, version: int) -> dict:
        receipt = {
            "消息编号": message_id,
            "会话编号": session_id,
            "会话版本": version,
            "已接收": "是",
        }
        if set(receipt) != RECEIPT_KEYS:
            raise RuntimeError("受理回执字段超出允许范围")
        return receipt

    def _refuse(self, credential_id, session_id, reason: str) -> None:
        with connect(self.path) as conn:
            with immediate(conn):
                self._refuse_in(conn, credential_id, session_id, reason)

    def _refuse_in(self, conn, credential_id, session_id, reason: str) -> None:
        conn.execute(
            """
            INSERT INTO refusals (refusal_id, credential_id, session_id, reason, refused_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (_id("refusal"), credential_id, session_id, reason, self.clock.now()),
        )

    def _first_refusal(self, session, task, claim_id, now_ms, run, reply_exists, load_failed):
        if session["bot_allowed"] != 1 or task["invalidated_reason"] == "已进入人工":
            return "已进入人工"
        if task["input_version"] != session["version"]:
            return "输入版本已失效"
        if task["current_claim_id"] != claim_id:
            return "领取编号不匹配"
        if task["lease_until"] is None or task["lease_until"] <= now_ms:
            return "租约已过期"
        if task["status"] == "invalidated":
            return "已进入人工"
        if reply_exists or task["status"] == "published":
            return "任务已有可见结果"
        if load_failed or run is None or not run.get("output_approved") or run.get("state") != "done":
            return "运行未通过"
        fields = run.get("output_fields")
        if not isinstance(fields, dict) or set(fields) != {"预约编号", "是否预约成功"}:
            return "展示字段违规"
        if fields["预约编号"] != task["expected_appointment_id"]:
            return "展示字段违规"
        if fields["是否预约成功"] not in {"是", "否"}:
            return "展示字段违规"
        if run.get("proposed_text"):
            return "展示字段违规"
        return None

    def _advisor_item(self, event_id: str, seq: int, kind: str, payload: dict) -> dict:
        base = {"事件编号": event_id, "事件序号": seq, "事件种类": kind}
        if kind == "用户消息已受理":
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
        if kind == "回复已发布":
            base.update(
                {
                    "回复种类": "预约状态查询",
                    "预约编号": payload["预约编号"],
                    "是否预约成功": payload["是否预约成功"],
                    "任务编号": payload["任务编号"],
                    "领取编号": payload["领取编号"],
                    "运行编号": payload["运行编号"],
                }
            )
            return base
        if kind == "已进入人工":
            base.update(
                {
                    "会话编号": payload["会话编号"],
                    "会话版本": payload["会话版本"],
                    "接管时间": payload["接管时间"],
                }
            )
            return base
        if kind == "运行未发布":
            base.update(
                {
                    "任务编号": payload["任务编号"],
                    "领取编号": payload["领取编号"],
                    "运行编号": payload["运行编号"],
                    "拒绝原因": payload["拒绝原因"],
                    "输入会话版本": payload["输入会话版本"],
                    "当前会话版本": payload["当前会话版本"],
                }
            )
            if "运行失败原因" in payload:
                base["运行失败原因"] = payload["运行失败原因"]
            return base
        raise RuntimeError("未列明的事件种类")
