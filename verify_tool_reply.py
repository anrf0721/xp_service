import importlib.util
import shutil
import sys
import tempfile
import threading
import unittest
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "session-facts"))
sys.path.insert(0, str(ROOT / "run-facts"))
sys.path.insert(0, str(ROOT / "person-vehicle"))
sys.path.insert(0, str(ROOT / "appointment-status"))

from appointment_status import AppointmentStatus, READ_TOOL_NAME
from owner_gate import Clock, OwnerGate, Proposal, ToolCall, accurate_proposal
from person_vehicle import PersonVehicle
from run_facts import RunStore
from session_facts import SessionFacts


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Fixture:
    def __init__(self, records):
        self.root = Path(tempfile.mkdtemp(prefix="xp-owner-min-"))
        self.person = PersonVehicle(self.root / "person-vehicle" / "credentials.sqlite")
        self.person.install("cred-owner", "owner")
        self.person.install("cred-driver", "authorized_driver")
        self.person.install("cred-advisor", "advisor")
        self.person.install("cred-admin", "admin")
        self.clock = Clock()
        self.sessions = SessionFacts(self.root / "session-facts" / "sessions.sqlite", self.person, self.clock)
        self.runs = RunStore(self.root / "run-facts" / "runs.sqlite")
        self.appointments = AppointmentStatus(
            self.root / "appointment-status" / "records.sqlite",
            records,
        )
        self.gate = OwnerGate(self.sessions, self.runs, self.appointments, self.clock)

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)


