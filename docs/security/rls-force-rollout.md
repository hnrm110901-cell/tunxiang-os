# RLS FORCE 全表回填 + BYPASSRLS 撤销 — 上线计划

**对应审计项**：[S-05](../audit-2026-05/01-security.md#s-05) — RLS 在 BYPASSRLS + 缺 FORCE 下失效（P0）
**估时**：5 个工作日（含 staging canary）
**风险**：高 — 错误执行将导致生产 app 全量查询返回 0 行

---

## 背景

审计发现：
1. `shared/ontology/src/database.py:81-82` 注释建议给 app role `GRANT BYPASSRLS`（部署 GRANT 是否真执行需在 staging 验证）
2. ~176 张表 `ENABLE ROW LEVEL SECURITY` 但缺 `FORCE`
3. 部分历史策略（v117_finance_engine 等）仅 `USING (...)` 没 `WITH CHECK (...)` — **此项已由 v399/v400/v401/v402 修补**

**FORCE 的作用**：即便 app role 持 BYPASSRLS（或会话内 `SET LOCAL row_security = off`），FORCE RLS 仍然强制策略生效。这是多租户安全的最后一道防线。

**风险根源**：当前任何能调 `get_db_no_rls()` 的代码（已知 5 处：gateway hub_api、tx-trade banquet_payment_routes、wechat_pay_notify_service、tx-analytics seed_loader、tx-brain brain_routes）都能跨租户读写。如果 GRANT 真应用了，**单个被攻陷的 service pod 可读 / 写所有租户的所有业务表**。

---

## 修复策略（5 阶段）

### 阶段 1（D1）：CI 防止新增违规 — ✅ 已完成

**已交付**（本审计修复批次）：
- `.github/workflows/rls-gate.yml` 增加 FORCE ROW LEVEL SECURITY 静态检查
- 新 migration 必须为每张 ENABLE RLS 的表同时加 FORCE，否则 PR fail

**验证方式**：开 PR 加一张新表 + ENABLE RLS 不加 FORCE，应触发 CI 红。

### 阶段 2（D1-D2）：staging dry-run 评估影响

```sql
-- 在 staging DB 跑：列出所有 ENABLE 但未 FORCE 的业务表
SELECT
    schemaname,
    tablename,
    rowsecurity AS enabled,
    forcerowsecurity AS forced
FROM pg_tables
WHERE schemaname = 'public'
  AND rowsecurity = true
  AND forcerowsecurity = false
ORDER BY tablename;
```

**预期结果**：约 176 张表。逐张确认是否：
- 需要 BYPASSRLS 路径（finance reports / agent cross-tenant aggregation）
- 是否能依赖 SET LOCAL row_security = off + FORCE 后会失效

**关键测试**：在 staging 给 1 张非关键表（如 `audit_logs`）单独加 FORCE，跑 e2e 套件 + Tier 1 测试，观察是否有路径回 0 行。

### 阶段 3（D2-D3）：生成 retroactive FORCE migration

```python
# shared/db-migrations/versions/vNNN_rls_force_all_business_tables.py
"""vNNN — 给所有 ENABLE RLS 的业务表追加 FORCE [SECURITY][Tier1]

审计 S-05 修复阶段 3：消除 BYPASSRLS-via-SET-LOCAL 绕过路径。

EXEMPT 表（与 rls-gate.yml + tests/tier1/test_rls_all_tables_tier1.py 同步）：
  events / mv_* / partitions / system_config / refresh_tokens / sync_checkpoints
  device_registry / franchise_audits / 共享配置表

升级前必须做：
  1. staging dry-run 全 e2e 套件 + tier1 100% 通过
  2. 手工确认 5 处 get_db_no_rls() 调用方在 FORCE 后仍可工作（需迁到 SET ROLE 或新角色）
  3. 灰度发布：一店 → 一品牌 → 全量
"""

from alembic import op

# 与 rls-gate.yml 同步
EXEMPT = (
    "alembic_version", "events", "events_default",
    "projector_checkpoints", "projector_rebuild_locks",
    # ... 见 rls-gate.yml 完整列表
)

def upgrade() -> None:
    op.execute(f"""
        DO $$
        DECLARE
            t record;
        BEGIN
            FOR t IN
                SELECT tablename
                FROM pg_tables
                WHERE schemaname = 'public'
                  AND rowsecurity = true
                  AND forcerowsecurity = false
                  AND tablename NOT IN (
                      {', '.join(repr(e) for e in EXEMPT)}
                  )
                  AND tablename NOT LIKE 'mv_%'
                  AND tablename NOT LIKE 'events_2%'
            LOOP
                EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t.tablename);
            END LOOP;
        END $$;
    """)

def downgrade() -> None:
    # 危险：批量降级，手工逐表评估
    op.execute("""
        DO $$
        DECLARE
            t record;
        BEGIN
            FOR t IN
                SELECT tablename FROM pg_tables
                WHERE schemaname = 'public' AND forcerowsecurity = true
            LOOP
                EXECUTE format('ALTER TABLE %I NO FORCE ROW LEVEL SECURITY', t.tablename);
            END LOOP;
        END $$;
    """)
```

### 阶段 4（D3-D4）：撤 BYPASSRLS + 引入 tx_system_role — ✅ 已落代码

**已交付**（独立 PR `audit/p0-followup-rls-stage-4-bypassrls`，DO NOT MERGE pending staging dry-run）：

- `shared/ontology/src/database.py` `get_db_no_rls()` 改造为**双模式 env-driven**：
  - 默认（`RLS_USE_TX_SYSTEM_ROLE` 未设/false）→ 模式 A `SET LOCAL row_security = off`（向后兼容）
  - `RLS_USE_TX_SYSTEM_ROLE=true` → 模式 B `SET LOCAL ROLE tx_system_role`
- `scripts/db/create_tx_system_role.sql` — DBA 部署脚本（NOINHERIT + NOLOGIN + BYPASSRLS + GRANT TO tunxiang + 默认表权限）
- `scripts/db/revoke_tunxiang_bypassrls.sql` — 阶段 5 cutover 收尾脚本
- `tests/tier1/test_get_db_no_rls_role_switching_tier1.py` — 27 个 Tier 1 测试覆盖双模式 SQL 生成 + finally 清理 + 异常路径 + env 解析

部署 4 步无破坏切换：
1. 部署应用代码（默认模式 A，无变化）
2. DBA 跑 `create_tx_system_role.sql`（创建角色但不撤主角色 BYPASSRLS）
3. 灰度 pod 设 `RLS_USE_TX_SYSTEM_ROLE=true`，验证 5 处合法调用方仍工作
4. 全量 pod 切 → 阶段 5 撤 BYPASSRLS

#### 4.1 创建专用系统角色

```sql
-- 不通过 alembic（DBA 操作）
CREATE ROLE tx_system_role NOINHERIT NOLOGIN;
GRANT BYPASSRLS ON ROLE tx_system_role TO tx_system_role;

-- 应用角色保留普通权限，但被允许 SET ROLE 到系统角色
GRANT tx_system_role TO tunxiang;

-- 撤销主角色的 BYPASSRLS
ALTER ROLE tunxiang NOBYPASSRLS;
```

#### 4.2 改 `shared/ontology/src/database.py`

```python
@asynccontextmanager
async def get_db_no_rls():
    """跨租户 session — 仅 5 处合法用例（见 docstring）。

    审计 S-05 修复：从 SET LOCAL row_security = off 切换到 SET ROLE tx_system_role。
    后者只能在显式授予的会话生效，而非整个角色都默认 BYPASSRLS。
    """
    async with async_session_factory() as session:
        try:
            await session.execute(text("SET LOCAL ROLE tx_system_role"))
            yield session
        finally:
            await session.execute(text("RESET ROLE"))
```

#### 4.3 测试

新增 `tests/tier1/test_rls_force_no_bypass_tier1.py`：
1. 主角色直查 banquet_deposits → 必须返 0 行（FORCE 生效 + 无 BYPASSRLS）
2. `get_db_no_rls()` 内查询 → 返全部行（SET ROLE 生效）
3. 非 `get_db_no_rls()` 路径调 `SET LOCAL row_security = off` → 应失败（不再有 BYPASSRLS）

### 阶段 5（D4-D5）：灰度发布

| 阶段 | 范围 | 监控 | 回滚阈值 |
|---|---|---|---|
| Canary 1 | demo 环境 | rls_query_total / RLS-related 5xx | 任何业务回归 |
| Canary 2 | 1 个真实门店（尝在一起 文化城店）| 4 小时内 0 异常订单 | RLS-related 错误 > 0 |
| Canary 3 | 整个尝在一起品牌 | 24 小时无 5xx 增加 | RLS 错误 > 0 |
| Full | 全部 3 品牌 | 持续 48 小时观察 | — |

---

## 不修则会怎样

[审计 01-security.md S-05 原文](../audit-2026-05/01-security.md#s-05)：
> **多租户灾难性。跨品牌财务泄漏（PNL、成本、营收）就在 Tier 1 表上；与 S-02 叠加，无纵深防御。**

具体场景：
1. 内部员工误操作 / 凭据泄漏 → 直接拉到任意品牌的销售/会员数据
2. 任一服务被 RCE → 横向爬全平台数据
3. v399/v400/v401/v402 已修的 WITH CHECK 仅在策略生效时有用；FORCE 缺失时策略本身被绕过 → WITH CHECK 形同虚设

---

## 已知调用 `get_db_no_rls()` 的代码（迁移前必须确认每处）

来自 `shared/ontology/src/database.py:84-86` docstring：

| 服务 | 文件 | 用途 | 迁移注意 |
|---|---|---|---|
| gateway | hub_api | 跨租户 hub API | 用 SET ROLE 替换 |
| tx-trade | banquet_payment_routes | 微信回调跨租户查 tenant | 已修签名验证（S-04），可继续用 SET ROLE |
| tx-trade | wechat_pay_notify_service | 按 out_trade_no 跨租户查订单 | 同上 |
| tx-analytics | seed_loader | 初始化数据导入 | 启动期一次性，可用 SET ROLE |
| tx-brain | brain_routes | 跨租户聚合视图 | 优先：改读 mv_* 物化视图，避免 bypass 需求 |

---

## 验收标准

修复完成的判定（**全部 ✅**）：

- [ ] `pg_tables.forcerowsecurity = true` 覆盖所有非 EXEMPT 业务表（≥ 425 张）
- [ ] `pg_roles.rolbypassrls = true` 仅 `tx_system_role`（不含 `tunxiang` / 任何 app 角色）
- [ ] `tests/tier1/test_rls_force_no_bypass_tier1.py` 通过
- [ ] 灰度 24h 后 RLS-related 5xx = 0
- [ ] `scripts/check_rls_policies.py --strict` 退出 0
- [ ] `.github/workflows/rls-gate.yml` 拒任何 ENABLE-without-FORCE 的新 migration（已交付）
