# 实际验证记录

运行环境：Windows，Python 3.12.8，独立 `.venv`。所有操作范围在新建 `xp-owner/` 中，没有读取或导入旧项目。

维护连接只使用 `postgres` 库，创建了八个新的独立库。四个业务库已经初始化：`xp_owner`、`xp_procedure`、`xp_ai`、`xp_account`。账号初始化只有三种凭证，密钥以不可逆摘要保存；流程种子保留指定的非官方占位原句。没有连接 `customer_service` 库。

测试命令（数据库密码从环境变量提供，不在记录中保存）：

```powershell
$env:XP_PG_HOST = '192.168.100.128'
$env:XP_PG_USER = '<已配置的 PostgreSQL 角色>'
$env:XP_PG_PASSWORD = '<本地数据库密码>'
$env:PYTHONUTF8 = '1'
.\.venv\Scripts\python.exe tests\integration.py
```

实际进程启动输出：

```text
STARTED xp_account_service pid=36860 port=8003 db=xp_account_test
STARTED xp_procedure_service pid=42816 port=8001 db=xp_procedure_test
STARTED xp_ai_service pid=29176 port=8002 db=xp_ai_test
STARTED xp_owner_service pid=38168 port=8000 db=xp_owner_test
TEST_SCHEMA verify_55aa824467fe4b2fb4d43e90e22877c2
```

实际测试结果：

```text
test_01_concurrent_identical_first_acceptance ... ok
test_02_second_sentence_routes_attention_without_run ... ok
test_03_new_revision_refuses_old_run ... ok
test_04_handoff_preserves_history_and_blocks_future_ai ... ok
test_05_wrong_identity_and_withdrawal ... ok
test_06_same_id_changed_text_and_internal_boundaries ... ok
test_07_three_leases_stale_claim_and_timeout ... ok
test_08_run_idempotency_and_concurrent_publish ... ok
test_09_codepoints_collection_cap_and_indexes ... ok
test_10_worker_real_http_path_and_pending_outbox ... ok
test_11_changed_revision_cannot_reclaim_old_turn ... ok
test_12_field_tampering_refused_and_run_retry_contract ... ok
test_13_version_priority_and_secret_validation ... ok

Ran 13 tests in 53.948s

OK
```

机器可读结果保存在 `artifacts/verify_55aa824467fe4b2fb4d43e90e22877c2/result.json`。四个服务日志在同目录。每次测试建立新的独立 schema，既有测试数据保留；无需 DROP、TRUNCATE 或 `drop_all`。

| 指定场景 | 实际断言 |
| --- | --- |
| 两个相同请求首次并发受理 | 两次同一张四字段回执，新增一条用户消息、一个轮次、一条受理事件和 outbox |
| 收集截止前再提交另一句 | ATTENTION，没有新增 AgentRun、没有已发布回复，顾问保留两句原文 |
| 运行写完后新消息使旧输入失效 | 无用户回复，运行未发布原因为输入版本已失效，重复发布不重复写失败 |
| 进入人工后继续发精确问句 | 接管事件可按序号补取，新消息不挂轮次、不调用运行服务，顾问能看到新受理，历史回复仍在；已领轮次拒绝原因为已进入人工 |
| 身份错误及流程下架 | 错误身份前后客服九张表计数完全相同；运行完成后撤下流程版，发布拒绝且无回复 |

补充验证覆盖三次 30 秒租约、重领换号、旧执行者不写库、运行唯一请求号并发幂等、轮次唯一回复并发发布、内部令牌保护、字段白名单、步骤篡改拒绝、逐码点精确匹配、8000ms 收集上限、部分唯一索引和 outbox 未投递状态。

编译命令执行成功：

```powershell
.\.venv\Scripts\python.exe -m compileall -q xp_owner_service xp_account_service xp_procedure_service xp_ai_service tools tests
```

测试结束后实际端口检查：

```text
PYTHON 3.12.8
PORT 8000 FREE
PORT 8001 FREE
PORT 8002 FREE
PORT 8003 FREE
```

这是第一刀的事务及 HTTP 链路验证。跨库流程复核以 HTTP 读取时的状态为准，没有跨库锁或分布式事务。RealtimeOutbox 仅待通知，未执行 Redis/WebSocket/推送投递。官方流程步骤仍需上线前人工替换。本步没有外部模型或用户业务写入。
