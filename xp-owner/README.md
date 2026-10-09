# 小鹏车主客服：第一刀

Python 3.12、FastAPI、SQLAlchemy 2、PostgreSQL。四个可单独启动的 Python 包，各自进程、各自数据库。包之间只用携带 `X-Internal-Service-Token` 的 HTTP 通信，不导入其他服务的模型或服务。

| 包 | 端口 | 业务库 | 测试库 | 权威 |
| --- | --- | --- | --- | --- |
| xp_owner_service | 8000 | xp_owner | xp_owner_test | 会话事实、接管和发布裁决 |
| xp_procedure_service | 8001 | xp_procedure | xp_procedure_test | 当前流程说明版本 |
| xp_ai_service | 8002 | xp_ai | xp_ai_test | AgentRun 运行记录 |
| xp_account_service | 8003 | xp_account | xp_account_test | 凭证种类 |

每包均有 `app/routers`、`app/schemas`、`app/services`、`app/repositories`、`app/dependencies.py`、`models`、`infrastructure`、`common`。客服进一步分成 chat、ai、handoff、realtime 领域，另有 `worker/ai`、`worker/realtime`。模型只定义表，仓储执行查询/插入/条件更新/行锁，服务层拥有事务与发布裁决，路由校验身份并调用服务。

## 安装与配置

