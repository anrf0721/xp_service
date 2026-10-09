"""预约维保记录的进程内只读权威。

这不是预约维保查询接口，也不是维保预约创建入口。
本模块没有改状态的函数。模型不能写这些记录。
"""

import threading
from pathlib import Path

from sqlite_util import connect, immediate

READ_TOOL_NAME = "read_appointment_status"
READ_TIMEOUT_MS = 1500
READ_RETRY_PER_CLAIM = 0

BLOCKED_WRITE_TOOLS = frozenset(
    {
        "create_appointment",
        "reschedule_appointment",
        "cancel_appointment",
        "create_rescue",
        "update_delivery_contact",
        "update_plate",
        "submit_home_survey",
        "remote_unlock",
        "remote_ac",
        "summon_vehicle",
        "place_order",
    }
)

ALLOWED_RESULT_KEYS = frozenset({"预约编号", "是否预约成功"})


class AppointmentStatus:
    def __init__(self, path: Path, records: tuple[tuple[str, str, bool], ...]):
        self.path = Path(path)
        self._lock = threading.Lock()
        self.read_count = 0
        self.queries: list[str] = []
        with connect(self.path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS appointment_records (
                    appointment_id TEXT PRIMARY KEY,
                    owner_credential_id TEXT NOT NULL,
                    booked INTEGER NOT NULL CHECK (booked IN (0, 1))
                )
                """
            )
            with immediate(conn):
                for appointment_id, owner_credential_id, booked in records:
                    conn.execute(
                        """
                        INSERT INTO appointment_records (
                            appointment_id, owner_credential_id, booked
                        ) VALUES (?, ?, ?)
                        ON CONFLICT(appointment_id) DO NOTHING
                        """,
                        (appointment_id, owner_credential_id, 1 if booked else 0),
                    )

    def read(
        self,
        appointment_id: str,
        reader_credential_id: str,
        reader_kind: str,
        elapsed_ms: int,
    ) -> dict:
        if elapsed_ms > READ_TIMEOUT_MS:
            return {"ok": False, "reason": "查询超时", "attempted": False, "fields": None}
        if reader_kind != "owner":
            return {"ok": False, "reason": "身份无权", "attempted": False, "fields": None}
        with self._lock:
            self.read_count += 1
            self.queries.append(appointment_id)
        with connect(self.path) as conn:
            row = conn.execute(
                """
                SELECT appointment_id, owner_credential_id, booked
                FROM appointment_records
                WHERE appointment_id = ?
                """,
                (appointment_id,),
            ).fetchone()
        if row is None or row["owner_credential_id"] != reader_credential_id:
            return {"ok": False, "reason": "查询失败", "attempted": True, "fields": None}
        fields = {
            "预约编号": row["appointment_id"],
            "是否预约成功": "是" if row["booked"] == 1 else "否",
        }
        return {"ok": True, "reason": None, "attempted": True, "fields": fields}

    def snapshot(self) -> dict[str, int]:
        with connect(self.path) as conn:
            rows = conn.execute(
                "SELECT appointment_id, booked FROM appointment_records ORDER BY appointment_id"
            ).fetchall()
        return {row["appointment_id"]: row["booked"] for row in rows}
