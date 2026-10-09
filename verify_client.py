import os
import sys
import threading
import unittest
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
for name in ("session-facts", "run-facts", "person-vehicle", "procedure-versions"):
    sys.path.insert(0, str(ROOT / name))

import app as app_module
from clock import Clock
from db import Base
from person_vehicle import seed as seed_credentials
from procedure_versions import seed_current
from schema import ProcedureVersion

DATABASE_URL = os.environ["XP_PG_URL"]
OWNER = "owner-secret"
DRIVER = "driver-secret"
ADVISOR = "advisor-secret"
EXACT = "如何在 App 里预约保养"


def prepare_schema(engine) -> None:
    with engine.connect() as conn:
        existing = conn.execute(
            text("SELECT 1 FROM information_schema.schemata WHERE schema_name = 'owner_client'")
        ).scalar()
        public_before = conn.execute(
            text(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                ORDER BY table_name
                """
            )
        ).scalars().all()
        if existing:
            print("owner_client 已存在，只清空该 schema 的数据，不删除表，不碰 public")
        if public_before != ["conversation_turns", "conversations", "handoffs", "messages", "realtime_outbox"]:
            raise RuntimeError(f"public 表现有集合与预期不同，停止：{public_before}")
            conn.execute(text("CREATE SCHEMA owner_client"))
            conn.commit()
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                TRUNCATE
                    owner_client.task_messages,
                    owner_client.notice_events,
                    owner_client.published_replies,
                    owner_client.run_records,
                    owner_client.claims,
                    owner_client.follow_up_tasks,
                    owner_client.user_messages,
                    owner_client.takeovers,
                    owner_client.refusals,
                    owner_client.conversations,
                    owner_client.credentials,
                    owner_client.procedure_versions
                RESTART IDENTITY CASCADE
                """
            )
        )
    with engine.connect() as conn:
        public_after = conn.execute(
            text(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                ORDER BY table_name
                """
            )
        ).scalars().all()
        if public_after != ["conversation_turns", "conversations", "handoffs", "messages", "realtime_outbox"]:
            raise RuntimeError(f"public 表被改变，停止：{public_after}")


class ClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(DATABASE_URL, future=True)
        prepare_schema(cls.engine)
        Base.metadata.create_all(cls.engine)
        cls.factory = sessionmaker(bind=cls.engine, future=True, expire_on_commit=False)
        cls.clock = Clock()
        with cls.factory() as db:
            seed_credentials(
                db,
                (
                    ("cred-owner", "owner", OWNER),
                    ("cred-driver", "authorized_driver", DRIVER),
                    ("cred-advisor", "advisor", ADVISOR),
                    ("cred-fresh", "authorized_driver", "fresh-secret"),
                ),
            )
            seed_current(db)
            db.commit()
        app_module.configure(cls.factory, cls.clock)
        cls.client = TestClient(app_module.app)

    def setUp(self):
        self.clock.value = Clock().value

    def auth(self, secret: str) -> dict:
        return {"Authorization": f"Bearer {secret}"}

    def send(self, secret: str, request_id: str, body: str):
        return self.client.post(
            "/messages",
            json={"client_request_id": request_id, "body": body},
            headers=self.auth(secret),
        )

    def counts(self) -> dict:
        with self.engine.connect() as conn:
            return {
                key: conn.execute(text(f"SELECT COUNT(*) FROM owner_client.{key}")).scalar()
                for key in (
                    "user_messages",
                    "follow_up_tasks",
                    "notice_events",
                    "run_records",
                    "published_replies",
                    "claims",
                )
            }

    def session_id(self, secret: str) -> str:
        response = self.client.get("/session", headers=self.auth(secret))
        self.assertEqual(response.status_code, 200)
        return response.json()["session_id"]

    def test_concurrent_same_request_one_receipt(self):
        barrier = threading.Barrier(2)
        results = []

        def once():
            barrier.wait()
            results.append(self.send(OWNER, "same-1", EXACT).json())

        threads = [threading.Thread(target=once), threading.Thread(target=once)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        counts = self.counts()
        self.assertEqual(counts["user_messages"], 1)
        self.assertEqual(counts["follow_up_tasks"], 1)
        self.assertEqual(counts["notice_events"], 1)
        self.assertEqual(results[0]["user_visible"], results[1]["user_visible"])
        self.assertEqual(set(results[0]["user_visible"]), {"消息编号", "会话编号", "会话版本", "已接收"})

    def test_second_sentence_before_deadline_routes_human(self):
        before = self.counts()["run_records"]
        first = self.send(OWNER, "mix-1", EXACT)
        self.assertTrue(first.json()["ok"])
        second = self.send(OWNER, "mix-2", "另一句")
        self.assertTrue(second.json()["ok"])
        session_id = self.session_id(OWNER)
        self.clock.advance(8000)
        claimed = self.client.post(f"/sessions/{session_id}/claim")
        self.assertEqual(claimed.json()["routed"], "human")
        self.assertEqual(self.counts()["run_records"], before)
        self.assertEqual(self.counts()["published_replies"], 0)
        advisor = self.client.get(
            "/advisor-events",
            params={"session_id": session_id},
            headers=self.auth(ADVISOR),
        ).json()["items"]
        bodies = [item["用户原文"] for item in advisor if item["事件种类"] == "用户消息已受理"]
        self.assertEqual(bodies[-2:], [EXACT, "另一句"])

    def test_old_claim_after_new_message_is_not_published(self):
        accepted = self.send(DRIVER, "late-1", EXACT)
        self.assertTrue(accepted.json()["ok"])
        session_id = self.session_id(DRIVER)
        self.clock.advance(1500)
        claim = self.client.post(f"/sessions/{session_id}/claim").json()
        self.assertEqual(claim["routed"], "procedure")
        run = self.client.post(f"/claims/{claim['claim_id']}/run", json={"claim_id": claim["claim_id"]})
        self.assertTrue(run.json()["ok"])
        newer = self.send(DRIVER, "late-2", "生成期间的另一句")
        self.assertTrue(newer.json()["ok"])
        published = self.client.post(f"/claims/{claim['claim_id']}/publish")
        self.assertFalse(published.json()["ok"])
        self.assertEqual(published.json()["reason"], "输入版本已失效")
        user = self.client.get("/user-events", headers=self.auth(DRIVER)).json()["items"]
        self.assertEqual(user, [])
        advisor = self.client.get(
            "/advisor-events",
            params={"session_id": session_id},
            headers=self.auth(ADVISOR),
        ).json()["items"]
        refused = [item for item in advisor if item["事件种类"] == "运行未发布"]
        self.assertEqual(refused[0]["失败原因"], "输入版本已失效")
        self.assertNotIn("步骤", refused[0])
        self.assertEqual(self.counts()["published_replies"], 0)

    def test_takeover_keeps_history_and_blocks_new_claim(self):
        accepted = self.send(OWNER, "human-1", EXACT)
        self.assertTrue(accepted.json()["ok"])
        session_id = accepted.json()["user_visible"]["会话编号"]
        self.clock.advance(1500)
        claim = self.client.post(f"/sessions/{session_id}/claim").json()
        self.client.post(f"/claims/{claim['claim_id']}/run", json={"claim_id": claim["claim_id"]})
        published = self.client.post(f"/claims/{claim['claim_id']}/publish")
        self.assertTrue(published.json()["ok"])
        owner_takeover = self.client.post(
            "/takeover",
            json={"session_id": session_id, "request_id": "owner-take"},
            headers=self.auth(OWNER),
        )
        self.assertEqual(owner_takeover.json()["reason"], "身份无权")
        takeover = self.client.post(
            "/takeover",
            json={"session_id": session_id, "request_id": "take-1"},
            headers=self.auth(ADVISOR),
        )
        self.assertTrue(takeover.json()["ok"])
        self.assertFalse(takeover.json()["duplicate"])
        again = self.send(OWNER, "human-2", EXACT)
        self.assertTrue(again.json()["ok"])
        with self.engine.connect() as conn:
            allowed = conn.execute(
                text("SELECT bot_allowed FROM owner_client.conversations WHERE session_id = :session_id"),
                {"session_id": session_id},
            ).scalar()
            attached = conn.execute(
                text(
                    """
                    SELECT COUNT(*) FROM owner_client.task_messages tm
                    JOIN owner_client.user_messages m ON m.message_id = tm.message_id
                    WHERE m.client_request_id = 'human-2'
                    """
                )
            ).scalar()
        self.assertFalse(allowed)
        self.assertEqual(attached, 0)
        self.clock.advance(8000)
        blocked = self.client.post(f"/sessions/{session_id}/claim")
        self.assertNotEqual(blocked.json().get("routed"), "procedure")
        with self.engine.connect() as conn:
            claimable = conn.execute(
                text(
                    """
                    SELECT COUNT(*) FROM owner_client.follow_up_tasks
                    WHERE session_id = :session_id AND kind = 'collecting' AND status = 'open'
                    """
                ),
                {"session_id": session_id},
            ).scalar()
        self.assertEqual(claimable, 0)
        user = self.client.get("/user-events", headers=self.auth(OWNER)).json()["items"]
        self.assertEqual([item["事件种类"] for item in user], ["回复已发布", "已进入人工"])
        advisor = self.client.get(
            "/advisor-events",
            params={"session_id": session_id},
            headers=self.auth(ADVISOR),
        ).json()["items"]
        self.assertEqual(advisor[-1]["事件种类"], "用户消息已受理")
        self.assertEqual(advisor[-1]["用户原文"], EXACT)
        self.assertGreater(advisor[-1]["事件序号"], next(item["事件序号"] for item in advisor if item["事件种类"] == "已进入人工"))
        self.assertEqual(self.counts()["published_replies"], 1)

    def test_wrong_identity_and_withdrawn_flow_publish_nothing(self):
        before = self.counts()["user_messages"]
        wrong = self.send(ADVISOR, "bad-1", EXACT)
        self.assertEqual(wrong.json()["reason"], "身份无权")
        self.assertNotIn("user_visible", wrong.json())
        self.assertEqual(self.counts()["user_messages"], before)
        mismatch = self.send(DRIVER, "bad-2", EXACT)
        self.assertTrue(mismatch.json()["ok"])
        same_id = self.send(DRIVER, "bad-2", "如何在 App 里预约保养 ")
        self.assertEqual(same_id.json()["reason"], "请求编号原文不一致")
        self.assertNotIn("user_visible", same_id.json())
        changed = self.send(DRIVER, "bad-3", "如何在 App 里预约保养 ")
        self.assertTrue(changed.json()["ok"])
        self.assertNotEqual(mismatch.json()["user_visible"]["消息编号"], changed.json()["user_visible"]["消息编号"])
        with self.factory() as db:
            row = db.get(ProcedureVersion, "flow-app-service-placeholder")
            row.current_published = False
            row.withdrawn = True
            db.commit()
        fresh_id = f"fresh-{uuid.uuid4().hex}"
        fresh = self.send("fresh-secret", fresh_id, EXACT)
        session_id = fresh.json()["user_visible"]["会话编号"]
        existing_user = self.client.get("/user-events", headers=self.auth("fresh-secret")).json()["items"]
        before_seq = existing_user[-1]["事件序号"] if existing_user else 0
        self.clock.advance(1500)
        claim = self.client.post(f"/sessions/{session_id}/claim").json()
        self.assertIn("claim_id", claim, claim)
        self.client.post(f"/claims/{claim['claim_id']}/run", json={"claim_id": claim["claim_id"]})
        published = self.client.post(f"/claims/{claim['claim_id']}/publish")
        self.assertFalse(published.json()["ok"])
        self.assertEqual(published.json()["reason"], "流程已下架")
        user = self.client.get("/user-events", params={"after_seq": before_seq}, headers=self.auth("fresh-secret")).json()["items"]
        self.assertEqual(user, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
