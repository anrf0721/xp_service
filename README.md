# xp-owner-min

小鹏车主客服客户端的最小切片。四个子目录是同一个进程、同一个 PostgreSQL 库里的模块。

## 本步

只验证已审核流程说明的受理、收集、领取、运行记录、发布和补取。

精确原文是「如何在 App 里预约保养」。步骤是非官方占位，不是小鹏官方点击路径。

## 本步不做

- 远程控车
- 发起救援
- 创建或修改维保预约
- 修改交付单
- 写入家充工单
- 用政策文本回答“这台车当前在保”
- 外部模型调用接口
- 网络推送投递接口
- 切换 VIN 入口
- 账号与人车关系在线查询接口
- VIN 绑定表
- 凭证签发接口
- 流程说明审核发布入口
- 单车在保状态查询接口
- 质保政策版本读取接口

## 验证

连接现有库 `customer_service`，只新建 schema `owner_client`。不修改 public 里已有的五张表。

```powershell
$env:XP_PG_URL = "postgresql+psycopg://customer_service:customer_service@192.168.100.128:5432/customer_service"
py -3.12 verify_client.py
```

```powershell
$env:XP_PG_ADMIN_URL = "postgresql+psycopg://用户:密码@192.168.100.128:5432/postgres"
$env:XP_PG_TEST_DB = "xp_owner_min_verify"
python verify_client.py
```

库已存在时测试拒绝继续，不会 `DROP DATABASE`，也不会 `drop_all`。