在本目录执行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:XP_PG_HOST = "192.168.100.128"
$env:XP_PG_USER = "你的建库账号"
$env:XP_PG_PASSWORD = "你的数据库密码"
.\.venv\Scripts\python.exe tools\bootstrap_databases.py --include-production
.\.venv\Scripts\python.exe tools\manage.py configure
.\.venv\Scripts\python.exe tools\manage.py initialize
```

建库工具只连接维护库 `postgres`，仅创建缺失的八个白名单库，不覆盖既有库。所有服务拒绝连接名为 `customer_service` 的数据库。`configure` 生成本地 `.env`，随机内部令牌和三枚凭证密钥，不打印内容；文件已被 `.gitignore` 排除，已存在则拒绝覆盖。初始化幂等，不改已有种子记录。修改已有凭证密钥的环境配置不会自动更新已存摘要。

可以参照 `.env.example` 自行配置。`manage.py` 从 `.env` 加载配置并生成各自数据库 URL；也支持直接设置 `XP_OWNER_DATABASE_URL`、`XP_PROCEDURE_DATABASE_URL`、`XP_AI_DATABASE_URL`、`XP_ACCOUNT_DATABASE_URL`。

在四个独立终端各启动一个包：

```powershell
.\.venv\Scripts\python.exe tools\manage.py serve account
.\.venv\Scripts\python.exe tools\manage.py serve procedure
.\.venv\Scripts\python.exe tools\manage.py serve ai
.\.venv\Scripts\python.exe tools\manage.py serve owner
```

加载环境变量后也可直接用 `python -m xp_account_service` 等命令。普通启动不建表；每个包的 `--initialize` 才执行建表与本服务种子初始化。默认只绑定 `127.0.0.1`。每个服务有 `GET /health`。

## 用户和顾问接口

用 `Authorization: Bearer <凭证密钥>`。客服在开启自己的事务前，以内部 HTTP 向账号服务验证凭证；车主/授权用车人可发消息，只有服务顾问可接管和获取顾问事件。账号库只有凭证编号、种类和不可逆密钥摘要三列，没有 VIN 和签发接口。

- `POST :8000/chat/messages`：`{"client_request_id":"唯一请求号","body":"如何在 App 里预约保养"}`。响应只有 `消息编号`、`会话编号`、`会话版本`、`已接收`，最后一项恒为 `是`。
- `GET :8000/chat/conversation`：查本凭证的未结束会话。
- `GET :8000/chat/conversations/{id}/events?after_seq=0`：本人的用户事件。
- `POST :8000/handoff`：顾问提交 `{"conversation_id":"...","request_id":"..."}`。
- `GET :8000/advisor/conversations/{id}/events?after_seq=0`：顾问四种事件。

相同会话中客户端请求号和原文完全一致时返回同一张回执；原文不同时 409，不插入任何新行。凭证最多一个未结束会话，由 PostgreSQL 部分唯一索引约束，首次并发创建通过 `INSERT ... ON CONFLICT DO NOTHING` 等待胜者提交，再 `SELECT FOR UPDATE` 锁住胜者。身份错误不打开客服写事务。

## 内部运行与发布

内部接口必须携带内部令牌，用户凭证没有内部权限。客服内部接口包括 `POST /internal/turns/claim`、`POST /internal/results/publish`、`GET /internal/turns/{id}/reply`、`POST /internal/worker/tick`。发布接口只接受领取/请求编号，自己通过 HTTP 重读 AgentRun，不接受外部正文或人为指定的 `elapsed_ms/read_failed`。

流程服务只有 `GET /internal/procedures/current?flow_key=App预约保养步骤`；账号只有 `POST /internal/credentials/verify`；运行服务有 `POST /internal/runs` 和 `GET /internal/runs/by-request/{request_id}`。运行请求字段为 `request_id`、`turn_id`、`claim_id`、`snapshot_revision`，请求号唯一，同输入返回原记录，不同输入 409。

受理事务锁会话，提交用户消息、版本、收集轮次、受理事件及 outbox 后立即返回。初始收集 1500ms，每条连续消息把既有截止时间推后 1500ms，上限为开始后 8000ms。收集截止且模式为 AI、没有其他 RUNNING 轮次时才可领取。只有该轮恰好一条原文逐字等于精确问题才调用运行服务；其他轮次标 ATTENTION，无运行记录、无机器人答复。

领取租约 30 秒，最多三次；条件更新领取，每次生成新领取号和运行请求号。过期且版本未变才可重领；版本变更标 SUPERSEDED；三次过期标 TIMED_OUT 并写 `执行超时`。同一会话至多一个 RUNNING 轮次也有部分唯一索引约束。

运行服务仅通过 HTTP 读取当前流程，并原样复制到自己的 AgentRun。发布在客服的独立事务锁会话及轮次，再通过 HTTP 重读流程服务。按规定顺序核对版本、领取、租约、模式、流程状态和逐字字段，成功原子写已发布回复、事件和 outbox。已发布回复的轮次编号唯一。旧领取不改当前轮次，也不覆盖新执行者。模糊的 HTTP 结果只按请求号重读运行，未知发布提交结果只读已发布回复；缺失时等待租约，不写补偿失败。

顾问接管只在 AI 模式条件更新成功一次，原子失效未完成轮次并写 `已进入人工`。已发布历史保留，之后的新消息仍受理但不进入机器人轮次。

默认客服进程内的 AI worker 线程负责扫描与运行，测试设置 `XP_AI_WORKER_ENABLED=false` 后用受保护的 tick 精确驱动时序。realtime worker 本步仅保留包，不投递。事件存储与 RealtimeOutbox 同一事务落库；outbox 有行只表示待通知。按事件序号补取，按事件编号去重，用户和顾问响应分别使用字段白名单。

跨库发布检查采用流程 HTTP 读取时返回的版本；流程在另一个库中，不存在跨库行锁或分布式原子事务。本步没有流程变更入口。

## 验证

```powershell
.\.venv\Scripts\python.exe tools\manage.py test
```

测试启动四个真实 Python 进程，在固定 8000–8003 端口通过真实 HTTP 互调，分别连接四个 `_test` 库。端口被占用则拒绝替换现有服务。每次运行创建随机独立 schema，保留数据以便检查；不删除数据库/表，不 `drop_all`、不 `TRUNCATE`，不使用 SQLite 或内存列表代替数据库。用 UPDATE 把测试截止时间/租约移到过去。测试结束自动回收本次启动的四个进程。

包含五个指定场景：并发相同受理、连续消息转人工关注、旧输入拒绝发布、接管后不再机器人回答且保留历史、错误身份与下架拒绝。还检查三次租约、领取更换、运行幂等、并发发布、内部鉴权、逐码点比较、收集上限、字段白名单、部分唯一索引以及 outbox 待通知状态。命令输出和 `artifacts/verify_*/result.json` 是验证依据。

## 本步范围

唯一流程种子为 `App预约保养步骤`，当前发布版部分唯一索引按流程键约束：

- 标题：App 预约保养步骤
- 步骤：【非官方占位】此处不是小鹏官方步骤。上线前必须替换为人工审核原句。
- 边界句：这只说明 App 里的预约步骤，不表示已经预约成功，也不表示这台车在保。

本步不实现远程控车、救援、维保预约或改期、交付修改、家充、在保查询、政策文本、VIN 绑定、凭证签发、外部模型、WebSocket 投递、切换 VIN、前端，也不连接 Redis。
