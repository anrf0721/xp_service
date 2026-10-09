"""Four real processes, HTTP only across services, four PostgreSQL _test DBs.

Every run creates a fresh schema in each test DB and retains it for inspection.
No production URL, SQLite, DROP, TRUNCATE or service-model imports are used.
"""
import concurrent.futures
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import threading
import time
import unittest
from uuid import uuid4

import httpx
import psycopg
from psycopg import sql
from sqlalchemy.engine import URL, make_url

ROOT = Path(__file__).resolve().parents[1]
SERVICES = {"owner": 8000, "procedure": 8001, "ai": 8002, "account": 8003}
EXACT = "如何在 App 里预约保养"
STEPS = "【非官方占位】此处不是小鹏官方步骤。上线前必须替换为人工审核原句。"
BOUNDARY = "这只说明 App 里的预约步骤，不表示已经预约成功，也不表示这台车在保。"
SCHEMA = "verify_" + uuid4().hex
ARTIFACTS = ROOT / "artifacts" / SCHEMA
TOKEN = secrets.token_urlsafe(32)
SECRETS = {kind: secrets.token_urlsafe(24) for kind in ("owner", "authorized_user", "advisor")}
URLS = {}
PROCESSES = []
LOGS = []


def connection(service):
    url = make_url(URLS[service])
    expected = "xp_" + service + "_test"
    if url.get_backend_name() != "postgresql" or url.database != expected:
        raise RuntimeError("Integration connections must use their dedicated _test database")
    return psycopg.connect(host=url.host, port=url.port or 5432, dbname=url.database,
        user=url.username, password=url.password, options="-csearch_path=" + SCHEMA, autocommit=True)


def query(service, statement, params=()):
    with connection(service) as conn:
        cursor = conn.execute(statement, params)
        return cursor.fetchall() if cursor.description else []


def call(service, method, path, *, data=None, role=None, internal=False, params=None):
    headers = {}
    if role:
        headers["Authorization"] = "Bearer " + SECRETS[role]
    if internal:
        headers["X-Internal-Service-Token"] = TOKEN
    with httpx.Client(timeout=20, trust_env=False) as client:
        return client.request(method, f"http://127.0.0.1:{SERVICES[service]}" + path, json=data, headers=headers, params=params)


def start_services():
    ARTIFACTS.mkdir(parents=True)
    env = dict(os.environ)
    env.update(XP_INTERNAL_SERVICE_TOKEN=TOKEN, XP_OWNER_SECRET=SECRETS["owner"],
        XP_AUTHORIZED_USER_SECRET=SECRETS["authorized_user"], XP_ADVISOR_SECRET=SECRETS["advisor"],
        XP_AI_WORKER_ENABLED="false", XP_BIND_HOST="127.0.0.1", PGOPTIONS="-csearch_path=" + SCHEMA,
        PYTHONUTF8="1", PYTHONUNBUFFERED="1")
    for service, port in SERVICES.items():
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                raise RuntimeError(f"Port {port} is in use; refusing to replace an existing server")
        name = "xp_" + service + "_test"
        key = "XP_" + service.upper() + "_DATABASE_URL"
        if key in os.environ:
            url = make_url(os.environ[key])
        else:
            url = URL.create("postgresql+psycopg", username=os.environ["XP_PG_USER"], password=os.environ["XP_PG_PASSWORD"],
                host=os.environ["XP_PG_HOST"], port=int(os.environ.get("XP_PG_PORT", "5432")), database=name)
        if url.get_backend_name() != "postgresql" or url.database != name:
            raise RuntimeError(f"{key} must point to {name}")
        URLS[service] = url.render_as_string(hide_password=False)
        env[key] = URLS[service]
        with connection(service) as conn:
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(SCHEMA)))
        log = (ARTIFACTS / f"{service}.log").open("w", encoding="utf-8")
        LOGS.append(log)
        initialized = subprocess.run([sys.executable, "-m", f"xp_{service}_service", "--initialize"], cwd=ROOT,
            env=env, stdout=log, stderr=subprocess.STDOUT, timeout=30)
        if initialized.returncode:
            raise RuntimeError(f"{service} initialization failed; inspect its artifact log")
    for service in ("account", "procedure", "ai", "owner"):
        log = LOGS[list(SERVICES).index(service)]
        proc = subprocess.Popen([sys.executable, "-m", f"xp_{service}_service"], cwd=ROOT, env=env,
            stdout=log, stderr=subprocess.STDOUT)
        PROCESSES.append(proc)
        started = time.monotonic()
        while True:
            if proc.poll() is not None:
                raise RuntimeError(f"{service} exited during startup; inspect its artifact log")
            try:
                if call(service, "GET", "/health").status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if time.monotonic() - started > 20:
                raise RuntimeError(f"{service} health timeout")
            time.sleep(0.1)
        print(f"STARTED xp_{service}_service pid={proc.pid} port={SERVICES[service]} db=xp_{service}_test", flush=True)
    print("TEST_SCHEMA", SCHEMA, flush=True)