class ToolReplyTests(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture((("apt-1", "cred-owner", True),))

    def tearDown(self):
        self.fx.close()

    def accept(self, request_id="req-1", body="维保是否预约成功", appointment_id="apt-1", credential="cred-owner"):
        return self.fx.gate.accept(credential, "sess-1", request_id, body, appointment_id)

    def claim_and_run(self, accepted, proposal=None, elapsed_ms=0, tool_elapsed_ms=0):
        task_id = accepted["internal"]["task_id"]
        claim = self.fx.sessions.claim_task(task_id, f"claim-{uuid.uuid4().hex}", self.fx.clock.now())
        proposal = proposal or accurate_proposal("apt-1", "是")
        run = self.fx.gate.run_claimed(claim, proposal, elapsed_ms, tool_elapsed_ms)
        return claim, run

    def test_accurate_call_publishes_only_allowed_fields(self):
        accepted = self.accept()
        claim, run = self.claim_and_run(accepted)
        published = self.fx.gate.publish(claim["claim_id"])
        user = self.fx.sessions.fetch_user("cred-owner", "sess-1")
        advisor = self.fx.sessions.fetch_advisor("cred-advisor", "sess-1")

        self.assertTrue(run["call_accurate"])
        self.assertTrue(run["executed"])
        self.assertTrue(published["ok"])
        self.assertEqual(self.fx.appointments.read_count, 1)
        self.assertEqual(self.fx.appointments.queries, ["apt-1"])
        self.assertEqual(
            user["items"],
            [
                {
                    "事件编号": user["items"][0]["事件编号"],
                    "事件序号": 2,
                    "事件种类": "回复已发布",
                    "回复种类": "预约状态查询",
                    "预约编号": "apt-1",
                    "是否预约成功": "是",
                }
            ],
        )
        self.assertNotIn("proposed_text", user["items"][0])
        published_events = [item for item in advisor["items"] if item["事件种类"] == "回复已发布"]
        self.assertEqual(published_events[0]["是否预约成功"], "是")
        self.assertNotIn("依据说明", published_events[0])
        self.assertEqual(self.fx.appointments.snapshot(), {"apt-1": 1})

    def test_duplicate_request_leaves_one_message(self):
        first = self.accept()
        second = self.accept()
        self.assertTrue(second["duplicate"])
        self.assertEqual(first["user_visible"], second["user_visible"])
        self.assertEqual(self.fx.sessions.counts()["messages"], 1)
        self.assertEqual(self.fx.sessions.counts()["tasks"], 1)
        self.assertEqual(self.fx.sessions.counts()["events"], 1)
        self.assertEqual(self.fx.appointments.read_count, 0)

    def test_concurrent_same_request_one_insert(self):
        barrier = threading.Barrier(2)
        results = []

        def send():
            barrier.wait()
            results.append(self.accept())

        threads = [threading.Thread(target=send), threading.Thread(target=send)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(self.fx.sessions.counts()["messages"], 1)
        self.assertEqual(self.fx.sessions.counts()["events"], 1)
        receipts = [item["user_visible"] for item in results]
        self.assertEqual(receipts[0], receipts[1])

    def test_inaccurate_tool_does_not_read_or_publish(self):
        accepted = self.accept()
        proposal = Proposal(
            calls=(ToolCall("create_appointment", {"appointment_id": "apt-1"}),),
            fields={"预约编号": "apt-1", "是否预约成功": "是"},
            text="我已经帮你改好了",
        )
        claim, run = self.claim_and_run(accepted, proposal)
        published = self.fx.gate.publish(claim["claim_id"])
        user = self.fx.sessions.fetch_user("cred-owner", "sess-1")
        advisor = self.fx.sessions.fetch_advisor("cred-advisor", "sess-1")

        self.assertFalse(run["call_accurate"])
        self.assertTrue(run["blocked_write"])
        self.assertFalse(run["executed"])
        self.assertEqual(run["failure_reason"], "工具调用不准确")
        self.assertFalse(published["ok"])
        self.assertEqual(user["items"], [])
        self.assertEqual(self.fx.appointments.read_count, 0)
        self.assertEqual(self.fx.appointments.snapshot(), {"apt-1": 1})
        refused = [item for item in advisor["items"] if item["事件种类"] == "运行未发布"]
        self.assertEqual(refused[0]["拒绝原因"], "运行未通过")
        self.assertEqual(refused[0]["运行失败原因"], "工具调用不准确")
        self.assertNotIn("我已经帮你改好了", str(refused[0]))

    def test_wrong_appointment_argument_is_inaccurate(self):
        accepted = self.accept()
        proposal = Proposal(
            calls=(ToolCall(READ_TOOL_NAME, {"appointment_id": "apt-2"}),),
            fields={"预约编号": "apt-2", "是否预约成功": "是"},
        )
        claim, run = self.claim_and_run(accepted, proposal)
        self.fx.gate.publish(claim["claim_id"])
        self.assertFalse(run["call_accurate"])
        self.assertEqual(self.fx.appointments.queries, [])
        self.assertEqual(self.fx.sessions.fetch_user("cred-owner", "sess-1")["items"], [])

    def test_omitted_model_fields_still_publish_tool_result(self):
        accepted = self.accept()
        proposal = Proposal(calls=(ToolCall(READ_TOOL_NAME, {"appointment_id": "apt-1"}),))
        claim, run = self.claim_and_run(accepted, proposal)
        published = self.fx.gate.publish(claim["claim_id"])
        user = self.fx.sessions.fetch_user("cred-owner", "sess-1")
        self.assertTrue(run["call_accurate"])
        self.assertTrue(published["ok"])
        self.assertEqual(user["items"][0]["是否预约成功"], "是")
        self.assertEqual(user["items"][0]["预约编号"], "apt-1")

    def test_model_fields_cannot_replace_query_result(self):
        accepted = self.accept()
        proposal = accurate_proposal("apt-1", "否")
        claim, run = self.claim_and_run(accepted, proposal)
        self.fx.gate.publish(claim["claim_id"])
        user = self.fx.sessions.fetch_user("cred-owner", "sess-1")
        self.assertTrue(run["call_accurate"])
        self.assertEqual(run["evidence"]["是否预约成功"], "是")
        self.assertFalse(run["output_approved"])
        self.assertEqual(run["failure_reason"], "展示字段违规")
        self.assertEqual(user["items"], [])

    def test_authorized_driver_cannot_query_owner_appointment(self):
        accepted = self.accept(credential="cred-driver")
        self.assertEqual(accepted["internal"]["kind"], "human_attention")
        claim = self.fx.sessions.claim_task("missing", "claim-x", self.fx.clock.now())
        self.assertFalse(claim["ok"])
        self.assertEqual(self.fx.appointments.read_count, 0)
        user = self.fx.sessions.fetch_user("cred-driver", "sess-1")
        advisor = self.fx.sessions.fetch_advisor("cred-advisor", "sess-1")
        self.assertEqual(user["items"], [])
        self.assertEqual(advisor["items"][0]["发送者凭证种类"], "授权用车人")
        self.assertEqual(advisor["items"][0]["用户原文"], "维保是否预约成功")

    def test_query_failure_publishes_nothing(self):
        accepted = self.accept(appointment_id="missing")
        claim, run = self.claim_and_run(accepted, accurate_proposal("missing", "是"))
        published = self.fx.gate.publish(claim["claim_id"])
        self.assertEqual(run["failure_reason"], "查询失败")
        self.assertFalse(published["ok"])
        self.assertEqual(self.fx.sessions.fetch_user("cred-owner", "sess-1")["items"], [])
        advisor = self.fx.sessions.fetch_advisor("cred-advisor", "sess-1")
        refused = [item for item in advisor["items"] if item["事件种类"] == "运行未发布"][0]
        self.assertEqual(refused["运行失败原因"], "查询失败")
        self.assertNotIn("是否预约成功", refused)

    def test_old_result_after_new_message_is_not_visible(self):
        accepted = self.accept()
        claim = self.fx.sessions.claim_task(
            accepted["internal"]["task_id"], "claim-old", self.fx.clock.now()
        )
        self.fx.clock.value += 10
        newer = self.accept("req-2", "我补充一下", None)
        run = self.fx.gate.run_claimed(claim, accurate_proposal("apt-1", "是"))
        published = self.fx.gate.publish(claim["claim_id"])
        user = self.fx.sessions.fetch_user("cred-owner", "sess-1")
        advisor = self.fx.sessions.fetch_advisor("cred-advisor", "sess-1")

        self.assertTrue(run["output_approved"])
        self.assertFalse(published["ok"])
        self.assertEqual(published["reason"], "输入版本已失效")
        self.assertEqual(user["items"], [])
        self.assertEqual([item["事件种类"] for item in advisor["items"]], ["用户消息已受理", "用户消息已受理", "运行未发布"])
        self.assertEqual(advisor["items"][1]["用户原文"], "我补充一下")
        self.assertEqual(advisor["items"][2]["拒绝原因"], "输入版本已失效")
        self.assertEqual(self.fx.sessions.counts()["replies"], 0)
        self.assertIsNotNone(newer["user_visible"])

    def test_after_takeover_new_message_is_an_event(self):
        accepted = self.accept()
        claim = self.fx.sessions.claim_task(
            accepted["internal"]["task_id"], "claim-human", self.fx.clock.now()
        )
        takeover = self.fx.sessions.takeover("cred-advisor", "sess-1", "take-1")
        newer = self.accept("req-human", "人工后的补充", None)
        run = self.fx.gate.run_claimed(claim, accurate_proposal("apt-1", "是"))
        published = self.fx.gate.publish(claim["claim_id"])
        advisor = self.fx.sessions.fetch_advisor("cred-advisor", "sess-1")

        self.assertTrue(takeover["ok"])
        self.assertTrue(run["output_approved"])
        self.assertEqual(published["reason"], "已进入人工")
        self.assertEqual(self.fx.sessions.fetch_user("cred-owner", "sess-1")["items"], [])
        self.assertEqual(
            [item["事件种类"] for item in advisor["items"]],
            ["用户消息已受理", "已进入人工", "用户消息已受理", "运行未发布"],
        )
        self.assertEqual(advisor["items"][2]["用户原文"], "人工后的补充")
        self.assertGreater(advisor["items"][2]["事件序号"], advisor["items"][1]["事件序号"])
        self.assertIsNotNone(newer["user_visible"])
        self.assertEqual(self.fx.sessions.counts()["replies"], 0)

    def test_same_claim_cannot_execute_twice(self):
        accepted = self.accept()
        claim = self.fx.sessions.claim_task(
            accepted["internal"]["task_id"], "claim-once", self.fx.clock.now()
        )
        first = self.fx.gate.run_claimed(claim, accurate_proposal("apt-1", "是"))
        second = self.fx.gate.run_claimed(claim, Proposal(calls=(ToolCall("create_appointment", {}),)))
        self.assertTrue(second["retry_rejected"])
        self.assertEqual(second["run_id"], first["run_id"])
        self.assertEqual(self.fx.runs.count(), 1)
        self.assertEqual(self.fx.appointments.read_count, 1)

    def test_expired_claim_can_be_replaced_once(self):
        accepted = self.accept()
        first = self.fx.sessions.claim_task(
            accepted["internal"]["task_id"], "claim-a", self.fx.clock.now()
        )
        self.assertTrue(first["ok"])
        early = self.fx.sessions.reclaim_task(accepted["internal"]["task_id"], "claim-b", self.fx.clock.now())
        self.assertFalse(early["ok"])
        self.fx.clock.value += 20000
        second = self.fx.sessions.reclaim_task(accepted["internal"]["task_id"], "claim-b", self.fx.clock.now())
        late = self.fx.gate.run_claimed(first, accurate_proposal("apt-1", "是"))
        refused = self.fx.gate.publish(first["claim_id"])
        current = self.fx.gate.run_claimed(second, accurate_proposal("apt-1", "是"))
        published = self.fx.gate.publish(second["claim_id"])
        self.assertTrue(second["ok"])
        self.assertTrue(late["output_approved"])
        self.assertEqual(refused["reason"], "领取编号不匹配")
        self.assertTrue(current["output_approved"])
        self.assertTrue(published["ok"])
        self.assertEqual(self.fx.sessions.counts()["replies"], 1)

    def test_internal_credential_cannot_send_user_message(self):
        result = self.accept(credential="cred-advisor")
        self.assertEqual(result["reason"], "身份无权")
        self.assertIsNone(result["user_visible"])
        self.assertEqual(self.fx.sessions.counts()["messages"], 0)
        self.assertEqual(self.fx.sessions.counts()["refusals"], 1)

    def test_lookup_does_not_insert_after_unknown_timeout(self):
        unknown = self.fx.sessions.accept_message(
            "cred-owner",
            "sess-1",
            "req-timeout",
            "维保是否预约成功",
            "apt-1",
            elapsed_ms=1501,
        )
        found = self.fx.sessions.lookup_receipt("cred-owner", "sess-1", "req-timeout")
        self.assertEqual(unknown["结果"], "不明")
        self.assertEqual(found["结果"], "不明")
        self.assertEqual(self.fx.sessions.counts()["messages"], 0)

    def test_two_claimers_only_one_wins(self):
        accepted = self.accept()
        barrier = threading.Barrier(2)
        claims = []

        def once(claim_id):
            barrier.wait()
            claims.append(
                self.fx.sessions.claim_task(accepted["internal"]["task_id"], claim_id, self.fx.clock.now())
            )

        threads = [
            threading.Thread(target=once, args=("claim-1",)),
            threading.Thread(target=once, args=("claim-2",)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        winners = [item for item in claims if item["ok"]]
        losers = [item for item in claims if not item["ok"]]
        self.assertEqual(len(winners), 1)
        self.assertEqual(len(losers), 1)
        self.assertEqual(self.fx.sessions.counts()["claims"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
