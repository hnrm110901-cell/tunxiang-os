"""v395 — delivery_dispatches & delivery_provider_configs RLS WITH CHECK 修补
[SECURITY][Tier1]

§19 PR #139 独立验证发现 v391_delivery_dispatches RLS 策略漏洞：

  原策略（v391, _enable_rls 内部模板）：
      CREATE POLICY rls_<table>_<action> ON <table>
          AS PERMISSIVE FOR <action> TO PUBLIC
          USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

  漏洞影响（配送调度跨租户污染）：
    PostgreSQL Row Security 中 USING 子句默认仅约束
    SELECT/UPDATE/DELETE 的 *可见性*。INSERT 与 UPDATE 的 *写入侧* 由
    WITH CHECK 子句约束。v391 INSERT/UPDATE/DELETE 三条策略只声明 USING、
    未声明 WITH CHECK，因此任何拿到 db session 的代码可以
    `INSERT INTO delivery_dispatches (..., tenant_id='tenant_B', ...)`
    向其他租户写入虚假调度记录 — 包括伪造骑手位置、伪造送达时间戳、
    污染配送商回调原始 payload 等。

  涉及表（v391 创建）：
    1. delivery_dispatches          — 配送调度主表（订单 → 骑手 → 状态机）
    2. delivery_provider_configs    — 租户/门店/配送商三元组配置（含 app_secret）

修补：
  - 对每张表的 INSERT / UPDATE / DELETE 三条策略：
    DROP 旧策略（PG 不支持 ALTER POLICY 加 WITH CHECK 子句）
    CREATE 新策略 同时声明 USING + WITH CHECK，且条件相同
  - SELECT 策略保持 USING-only（SELECT 无写入侧，WITH CHECK 不适用）
  - WITH CHECK 在 INSERT/UPDATE 时校验目标行 tenant_id 必须等于当前会话
    set_config('app.tenant_id') 的值，否则 PG 返回
    "new row violates row-level security policy for table"

向后兼容：
  - 现有 delivery_dispatch_routes.py 路由层目前为内存实现（_find_configs_for_store
    等使用进程级 dict），尚未走 DB session，因此本修补对现有路由零影响
  - 当未来 service 层接入真实 DB 写入时，调用方必须先
    SET LOCAL app.tenant_id = '<uuid>' 才能 INSERT，等价于 v274 修补 trade_audit_logs
    后 write_audit() 调用路径的契约
  - 新策略对合规读写零行为差异，仅"补漏"

部署约束（CLAUDE.md §17 Tier1 + §21 灰度）：
  - DROP/CREATE POLICY 持表的 ACCESS EXCLUSIVE LOCK，但仅元数据级，毫秒级完成
  - 无数据迁移，pure DDL；可在低峰期窗口直接灰度

Revision ID: v395
Revises: v391_delivery_dispatches
Create Date: 2026-05-04
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v395"
down_revision: Union[str, None] = "v391_delivery_dispatches"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RLS_EXPR = "NULLIF(current_setting('app.tenant_id', true), '')::UUID"

# 受影响表 — v391 创建，本 migration 修补
_TABLES = ("delivery_dispatches", "delivery_provider_configs")

# 写入侧 actions — INSERT/UPDATE/DELETE 必须 USING + WITH CHECK
# SELECT 仅约束可见性，USING-only 即可
_WRITE_ACTIONS = ("INSERT", "UPDATE", "DELETE")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    for table in _TABLES:
        if table not in existing_tables:
            # 父迁移 v391 未应用 — no-op（新环境从头初始化时 v391 应已带最终策略，
            # 但 v391 当前形态未带 WITH CHECK；v395 在 v391 后立即跑就会修齐）
            continue

        # 1. 对每个写入侧 action：DROP 旧策略 + CREATE 同时含 USING + WITH CHECK 的新策略
        for action in _WRITE_ACTIONS:
            old_policy = f"rls_{table}_{action.lower()}"
            new_policy = f"rls_{table}_{action.lower()}_with_check"

            # 先清理（防御幂等：环境上若已先行手动建过新名策略，先清掉）
            op.execute(f"DROP POLICY IF EXISTS {old_policy} ON {table};")
            op.execute(f"DROP POLICY IF EXISTS {new_policy} ON {table};")

            op.execute(
                f"CREATE POLICY {new_policy} ON {table} "
                f"AS PERMISSIVE FOR {action} TO PUBLIC "
                f"USING (tenant_id = {_RLS_EXPR}) "
                f"WITH CHECK (tenant_id = {_RLS_EXPR});"
            )

        # 2. 确保 RLS 仍启用 + FORCE（v391 已开启；防御幂等）
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    for table in _TABLES:
        if table not in existing_tables:
            continue

        # 反向：DROP 新策略，重建 v391 仅 USING 的旧策略形态（保持 down 等价回滚）
        for action in _WRITE_ACTIONS:
            old_policy = f"rls_{table}_{action.lower()}"
            new_policy = f"rls_{table}_{action.lower()}_with_check"

            op.execute(f"DROP POLICY IF EXISTS {new_policy} ON {table};")
            op.execute(f"DROP POLICY IF EXISTS {old_policy} ON {table};")

            op.execute(
                f"CREATE POLICY {old_policy} ON {table} "
                f"AS PERMISSIVE FOR {action} TO PUBLIC "
                f"USING (tenant_id = {_RLS_EXPR});"
            )