def stop_services():
    for proc in reversed(PROCESSES):
        if proc.poll() is None:
            proc.terminate()
    for proc in PROCESSES:
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    for log in LOGS:
        log.close()


class FourServiceTests(unittest.TestCase):
    def setUp(self):
        query("owner", "UPDATE conversations SET mode = 'CLOSED' WHERE mode <> 'CLOSED'")
        query("procedure", "UPDATE procedure_versions SET current_published = true, withdrawn = false WHERE version_id = 'placeholder-v1'")

    def send(self, body=EXACT, request_id=None, role="owner"):
        response = call("owner", "POST", "/chat/messages", role=role,
            data={"client_request_id": request_id or uuid4().hex, "body": body})
        self.assertEqual(response.status_code, 200, response.text)
        receipt = response.json()
        self.assertEqual(set(receipt), {"消息编号", "会话编号", "会话版本", "已接收"})
        self.assertEqual(receipt["已接收"], "是")
        return receipt

    def due(self, conversation_id):
        query("owner", "UPDATE conversation_turns SET collect_until = now() - interval '1 second' WHERE conversation_id = %s AND status = 'COLLECTING'", (conversation_id,))

    def claim(self, conversation_id):
        response = call("owner", "POST", "/internal/turns/claim", internal=True, data={"conversation_id": conversation_id})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def run_ai(self, claim):
        response = call("ai", "POST", "/internal/runs", internal=True,
            data={key: claim[key] for key in ("request_id", "turn_id", "claim_id", "snapshot_revision")})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def publish(self, claim):
        response = call("owner", "POST", "/internal/results/publish", internal=True,
            data={key: claim[key] for key in ("claim_id", "request_id")})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def events(self, conv_id, advisor=False, after_seq=0):
        path = ("/advisor" if advisor else "/chat") + f"/conversations/{conv_id}/events"
        response = call("owner", "GET", path, role="advisor" if advisor else "owner", params={"after_seq": after_seq})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["items"]

    def count(self, service, table, where="", params=()):
        return query(service, f"SELECT count(*) FROM {table} {where}", params)[0][0]

    def expire(self, claim):
        query("owner", "UPDATE conversation_turns SET locked_until = now() - interval '1 second' WHERE id = %s", (claim["turn_id"],))
        query("owner", "UPDATE claims SET locked_until = now() - interval '1 second' WHERE id = %s", (claim["claim_id"],))

    def snapshot_owner(self):
        tables = ["conversations", "messages", "conversation_turns", "turn_messages", "claims", "published_replies", "handoffs", "conversation_events", "realtime_outbox"]
        return {table: self.count("owner", table) for table in tables}

    def test_01_concurrent_identical_first_acceptance(self):
        before = self.snapshot_owner()
        barrier = threading.Barrier(2)
        def send():
            barrier.wait(timeout=5)
            return self.send(request_id="concurrent-first")
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(send), pool.submit(send)]
            receipts = [future.result(timeout=20) for future in futures]
        self.assertEqual(receipts[0], receipts[1])
        after = self.snapshot_owner()
        for table in ("conversations", "messages", "conversation_turns", "conversation_events", "realtime_outbox"):
            self.assertEqual(after[table] - before[table], 1, table)
        self.assertEqual(receipts[0]["会话版本"], 1)

    def test_02_second_sentence_routes_attention_without_run(self):
        before_runs = self.count("ai", "agent_runs")
        first = self.send()
        second = self.send("另一句")
        self.assertEqual(second["会话版本"], 2)
        self.due(first["会话编号"])
        result = self.claim(first["会话编号"])
        self.assertFalse(result["claimed"])
        self.assertEqual(result["reason"], "需要人工关注")
        self.assertEqual(self.count("ai", "agent_runs"), before_runs)
        self.assertEqual(self.count("owner", "published_replies", "WHERE conversation_id = %s", (first["会话编号"],)), 0)
        self.assertEqual([x["用户原文"] for x in self.events(first["会话编号"], advisor=True)], [EXACT, "另一句"])

    def test_03_new_revision_refuses_old_run(self):
        first = self.send()
        self.due(first["会话编号"])
        claim = self.claim(first["会话编号"])
        self.assertTrue(claim["claimed"])
        self.run_ai(claim)
        self.send("运行写完后的另一句")
        result = self.publish(claim)
        self.assertEqual(result, {"published": False, "reason": "输入版本已失效"})
        self.assertEqual(self.events(first["会话编号"]), [])
        failures = [x for x in self.events(first["会话编号"], advisor=True) if x["事件种类"] == "运行未发布"]
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["失败原因"], "输入版本已失效")
        self.assertEqual(set(failures[0]), {"事件编号", "事件序号", "事件种类", "任务编号", "领取编号", "运行编号", "失败原因", "输入会话版本", "拒绝时的当前会话版本", "引用的流程版本编号"})
        self.publish(claim)
        self.assertEqual(len([x for x in self.events(first["会话编号"], advisor=True) if x["事件种类"] == "运行未发布"]), 1)

    def test_04_handoff_preserves_history_and_blocks_future_ai(self):
        first = self.send()
        conv_id = first["会话编号"]
        self.due(conv_id)
        claim = self.claim(conv_id)
        self.run_ai(claim)
        self.assertTrue(self.publish(claim)["published"])
        history = self.events(conv_id)
        self.assertEqual(history[0]["步骤"], STEPS)
        self.assertEqual(history[0]["边界句"], BOUNDARY)
        self.assertEqual(set(history[0]), {"事件编号", "事件序号", "事件种类", "回复种类", "流程键", "版本编号", "版本标签", "标题", "步骤", "边界句"})
        # Also invalidate a run which had already been claimed before takeover.
        self.send()
        self.due(conv_id)
        old_claim = self.claim(conv_id)
        self.run_ai(old_claim)
        before_runs = self.count("ai", "agent_runs")
        take = call("owner", "POST", "/handoff", role="advisor", data={"conversation_id": conv_id, "request_id": "take-once"})
        self.assertEqual(take.status_code, 200, take.text)
        self.assertFalse(take.json()["重复"])
        self.assertEqual(self.publish(old_claim)["reason"], "已进入人工")
        take_again = call("owner", "POST", "/handoff", role="advisor", data={"conversation_id": conv_id, "request_id": "take-again"})
        self.assertTrue(take_again.json()["重复"])
        after_take = self.events(conv_id, after_seq=history[0]["事件序号"])
        self.assertEqual([x["事件种类"] for x in after_take], ["已进入人工"])
        takeover_seq = after_take[0]["事件序号"]
        self.assertEqual(set(after_take[0]), {"事件编号", "事件序号", "事件种类", "会话编号", "会话版本", "接管时间"})
        message = self.send()
        self.assertEqual(self.count("owner", "turn_messages", "WHERE message_id = %s", (message["消息编号"],)), 0)
        self.assertFalse(self.claim(conv_id)["claimed"])
        call("owner", "POST", "/internal/worker/tick", internal=True)
        self.assertEqual(self.count("ai", "agent_runs"), before_runs)
        self.assertEqual(self.count("owner", "published_replies", "WHERE conversation_id = %s", (conv_id,)), 1)
        self.assertEqual(self.events(conv_id, after_seq=history[0]["事件序号"])[0]["事件种类"], "已进入人工")
        advisor_after = self.events(conv_id, advisor=True, after_seq=takeover_seq)
        self.assertEqual(advisor_after[-1]["事件种类"], "用户消息已受理")
        self.assertEqual(advisor_after[-1]["用户原文"], EXACT)

    def test_05_wrong_identity_and_withdrawal(self):
        before = self.snapshot_owner()
        denied = call("owner", "POST", "/chat/messages", role="advisor", data={"client_request_id": "denied", "body": EXACT})
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(before, self.snapshot_owner())
        invalid = call("owner", "POST", "/chat/messages", data={"client_request_id": "denied", "body": EXACT})
        self.assertEqual(invalid.status_code, 403)
        self.assertEqual(before, self.snapshot_owner())
        first = self.send()
        self.due(first["会话编号"])
        claim = self.claim(first["会话编号"])
        self.run_ai(claim)
        query("procedure", "UPDATE procedure_versions SET current_published = false, withdrawn = true WHERE version_id = 'placeholder-v1'")
        self.assertEqual(self.publish(claim)["reason"], "流程已下架")
        self.assertEqual(self.events(first["会话编号"]), [])
        self.assertEqual(self.count("owner", "published_replies", "WHERE turn_id = %s", (claim["turn_id"],)), 0)

    def test_06_same_id_changed_text_and_internal_boundaries(self):
        first = self.send(request_id="same-id")
        before = self.snapshot_owner()
        conflict = call("owner", "POST", "/chat/messages", role="owner", data={"client_request_id": "same-id", "body": EXACT + " "})
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(set(conflict.json()), {"reason"})
        self.assertEqual(before, self.snapshot_owner())
        self.assertEqual(self.send(request_id="same-id"), first)
        for service, method, path, data in [
            ("owner", "POST", "/internal/turns/claim", {"conversation_id": first["会话编号"]}),
            ("owner", "POST", "/internal/results/publish", {"claim_id": "x", "request_id": "x"}),
            ("ai", "POST", "/internal/runs", {"request_id": "x", "claim_id": "x", "turn_id": "x", "snapshot_revision": 1}),
            ("account", "POST", "/internal/credentials/verify", {"secret": SECRETS["owner"]}),
            ("procedure", "GET", "/internal/procedures/current", None),
        ]:
            self.assertEqual(call(service, method, path, role="owner", data=data).status_code, 401)
        self.assertEqual(self.count("account", "credentials"), 3)

    def test_07_three_leases_stale_claim_and_timeout(self):
        receipt = self.send()
        conv_id = receipt["会话编号"]
        self.due(conv_id)
        first = self.claim(conv_id)
        self.run_ai(first)
        self.expire(first)
        self.assertEqual(self.publish(first)["reason"], "租约已过期")
        self.assertEqual(query("owner", "SELECT status FROM conversation_turns WHERE id=%s", (first["turn_id"],))[0][0], "RUNNING")
        second = self.claim(conv_id)
        self.assertEqual(second["attempt"], 2)
        self.assertNotEqual(first["claim_id"], second["claim_id"])
        before = self.snapshot_owner()
        self.assertEqual(self.publish(first)["reason"], "领取编号不匹配")
        self.assertEqual(before, self.snapshot_owner())
        self.expire(second)
        third = self.claim(conv_id)
        self.assertEqual(third["attempt"], 3)
        self.expire(third)
        self.assertEqual(self.claim(conv_id)["reason"], "执行超时")
        self.assertFalse(self.claim(conv_id)["claimed"])
        self.assertEqual(self.count("owner", "claims", "WHERE turn_id=%s", (first["turn_id"],)), 3)
        failures = [x for x in self.events(conv_id, advisor=True) if x["事件种类"] == "运行未发布"]
        self.assertEqual(failures[-1]["失败原因"], "执行超时")
        self.assertEqual(self.events(conv_id), [])

    def test_08_run_idempotency_and_concurrent_publish(self):
        receipt = self.send()
        self.due(receipt["会话编号"])
        claim = self.claim(receipt["会话编号"])
        before = self.count("ai", "agent_runs")
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _: self.run_ai(claim), range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(self.count("ai", "agent_runs") - before, 1)
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            published = list(pool.map(lambda _: self.publish(claim), range(2)))
        self.assertTrue(all(x["published"] for x in published))
        self.assertEqual(self.count("owner", "published_replies", "WHERE turn_id=%s", (claim["turn_id"],)), 1)
        self.assertEqual(len(self.events(receipt["会话编号"])), 1)
        self.assertTrue(self.publish(claim)["published"])
        self.assertEqual(len(self.events(receipt["会话编号"])), 1)

    def test_09_codepoints_collection_cap_and_indexes(self):
        before_runs = self.count("ai", "agent_runs")
        receipt = self.send(EXACT + " ")
        self.due(receipt["会话编号"])
        self.assertEqual(self.claim(receipt["会话编号"])["reason"], "需要人工关注")
        self.assertEqual(self.count("ai", "agent_runs"), before_runs)
        self.send("cap-start")
        for _ in range(8):
            self.send("more")
        delta = query("owner", "SELECT extract(epoch from (collect_until-started_at)), collect_until=max_collect_until FROM conversation_turns WHERE conversation_id=%s AND status='COLLECTING'", (receipt["会话编号"],))[0]
        self.assertEqual(float(delta[0]), 8.0)
        self.assertTrue(delta[1])
        indexes = query("owner", "SELECT indexdef FROM pg_indexes WHERE schemaname=%s AND indexname='uq_open_conversation_credential'", (SCHEMA,))
        self.assertIn("WHERE", indexes[0][0])
        indexes = query("procedure", "SELECT indexdef FROM pg_indexes WHERE schemaname=%s AND indexdef LIKE '%%current_published%%'", (SCHEMA,))
        self.assertTrue(any("UNIQUE" in row[0] and "WHERE" in row[0] for row in indexes))

    def test_10_worker_real_http_path_and_pending_outbox(self):
        receipt = self.send()
        self.due(receipt["会话编号"])
        result = call("owner", "POST", "/internal/worker/tick", internal=True)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertTrue(any(item.get("published") for item in result.json()["results"]))
        self.assertEqual(len(self.events(receipt["会话编号"])), 1)
        outbox = query("owner", "SELECT payload, delivered FROM realtime_outbox WHERE conversation_id=%s ORDER BY id", (receipt["会话编号"],))
        self.assertEqual(len(outbox), 2)
        self.assertTrue(all(not row[1] for row in outbox))
        for payload, _ in outbox:
            self.assertIn("事件编号", payload)
        for secret in [TOKEN, *SECRETS.values()]:
            self.assertNotIn(secret, json.dumps(outbox, ensure_ascii=False))

    def test_11_changed_revision_cannot_reclaim_old_turn(self):
        receipt = self.send()
        self.due(receipt["会话编号"])
        old = self.claim(receipt["会话编号"])
        self.send("changed while lease pending")
        self.expire(old)
        self.assertEqual(self.claim(receipt["会话编号"])["reason"], "输入版本已失效")
        self.assertEqual(query("owner", "SELECT status, attempts FROM conversation_turns WHERE id=%s", (old["turn_id"],))[0], ("SUPERSEDED", 1))

    def test_12_field_tampering_refused_and_run_retry_contract(self):
        receipt = self.send()
        self.due(receipt["会话编号"])
        claim = self.claim(receipt["会话编号"])
        run = self.run_ai(claim)
        by_request = call("ai", "GET", "/internal/runs/by-request/" + claim["request_id"], internal=True)
        self.assertEqual(by_request.json(), run)
        before = self.count("ai", "agent_runs")
        changed = {key: claim[key] for key in ("request_id", "turn_id", "claim_id", "snapshot_revision")}
        changed["snapshot_revision"] += 1
        self.assertEqual(call("ai", "POST", "/internal/runs", internal=True, data=changed).status_code, 409)
        self.assertEqual(self.count("ai", "agent_runs"), before)
        query("ai", "UPDATE agent_runs SET steps = steps || 'extra' WHERE request_id=%s", (claim["request_id"],))
        self.assertEqual(self.publish(claim)["reason"], "展示字段违规")
        self.assertEqual(self.events(receipt["会话编号"]), [])

    def test_13_version_priority_and_secret_validation(self):
        receipt = self.send()
        self.due(receipt["会话编号"])
        claim = self.claim(receipt["会话编号"])
        self.run_ai(claim)
        self.send("another revision")
        self.expire(claim)
        self.assertEqual(self.publish(claim)["reason"], "输入版本已失效")
        invalid = call("account", "POST", "/internal/credentials/verify", internal=True,
            data={"secret": SECRETS["owner"], "extra": SECRETS["advisor"]})
        self.assertEqual(invalid.status_code, 422)
        for secret in SECRETS.values():
            self.assertNotIn(secret, invalid.text)
        injected = {key: claim[key] for key in ("request_id", "turn_id", "claim_id", "snapshot_revision")}
        injected["read_failed"] = True
        self.assertEqual(call("ai", "POST", "/internal/runs", internal=True, data=injected).status_code, 422)
        injected.pop("read_failed")
        injected["elapsed_ms"] = 99999
        self.assertEqual(call("ai", "POST", "/internal/runs", internal=True, data=injected).status_code, 422)


def main():
    success = False
    try:
        start_services()
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(FourServiceTests)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        success = result.wasSuccessful()
        report = {"schema": SCHEMA, "databases": [f"xp_{name}_test" for name in SERVICES],
            "process_count": len(PROCESSES), "tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors), "passed": success}
        (ARTIFACTS / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        stop_services()
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
