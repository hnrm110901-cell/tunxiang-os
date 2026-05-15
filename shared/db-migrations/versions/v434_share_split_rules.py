"""v434 — ShareSplitRule 1 表（PRD-11 sub-A / Phase 2 W11 / T2 + Tier 1 邻接）

业务背景：
  徐记海鲜实际场景 — 一桌客人合点 1 份酸菜鱼(¥98)分给 2-4 人吃，POS 端可"拆单付款"
  (self_pay_router.split_count 已存在)，但**库存成本归属侧**没有对应:
  - 销售报表: 每人 0.25 份 → 客单价分母正确, 但成本归属还是 1 份 / 1 人
  - 会员 CLV: 张三只占 0.25 份 BOM 成本, 而非全份 (大幅影响 RFM 模型)
  - 跨部门成本归集: 西餐厅区 vs 中餐厅区共享菜品的成本切分基线

  PRD-11 范围 (sub-A 配置层 + auto_deduction opt-in gate):
  - share_split_rules 表 — 每个 dish 可配置: 允许分享 / 默认分享方法 / 上限人数
  - share_split_service.py CRUD + resolve_split helper (3-way enum: even/weighted/manual)
  - auto_deduction.deduct_for_dish/order 加 share_split opt-in 参数,
    caller (PR-B tx-trade) 提供时 emit inventory.split_attributed event 携 cost 分配
  - 物理 BOM 扣料**不变** (1 dish 仍消耗 1 份 BOM, 只是 cost 分摊到多 share)
  - sub-B / sub-C 在后续 PR (tx-trade OrderItem.share_count Tier 1 第 29 例 +
    tx-analytics report + POS UI)

设计要点：
  - dish_id 是逻辑外键 (跨服务不加 FK 约束, 与 v432 purchase_orders 同模式)
  - UNIQUE (tenant_id, dish_id) WHERE is_deleted=FALSE — 同 dish 一条 active rule
  - allow_share=FALSE 即"明确禁止分享" (例: 单人套餐, 不允许多人合点)
  - default_method enum: even / weighted / manual (caller 可覆盖)
  - max_share_count NULL = 不限人数, 非 NULL = 最大可分享人数 (业务上限, 防极端拆分)
  - RLS 标准模式: ENABLE + FORCE + POLICY + WITH CHECK 四联
  - inspector-and-skip 模式 (与 v421+ 一致)

长期资产: 多人合点行为画像 → AI 推荐"是否拆单" + 客单价精算

Revision ID: v434_share_split_rules
Revises: v433_department_ingredient_whitelist
Create Date: 2026-05-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v434_share_split_rules"
down_revision: Union[str, Sequence[str], None] = "v433_department_ingredient_whitelist"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "share_split_rules" not in existing:
        op.execute(
            """
            CREATE TABLE share_split_rules (
                id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id           UUID NOT NULL,
                dish_id             UUID NOT NULL,
                allow_share         BOOLEAN NOT NULL DEFAULT TRUE,
                default_method      VARCHAR(20) NOT NULL DEFAULT 'even',
                max_share_count     INTEGER,
                is_active           BOOLEAN NOT NULL DEFAULT TRUE,
                notes               TEXT,
                created_by          UUID NOT NULL,
                created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                is_deleted          BOOLEAN NOT NULL DEFAULT FALSE,
                CONSTRAINT chk_share_split_rules_method
                    CHECK (default_method IN ('even','weighted','manual')),
                CONSTRAINT chk_share_split_rules_max_share_positive
                    CHECK (max_share_count IS NULL OR max_share_count >= 2)
            )
            """
        )
        op.execute("ALTER TABLE share_split_rules ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE share_split_rules FORCE ROW LEVEL SECURITY")
        op.execute(
            """
            CREATE POLICY share_split_rules_tenant_isolation
            ON share_split_rules
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
            """
        )
        # 主查询入口: dish_id + is_active
        op.execute(
            """
            CREATE INDEX idx_share_split_rules_tenant_dish_active
            ON share_split_rules (tenant_id, dish_id, is_active)
            WHERE is_deleted = FALSE
            """
        )
        # 唯一性: 同租户同 dish 唯一一条 active 规则
        op.execute(
            """
            CREATE UNIQUE INDEX uq_share_split_rules_tenant_dish
            ON share_split_rules (tenant_id, dish_id)
            WHERE is_deleted = FALSE
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "share_split_rules" in existing:
        op.execute("DROP TABLE share_split_rules CASCADE")
