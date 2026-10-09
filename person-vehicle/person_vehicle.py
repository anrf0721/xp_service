"""账号与人车关系里，本步只保存预先存在的凭证种类。

没有 VIN 绑定表，没有在线查询接口，没有凭证签发。
车主、授权用车人、服务顾问、管理员的权限不自动继承。
车主侧凭证和内部服务凭证不能互相替代。
"""

from pathlib import Path

from sqlite_util import connect, immediate

KIND_DISPLAY = {
    "owner": "车主",
    "authorized_driver": "授权用车人",
    "advisor": "服务顾问",
    "admin": "管理员",
}
CUSTOMER_KINDS = frozenset({"owner", "authorized_driver"})
INTERNAL_KINDS = frozenset({"advisor", "admin"})


class PersonVehicle:
    def __init__(self, path: Path):
        self.path = Path(path)
        with connect(self.path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS credentials (
                    credential_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL CHECK (
                        kind IN ('owner', 'authorized_driver', 'advisor', 'admin')
                    )
                )
                """
            )

    def install(self, credential_id: str, kind: str) -> None:
        if kind not in KIND_DISPLAY:
            raise ValueError("未知凭证种类")
        with connect(self.path) as conn:
            with immediate(conn):
                conn.execute(
                    """
                    INSERT INTO credentials (credential_id, kind)
                    VALUES (?, ?)
                    ON CONFLICT(credential_id) DO NOTHING
                    """,
                    (credential_id, kind),
                )

    def get(self, credential_id: str):
        with connect(self.path) as conn:
            row = conn.execute(
                "SELECT credential_id, kind FROM credentials WHERE credential_id = ?",
                (credential_id,),
            ).fetchone()
        if row is None:
            return None
        return {"credential_id": row["credential_id"], "kind": row["kind"]}

    def display_kind(self, kind: str) -> str:
        return KIND_DISPLAY[kind]
