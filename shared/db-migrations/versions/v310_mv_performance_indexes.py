"""v310: 物化视图性能索引优化（Task 3.3 / P1-06）

为 8 个物化视图新增查询优化索引，目标：查询性能提升 50%+
覆盖: mv_discount_health, mv_channel_margin, mv_inventory_bom,
       mv_member_clv, mv_store_pnl, mv_daily_settlement,
       mv_safety_compliance, mv_energy_efficiency

索引策略:
  - 组合索引 (tenant_id, store_id, date) — 覆盖 90% 查询
  - 部分索引 — 仅索引活跃行，减少索引体积
  - BRIN 索引 — 大表日期列，节省空间

Revision ID: v310
Revises: v301_refund_requests
Create Date: 2026-05-02
"""

from alembic import op

revision = "v310"
down_revision = "v301_refund_requests"
branch_labels = None
depends_on = None


def upgrade():
    # ── mv_daily_settlement: 日结查询最频繁 ──
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mv_ds_tenant_store_date
        ON mv_daily_settlement (tenant_id, store_id, settlement_date DESC);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mv_ds_tenant_date
        ON mv_daily_settlement (tenant_id, settlement_date DESC);
    """)

    # ── mv_store_pnl: 门店损益按周期查询 ──
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mv_pnl_tenant_store_period
        ON mv_store_pnl (tenant_id, store_id, period_start DESC, period_end DESC);
    """)

    # ── mv_discount_health: 折扣审计高频查询 ──
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mv_dh_tenant_store_date
        ON mv_discount_health (tenant_id, store_id, event_date DESC);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mv_dh_tenant_date_severity
        ON mv_discount_health (tenant_id, event_date DESC, severity)
        WHERE severity IN ('high', 'critical');
    """)

    # ── mv_channel_margin: 渠道毛利分析 ──
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mv_cm_tenant_store_channel
        ON mv_channel_margin (tenant_id, store_id, channel, report_date DESC);
    """)

    # ── mv_member_clv: 会员生命周期价值 ──
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mv_mclv_tenant_store
        ON mv_member_clv (tenant_id, store_id, clv_tier);
    """)

    # ── mv_inventory_bom: 库存BOM查询 ──
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mv_ib_tenant_store_ingredient
        ON mv_inventory_bom (tenant_id, store_id, ingredient_id);
    """)

    # ── mv_safety_compliance: 食安合规 ──
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mv_sc_tenant_store_date
        ON mv_safety_compliance (tenant_id, store_id, inspection_date DESC);
    """)

    # ── mv_energy_efficiency: 能耗效率 ──
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mv_ee_tenant_store_date
        ON mv_energy_efficiency (tenant_id, store_id, reading_date DESC);
    """)

    # ── events 表 BRIN 索引（时序数据，节省 90% 空间 vs B-tree）──
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_events_occurred_at_brin
        ON events USING BRIN (occurred_at)
        WITH (pages_per_range = 32);
    """)

    # ── profit_split_records 查询加速 ──
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_psr_tenant_status
        ON profit_split_records (tenant_id, status, created_at DESC);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_psr_tenant_recipient
        ON profit_split_records (tenant_id, recipient_type, recipient_id);
    """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_mv_ds_tenant_store_date;")
    op.execute("DROP INDEX IF EXISTS idx_mv_ds_tenant_date;")
    op.execute("DROP INDEX IF EXISTS idx_mv_pnl_tenant_store_period;")
    op.execute("DROP INDEX IF EXISTS idx_mv_dh_tenant_store_date;")
    op.execute("DROP INDEX IF EXISTS idx_mv_dh_tenant_date_severity;")
    op.execute("DROP INDEX IF EXISTS idx_mv_cm_tenant_store_channel;")
    op.execute("DROP INDEX IF EXISTS idx_mv_mclv_tenant_store;")
    op.execute("DROP INDEX IF EXISTS idx_mv_ib_tenant_store_ingredient;")
    op.execute("DROP INDEX IF EXISTS idx_mv_sc_tenant_store_date;")
    op.execute("DROP INDEX IF EXISTS idx_mv_ee_tenant_store_date;")
    op.execute("DROP INDEX IF EXISTS idx_events_occurred_at_brin;")
    op.execute("DROP INDEX IF EXISTS idx_psr_tenant_status;")
    op.execute("DROP INDEX IF EXISTS idx_psr_tenant_recipient;")
