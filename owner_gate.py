"""编排三个权威，不成为第四个事实来源。

成功路径只有一次只读查询。外部模型调用接口未验证，本模块不调用它。
proposal 是测试或预先存在的运行输入，不是发布权。
"""

import uuid
from dataclasses import dataclass

from appointment_status import BLOCKED_WRITE_TOOLS, READ_TOOL_NAME
from run_facts import execute_run, load_public_run
from session_facts import EXACT_BODY


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict


@dataclass(frozen=True)
class Proposal:
    calls: tuple
    fields: dict | None = None
    text: str | None = None


class Clock:
    def __init__(self, start: int = 1_000):
        self.value = start

    def now(self) -> int:
        return self.value


def accurate_proposal(appointment_id: str, booked: str) -> Proposal:
    return Proposal(
        calls=(ToolCall(READ_TOOL_NAME, {"appointment_id": appointment_id}),),
        fields={"预约编号": appointment_id, "是否预约成功": booked},
    )


class OwnerGate:
    def __init__(self, sessions, runs, appointments, clock: Clock):
        self.sessions = sessions
        self.runs = runs
        self.appointments = appointments
        self.clock = clock

    def accept(self, credential_id: str, session_id: str, client_request_id: str, body: str, appointment_id=None):
        return self.sessions.accept_message(
            credential_id,
            session_id,
            client_request_id,
            body,
            appointment_id,
        )

    def run_claimed(self, claim, proposal, elapsed_ms: int = 0, tool_elapsed_ms: int = 0) -> dict:
        if not claim["ok"]:
            return {"ok": False, "reason": claim["reason"]}
        task = claim["task"]
        return execute_run(
            self.runs,
            run_id=f"run-{uuid.uuid4().hex}",
            claim_id=claim["claim_id"],
            task_id=task["task_id"],
            input_version=task["input_version"],
            input_body=EXACT_BODY,
            expected_appointment_id=task["expected_appointment_id"],
            reader_credential_id=self._owner(task["session_id"]),
            reader_kind=self._kind(task["session_id"]),
            proposal=proposal,
            read_tool=self.appointments.read,
            read_tool_name=READ_TOOL_NAME,
            blocked_write_tools=BLOCKED_WRITE_TOOLS,
            elapsed_ms=elapsed_ms,
            tool_elapsed_ms=tool_elapsed_ms,
        )

    def publish(self, claim_id: str, elapsed_ms: int = 0) -> dict:
        return self.sessions.publish(
            claim_id,
            self.clock.now(),
            lambda current_claim_id: load_public_run(self.runs, current_claim_id),
            elapsed_ms,
        )

    def _owner(self, session_id: str) -> str:
        from sqlite_util import connect

        with connect(self.sessions.path) as conn:
            return conn.execute(
                "SELECT owner_credential_id FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()["owner_credential_id"]

    def _kind(self, session_id: str) -> str:
        from sqlite_util import connect

        with connect(self.sessions.path) as conn:
            return conn.execute(
                "SELECT owner_kind FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()["owner_kind"]
