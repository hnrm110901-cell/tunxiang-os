"""v433 — DepartmentIngredientWhitelist 1 表（PRD-08 / Phase 2 W11 / T2 + Tier 1 邻接）

业务背景：
  徐记海鲜后厨分档口 — 早餐档 / 海鲜档 / 热菜档 / 凉菜档 / 卤味档 / 烘焙档。
  现状无白名单约束 → 早餐档员工领取龙虾 / 鲍鱼"串货" → 自己吃或私下出售 →
  毛利漏 3-5% / 月，年级损失数十万。徐记采购总监要求"硬约束"，违反阻塞 + 审计留痕。

  PRD-08 范围：
  - 部门白名单表 + CRUD service + REST endpoints + 矩阵编辑器 UI
  - dept_issue.create_issue_order 集成：领料路径硬阻塞违反白名单
  - auto_deduction.deduct_for_dish/order 集成：BOM 扣料 dept_id opt-in 校验（caller 激活为 follow-up）

设计要点：
  - max_qty_per_day NULL = 不限量（仅校验白名单存在性）— D1 锁定（向后兼容现有流程）
  - is_active=FALSE 即"软禁用"（保留历史记录，校验路径视为不存在白名单）
  - UNIQUE (tenant_id, dept_id, ingredient_id) WHERE is_deleted=FALSE —
    同部门同食材唯一一条 active 白名单
  - 不跨服务 FK（dept_id / ingredient_id 都是逻辑外键，跨服务 FK 是 anti-pattern）
  - RLS 标准模式：tenant_id::text = current_setting('app.tenant_id', true)
  - ENABLE + FORCE + POLICY + WITH CHECK 四联 inline（与 v428/v429/v430/v431/v432 一致）
  - inspector-and-skip 模式（与 v421+ 一致，方便环境重跑）

长期资产：部门-食材使用矩阵 → 后厨员工领料行为画像（异常领料模式识别）

Revision ID: v433_department_ingredient_whitelist
Revises: v432_requisition_template_and_purchase_orders
Create Date: 2026-05-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v433_department_ingredient_whitelist"
down_revision: Union[str, Sequence[str], None] = (
    "v432_requisition_template_and_purchase_orders"
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    # ───── department_ingredient_whitelists 部门白名单 ────────────────────────
    if "department_ingredient_whitelists" not in existing:
        op.execute(
            """
            CREATE TABLE department_ingredient_whitelists (
                id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id           UUID NOT NULL,
                dept_id             UUID NOT NULL,
                ingredient_id       UUID NOT NULL,
                max_qty_per_day     NUMERIC(14,4),
                is_active           BOOLEAN NOT NULL DEFAULT TRUE,
                notes               TEXT,
                created_by          UUID NOT NULL,
                created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                is_deleted          BOOLEAN NOT NULL DEFAULT FALSE,
                CONSTRAINT chk_dept_wl_max_qty_positive
                    CHECK (max_qty_per_day IS NULL OR max_qty_per_day > 0)
            )
            """
        )
        op.execute(
            "ALTER TABLE department_ingredient_whitelists ENABLE ROW LEVEL SECURITY"
        )
        op.execute(
            "ALTER TABLE department_ingredient_whitelists FORCE ROW LEVEL SECURITY"
        )
        op.execute(
            """
            CREATE POLICY department_ingredient_whitelists_tenant_isolation
            ON department_ingredient_whitelists
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
            """
        )
        # 主查询入口：按部门 + 是否启用过滤
        op.execute(
            """
            CREATE INDEX idx_dept_wl_tenant_dept_active
            ON department_ingredient_whitelists (tenant_id, dept_id, is_active)
            WHERE is_deleted = FALSE
            """
        )
        # 反查入口：按食材查"哪些部门可领"
        op.execute(
            """
            CREATE INDEX idx_dept_wl_tenant_ingredient
            ON department_ingredient_whitelists (tenant_id, ingredient_id)
            WHERE is_deleted = FALSE
            """
        )
        # 唯一性：同租户同部门同食材唯一一条 active 白名单
        op.execute(
            """
            CREATE UNIQUE INDEX uq_dept_wl_tenant_dept_ingredient
            ON department_ingredient_whitelists (tenant_id, dept_id, ingredient_id)
            WHERE is_deleted = FALSE
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "department_ingredient_whitelists" in existing:
        op.execute("DROP TABLE department_ingredient_whitelists CASCADE")
