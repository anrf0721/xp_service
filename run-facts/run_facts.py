"""模型执行组件是运行记录的权威。

它先占用领取编号，再判定工具调用是否准确。只有准确的只读调用才会执行。
它保存本次输入、工具提议、依据副本、输出和失败原因。
它不写已发布回复，不改预约记录。同一领取编号重试 0 次。
"""

import json
import sqlite3
from pathlib import Path

from sqlite_util import connect, immediate

EXECUTE_TIMEOUT_MS = 8000
EXECUTE_RETRY_PER_CLAIM = 0
ALLOWED_OUTPUT_KEYS = frozenset({"预约编号", "是否预约成功"})
ALLOWED_BOOKED = frozenset({"是", "否"})


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class RunStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        with connect(self.path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    claim_id TEXT NOT NULL UNIQUE,
                    task_id TEXT NOT NULL,
                    input_version INTEGER NOT NULL,
                    input_body TEXT NOT NULL,
                    proposed_tool_name TEXT,
                    proposed_arguments TEXT NOT NULL,
                    proposed_fields TEXT NOT NULL,
                    proposed_text TEXT,
                    call_accurate INTEGER NOT NULL,
                    blocked_write INTEGER NOT NULL,
                    executed INTEGER NOT NULL,
                    evidence TEXT NOT NULL,
                    output_approved INTEGER NOT NULL,
                    output_fields TEXT NOT NULL,
                    failure_reason TEXT,
                    state TEXT NOT NULL CHECK (state IN ('running', 'done'))
                )
                """
            )

    def get_by_claim(self, claim_id: str):
        with connect(self.path) as conn:
            row = conn.execute(
                "SELECT * FROM runs WHERE claim_id = ?",
                (claim_id,),
            ).fetchone()
        return None if row is None else dict(row)

    def count(self) -> int:
        with connect(self.path) as conn:
            return conn.execute("SELECT COUNT(*) AS n FROM runs").fetchone()["n"]


def judge_call(proposal, expected_appointment_id: str, read_tool_name: str, blocked_write_tools):
    calls = tuple(getattr(proposal, "calls", ()) or ())
    blocked = any(getattr(call, "name", None) in blocked_write_tools for call in calls)
    if len(calls) != 1 or not expected_appointment_id:
        return False, blocked, None, {}
    call = calls[0]
    name = getattr(call, "name", None)
    arguments = getattr(call, "arguments", None)
    if not isinstance(arguments, dict):
        return False, blocked or name in blocked_write_tools, name, {}
    if name != read_tool_name or set(arguments) != {"appointment_id"}:
        return False, blocked, name, arguments
    if arguments.get("appointment_id") != expected_appointment_id:
        return False, blocked, name, arguments
    if not isinstance(arguments["appointment_id"], str) or not arguments["appointment_id"]:
        return False, blocked, name, arguments
    return True, False, name, arguments


def execute_run(
    store: RunStore,
    *,
    run_id: str,
    claim_id: str,
    task_id: str,
    input_version: int,
    input_body: str,
    expected_appointment_id: str,
    reader_credential_id: str,
    reader_kind: str,
    proposal,
    read_tool,
    read_tool_name: str,
    blocked_write_tools,
    elapsed_ms: int,
    tool_elapsed_ms: int,
) -> dict:
    accurate, blocked, proposed_name, proposed_arguments = judge_call(
        proposal,
        expected_appointment_id,
        read_tool_name,
        blocked_write_tools,
    )
    proposed_fields = getattr(proposal, "fields", None)
    proposed_text = getattr(proposal, "text", None)
    try:
        with connect(store.path) as conn:
            with immediate(conn):
                conn.execute(
                    """
                    INSERT INTO runs (
                        run_id, claim_id, task_id, input_version, input_body,
                        proposed_tool_name, proposed_arguments, proposed_fields,
                        proposed_text, call_accurate, blocked_write, executed,
                        evidence, output_approved, output_fields, failure_reason, state
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'null', 0, 'null', '执行中', 'running')
                    """,
                    (
                        run_id,
                        claim_id,
                        task_id,
                        input_version,
                        input_body,
                        proposed_name,
                        _dump(proposed_arguments),
                        _dump(proposed_fields),
                        proposed_text,
                        1 if accurate else 0,
                        1 if blocked else 0,
                    ),
                )
    except sqlite3.IntegrityError:
        existing = store.get_by_claim(claim_id)
        return _public(existing, retry_rejected=True)

    failure = None
    executed = 0
    evidence = None
    approved = 0
    output = None
    if elapsed_ms > EXECUTE_TIMEOUT_MS:
        failure = "执行超时"
    elif not accurate:
        failure = "工具调用不准确"
    elif reader_kind != "owner":
        failure = "身份无权"
    else:
        result = read_tool(
            expected_appointment_id,
            reader_credential_id,
            reader_kind,
            tool_elapsed_ms,
        )
        executed = 1 if result["attempted"] else 0
        if not result["ok"]:
            failure = result["reason"]
        else:
            evidence = result["fields"]
            if not _fields_ok(evidence, expected_appointment_id):
                failure = "展示字段违规"
                evidence = None
            elif proposed_text not in (None, ""):
                failure = "展示字段违规"
            elif proposed_fields is not None and proposed_fields != evidence:
                failure = "展示字段违规"
            else:
                approved = 1
                output = {
                    "预约编号": evidence["预约编号"],
                    "是否预约成功": evidence["是否预约成功"],
                }
                failure = None

    with connect(store.path) as conn:
        with immediate(conn):
            updated = conn.execute(
                """
                UPDATE runs
                SET executed = ?, evidence = ?, output_approved = ?,
                    output_fields = ?, failure_reason = ?, state = 'done'
                WHERE claim_id = ? AND state = 'running'
                """,
                (
                    executed,
                    _dump(evidence),
                    approved,
                    _dump(output),
                    failure,
                    claim_id,
                ),
            )
            if updated.rowcount != 1:
                raise RuntimeError("运行记录未能从执行中完成")
    return _public(store.get_by_claim(claim_id), retry_rejected=False)


def _fields_ok(fields, expected_appointment_id: str) -> bool:
    if not isinstance(fields, dict) or set(fields) != ALLOWED_OUTPUT_KEYS:
        return False
    if fields["预约编号"] != expected_appointment_id:
        return False
    return fields["是否预约成功"] in ALLOWED_BOOKED


def load_public_run(store: RunStore, claim_id: str):
    row = store.get_by_claim(claim_id)
    if row is None or row["state"] != "done":
        return None
    return _public(row, retry_rejected=False)


def _public(row: dict, retry_rejected: bool) -> dict:
    if row is None:
        return {
            "run_id": None,
            "claim_id": None,
            "task_id": None,
            "call_accurate": False,
            "blocked_write": False,
            "executed": False,
            "output_approved": False,
            "evidence": None,
            "output_fields": None,
            "failure_reason": "同一领取不可重试",
            "proposed_tool_name": None,
            "proposed_text": None,
            "state": None,
            "retry_rejected": True,
        }
    return {
        "run_id": row["run_id"],
        "claim_id": row["claim_id"],
        "task_id": row["task_id"],
        "call_accurate": bool(row["call_accurate"]),
        "blocked_write": bool(row["blocked_write"]),
        "executed": bool(row["executed"]),
        "output_approved": bool(row["output_approved"]),
        "evidence": json.loads(row["evidence"]),
        "output_fields": json.loads(row["output_fields"]),
        "failure_reason": row["failure_reason"],
        "proposed_tool_name": row["proposed_tool_name"],
        "proposed_text": row["proposed_text"],
        "state": row["state"],
        "retry_rejected": retry_rejected,
    }
