"""[Tier1][SECURITY][T3] v403 — dashboard_pinned 表 + RLS

S4-04 PR2 (issue #291) 把 PR1 in-memory `_PINNED_STORE` dict 持久化到 PG。

PR2.A 范围（本迁移）：
  - 建表 dashboard_pinned（A2UI surface_snapshot + 元数据 + §6 标准列）
  - RLS policy（v395-style USING + WITH CHECK，INSERT/UPDATE/DELETE 写入侧防伪造）
  - 索引 (tenant_id, pinned_at DESC) WHERE is_deleted=FALSE — list 路径高频

不在本 PR（留 PR2.B/C/D）：
  - service 层 _PINNED_STORE → DB swap（pinned_dashboard.py 删 module-level dict）
  - HTTP 路由 /append/list/{pin_id} + main.py 注册
  - web-admin Pin 按钮 + 驾驶舱 Feed 渲染

表 schema：
  - pin_id              UUID PK，gen_random_uuid 默认
  - tenant_id           UUID NOT NULL（RLS 强制）
  - pinner_user_id      UUID NOT NULL（决策留痕）
  - pinned_at           TIMESTAMPTZ DEFAULT NOW()（业务时间）
  - surface_snapshot    JSONB（A2UI v0.8 declaration）
  - source_query_id     VARCHAR(64)，可空
  - source_natural_query TEXT，可空
  - created_at / updated_at / is_deleted（§6 底层基类）

RLS：
  - SELECT       USING-only（SELECT 无写入侧）
  - INSERT/UPDATE/DELETE  USING + WITH CHECK（v395 PR #139 §19 验证修法）

FIFO 20/tenant 上限留 service 层（PR1 既有逻辑直接迁移）。

部署约束（CLAUDE.md §17 Tier1 + §21 灰度）：
  - 新表 + 4 RLS policy，DDL 毫秒级，可在低峰窗口直接灰度
  - 无数据迁移；service 层切换前 _PINNED_STORE 与本表并存（PR2.B 时再删 dict）

Revision ID: v403_dashboard_pinned
Revises: v402
Create Date: 2026-05-08
"""

from typing import Sequence, Union

from alembic import op

revision: str = "v403_dashboard_pinned"
down_revision: Union[str, None] = "v402"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "dashboard_pinned"
_RLS_EXPR = "NULLIF(current_setting('app.tenant_id', true), '')::UUID"

# 写入侧 actions — INSERT/UPDATE/DELETE 必须 USING + WITH CHECK（v395 修法）
_WRITE_ACTIONS = ("INSERT", "UPDATE", "DELETE")


def upgrade() -> None:
    # 1. 建表
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS {_TABLE} (
            pin_id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            pinner_user_id          UUID NOT NULL,
            pinned_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            surface_snapshot        JSONB NOT NULL,
            source_query_id         VARCHAR(64),
            source_natural_query    TEXT,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted              BOOLEAN NOT NULL DEFAULT FALSE
        );
    """)

    # 2. 索引 — list_pins(tenant_id) ORDER BY pinned_at DESC 高频查询
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_{_TABLE}_tenant_pinned_at "
        f"ON {_TABLE} (tenant_id, pinned_at DESC) "
        f"WHERE is_deleted = FALSE;"
    )

    # 3. RLS — ENABLE + FORCE
    op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY;")

    # 4. SELECT 策略 — USING-only
    op.execute(f"DROP POLICY IF EXISTS rls_{_TABLE}_select ON {_TABLE};")
    op.execute(
        f"CREATE POLICY rls_{_TABLE}_select ON {_TABLE} "
        f"AS PERMISSIVE FOR SELECT TO PUBLIC "
        f"USING (tenant_id = {_RLS_EXPR});"
    )

    # 5. INSERT/UPDATE/DELETE 策略 — USING + WITH CHECK（v395 修法，从一开始带 CHECK）
    for action in _WRITE_ACTIONS:
        policy = f"rls_{_TABLE}_{action.lower()}_with_check"
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {_TABLE};")
        op.execute(
            f"CREATE POLICY {policy} ON {_TABLE} "
            f"AS PERMISSIVE FOR {action} TO PUBLIC "
            f"USING (tenant_id = {_RLS_EXPR}) "
            f"WITH CHECK (tenant_id = {_RLS_EXPR});"
        )


def downgrade() -> None:
    # 反向：DROP TABLE 自动级联删 policies + index（CASCADE 风格无需手动 DROP POLICY）
    op.execute(f"DROP TABLE IF EXISTS {_TABLE};")
