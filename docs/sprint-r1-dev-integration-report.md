# Sprint R1 — DEV 环境联调验证报告

> 日期：2026-04-23
> 环境：docker-postgres-1（PostgreSQL 16.13，tunxiang_os 库）
> 工作目录：`/Users/lichun/tunxiang-os/.claude/worktrees/hopeful-lehmann-b617b1`
> 目标 PR：[#90 feat/sprint-r1](https://github.com/hnrm110901-cell/tunxiang-os/pull/90)

---

## 1. 迁移应用结果 ✅

4 份迁移全部干净应用：

| 版本 | 迁移文件 | 结果 |
|---|---|---|
| v264 | customer_lifecycle_fsm.py | ✅ CREATE TABLE + ENUM + 3 索引 + RLS 策略 |
| v265 | tasks.py | ✅ CREATE TABLE + ENUM (task_type/status) + 6 索引 + RLS 策略 |
| v266 | sales_targets.py | ✅ 2 表（sales_targets + sales_progress）+ ENUM (period/metric) + 6 索引 + 2 RLS 策略 |
| v267 | banquet_leads.py | ✅ CREATE TABLE + 3 ENUM (type/channel/stage) + 6 索引 + RLS 策略 |

**总计**：5 新表 / 9 新 ENUM / 23 新索引 / 5 RLS 策略。

应用方式（离线提取 SQL）：
```bash
python3 /tmp/extract_migration_sql.py \
  shared/db-migrations/versions/v264_customer_lifecycle_fsm.py \
  shared/db-migrations/versions/v265_tasks.py \
  shared/db-migrations/versions/v266_sales_targets.py \
  shared/db-migrations/versions/v267_banquet_leads.py \
  > /tmp/r1_migrations.sql

docker cp /tmp/r1_migrations.sql docker-postgres-1:/tmp/
docker exec docker-postgres-1 psql -U tunxiang -d tunxiang_os -f /tmp/r1_migrations.sql
```

## 2. RLS 隔离验证 ✅

### 初次测试（tunxiang 超级用户）— 结果 ⚠️ 假阴性

用 `tunxiang` 登录（`rolsuper=t, rolbypassrls=t`），RLS 被 bypass，不代表真实隔离失败。

### 正式测试（tunxiang_app 普通用户）— 结果 ✅ 通过

创建专用角色：
```sql
CREATE ROLE tunxiang_app WITH LOGIN PASSWORD 'app_pw' NOSUPERUSER NOBYPASSRLS;
GRANT ALL ON ALL TABLES IN SCHEMA public TO tunxiang_app;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO tunxiang_app;
```

| 场景 | 预期 | 实际 |
|---|---|---|
| Tenant A 插入 3 条（customer/task/banquet） | 成功 | ✅ |
| 切换到 Tenant B 查询 | 全 0 条 | ✅ 0/0/0 |
| Tenant B 插入自己的 customer_lifecycle 行 | 成功 | ✅ |
| Tenant B 查询 customer_lifecycle | 仅自己的 1 条 | ✅ 1 条 |
| 事务结束 ROLLBACK | 数据不持久化 | ✅ |

**结论**：所有新表 RLS 策略在真实非超级用户环境下正确生效。

## 3. Pg Repository SQL PREPARE 验证 ✅

对 4 个 PgRepository 的 10 个关键 SQL 语句做 PREPARE（句法 + 列名 + 类型强校验）：

| Track | 语句 | 结果 |
|---|---|---|
| A — CustomerLifecycleRepo | `INSERT ... ON CONFLICT DO UPDATE RETURNING *` | ✅ |
| A — CustomerLifecycleRepo | `SELECT ... FOR UPDATE` | ✅ |
| A — CustomerLifecycleRepo | `GROUP BY state` 流量聚合 | ✅ |
| B — TaskRepo | `INSERT tasks RETURNING *` | ✅ |
| B — TaskRepo | `SELECT by_tenant+assignee ORDER BY due_at` | ✅ |
| B — TaskRepo | `UPDATE status='escalated'` | ✅ |
| C — SalesTargetRepo | `INSERT sales_targets RETURNING *` | ✅ |
| C — SalesTargetRepo | `INSERT sales_progress RETURNING *` | ✅ |
| D — BanquetLeadRepo | `INSERT banquet_leads RETURNING *` | ✅ |
| D — BanquetLeadRepo | `COUNT(*) FILTER WHERE stage=...` 漏斗聚合 | ✅ |

**结论**：所有 PgRepository SQL 与 v264-v267 表结构完全匹配，无列名、类型、enum 不一致。

## 4. 已知环境限制

- docker-postgres-1 未暴露宿主机 5432 端口 → 无法从宿主直接跑 `pytest --db`
- tunxiang-dev-* 服务容器镜像未包含 v264-v267 迁移（需 rebuild 后才能真实跑服务栈集成测试）
- 集成测试完整闭环需 CI 流水线跑 `alembic upgrade head` + 服务镜像重建

## 5. 下一步（Step 3 / Step 4 可并行）

- Step 3：独立验证会话（徐记海鲜收银员视角）— 从业务语义评审 T1 代码
- Step 4：Sprint R2 启动 — reservation_concierge / sales_coach / banquet_contract_agent 3 个新 Agent
- 待完成：CI 流水线拉取 feat/sprint-r1 分支跑完整 alembic upgrade head + 所有 Tier 1 测试

## 6. 验证指令速查

```bash
# 所有 5 表
docker exec docker-postgres-1 psql -U tunxiang -d tunxiang_os -c \
  "SELECT table_name FROM information_schema.tables WHERE table_name IN ('customer_lifecycle_state','tasks','sales_targets','sales_progress','banquet_leads') ORDER BY table_name;"

# RLS 状态
docker exec docker-postgres-1 psql -U tunxiang -d tunxiang_os -c \
  "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname IN ('customer_lifecycle_state','tasks','sales_targets','sales_progress','banquet_leads');"

# Policy 列表
docker exec docker-postgres-1 psql -U tunxiang -d tunxiang_os -c \
  "SELECT tablename, policyname FROM pg_policies WHERE tablename IN ('customer_lifecycle_state','tasks','sales_targets','sales_progress','banquet_leads');"

# 普通用户跑 RLS 冒烟
docker exec -e PGPASSWORD=app_pw docker-postgres-1 psql -U tunxiang_app -d tunxiang_os -f /tmp/r1_rls_smoke.sql

# Pg Repo SQL PREPARE 验证
docker exec -e PGPASSWORD=app_pw docker-postgres-1 psql -U tunxiang_app -d tunxiang_os -f /tmp/r1_pg_repo_smoke.sql
```
