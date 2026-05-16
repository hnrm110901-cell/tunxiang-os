"""v438 — cost_attribution_summary 汇总表 (PRD-11 sub-C / Phase 2 W12 收口)

业务背景:
  PRD-11 sub-A (v434 share_split_rules) 配置层 ✅
  PRD-11 sub-B (v436 OrderItem.share_count + ITEMS_SETTLED emit) ✅
  PRD-11 sub-B.2 (v437 tx-supply IndexSplitProjector + dlq_split_attribution_failed) ✅
  本 PR (sub-C) — tx-analytics SplitAttributionProjector 消费 inventory.split_attributed
  事件, 把每次成功分摊的 share / BOM / order_item 信息汇总到本表; cost attribution
  dashboard 直接读本表渲染单订单 / 单菜 / 时段三层视图.

设计要点:
  - source_event_id UNIQUE per tenant 保 projector 重放幂等 (与 v437 dlq 表 event_id
    一致语义, 但本表是 attribution 成功路径的归集, 而非死信)
  - shares JSONB 存 attribute 的明细数组 (share_index/weight/attributed_cost_fen),
    sub-C 看板需要逐 share 渲染时直接读出
  - bom_cost_total_fen BIGINT 单位"分" (与 §15 / share_split_service apply_split 返回
    类型一致), 严禁 float
  - RLS 四联 (ENABLE + FORCE + POLICY + WITH CHECK), 与 v434/v435/v437 一致
  - inspector-and-skip 模式 (与 v421+ 一致, idempotent 防 dry-run 重跑)
  - 索引: (tenant_id, occurred_at DESC) 主查询入口 (时段总览倒序);
            (tenant_id, order_id) 单订单视图入口;
            (tenant_id, dish_id) 单菜分布入口

Revision ID: v438_cost_attribution_summary
Revises: v437_ingredient_split_attribution_dedup
Create Date: 2026-05-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v438_cost_attribution_summary"
down_revision: Union[str, Sequence[str], None] = "v437_ingredient_split_attribution_dedup"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "cost_attribution_summary" not in existing_tables:
        op.execute(
            """
            CREATE TABLE cost_attribution_summary (
                id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id            UUID NOT NULL,
                source_event_id      UUID NOT NULL,
                order_id             UUID,
                order_item_id        UUID,
                dish_id              UUID,
                method               VARCHAR(40) NOT NULL,
                share_count          INTEGER NOT NULL,
                bom_cost_total_fen   BIGINT NOT NULL,
                shares               JSONB NOT NULL,
                occurred_at          TIMESTAMPTZ NOT NULL,
                created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        # F2 dedup — projector 重放同一 event 第二条 INSERT 命中 IntegrityError
        op.execute(
            """
            CREATE UNIQUE INDEX uq_cost_attribution_summary_tenant_source_event
            ON cost_attribution_summary (tenant_id, source_event_id)
            """
        )
        op.execute("ALTER TABLE cost_attribution_summary ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE cost_attribution_summary FORCE ROW LEVEL SECURITY")
        op.execute(
            """
            CREATE POLICY cost_attribution_summary_tenant_isolation
            ON cost_attribution_summary
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
            """
        )
        # 时段总览入口 (sub-C dashboard 时段筛选倒序展示)
        op.execute(
            """
            CREATE INDEX idx_cost_attribution_summary_tenant_occurred
            ON cost_attribution_summary (tenant_id, occurred_at DESC)
            """
        )
        # 单订单视图入口 (GET /cost-attribution/orders/{order_id})
        op.execute(
            """
            CREATE INDEX idx_cost_attribution_summary_tenant_order
            ON cost_attribution_summary (tenant_id, order_id)
            WHERE order_id IS NOT NULL
            """
        )
        # 单菜分布入口 (GET /cost-attribution/dishes/{dish_id}/summary)
        op.execute(
            """
            CREATE INDEX idx_cost_attribution_summary_tenant_dish
            ON cost_attribution_summary (tenant_id, dish_id)
            WHERE dish_id IS NOT NULL
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "cost_attribution_summary" in existing_tables:
        op.execute("DROP TABLE cost_attribution_summary CASCADE")
