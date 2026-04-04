"""v148 — 事件物化视图层 (Event Materialized Views)

Event Sourcing + CQRS 架构升级 Phase 2：
- 创建 8 个物化视图（mv_*），供上层服务和 Agent 直接读取
- 创建投影器游标更新函数
- 每个视图都有 REFRESH 函数（支持从事件流完整重建）

视图列表（对应方案第2.3节）：
  mv_discount_health    — 折扣率/授权链/泄漏类型（因果链①）
  mv_channel_margin     — 各渠道真实到手毛利（因果链②）
  mv_inventory_bom      — BOM理论vs实际耗用差异（因果链③）
  mv_member_clv         — 会员生命周期价值（因果链⑤）
  mv_store_pnl          — 门店实时P&L（因果链④）
  mv_daily_settlement   — 日结状态/差异项（因果链⑦）
  mv_safety_compliance  — 食安检查完成率（新模块⑧）
  mv_energy_efficiency  — 能耗/营收比（新模块⑨）

注意：物化视图初始为空，投影器消费事件后填充。
视图损坏时可通过 rebuild 函数从事件存储完全重建。

Revision: v148
"""

from alembic import op

revision = "v148"
down_revision = "v147"
branch_labels = None
depends_on = None


def upgrade() -> None:

    # ─────────────────────────────────────────────────────────────────
    # mv_discount_health — 折扣健康视图（因果链①）
    # 数据来源：discount.* 事件
    # 消费者：M4 Agent折扣守护、老板报表
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS mv_discount_health (
            tenant_id           UUID        NOT NULL,
            store_id            UUID        NOT NULL,
            stat_date           DATE        NOT NULL,
            total_orders        INT         NOT NULL DEFAULT 0,
            discounted_orders   INT         NOT NULL DEFAULT 0,
            discount_rate       NUMERIC(5,4) NOT NULL DEFAULT 0,  -- 折扣率 0.0-1.0
            total_discount_fen  BIGINT      NOT NULL DEFAULT 0,   -- 总折扣额（分）
            unauthorized_count  INT         NOT NULL DEFAULT 0,   -- 无授权折扣次数
            leak_types          JSONB       NOT NULL DEFAULT '{}', -- 泄漏类型分布
            top_operators       JSONB       NOT NULL DEFAULT '[]', -- TOP折扣操作员
            threshold_breaches  INT         NOT NULL DEFAULT 0,   -- 超阈值次数
            last_event_id       UUID,
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (tenant_id, store_id, stat_date)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mv_discount_health_tenant_date
            ON mv_discount_health (tenant_id, stat_date DESC)
    """)
    op.execute("COMMENT ON TABLE mv_discount_health IS '折扣健康投影视图 — 因果链①'")

    # ─────────────────────────────────────────────────────────────────
    # mv_channel_margin — 渠道真实毛利视图（因果链②）
    # 数据来源：channel.* + order.* 事件
    # 消费者：Agent、财务报表
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS mv_channel_margin (
            tenant_id               UUID        NOT NULL,
            store_id                UUID        NOT NULL,
            stat_date               DATE        NOT NULL,
            channel                 VARCHAR(32) NOT NULL,  -- meituan/eleme/douyin/dine_in
            gross_revenue_fen       BIGINT      NOT NULL DEFAULT 0,  -- 平台成交额
            commission_fen          BIGINT      NOT NULL DEFAULT 0,  -- 平台佣金
            promotion_subsidy_fen   BIGINT      NOT NULL DEFAULT 0,  -- 平台补贴
            net_revenue_fen         BIGINT      NOT NULL DEFAULT 0,  -- 实际到手
            cogs_fen                BIGINT      NOT NULL DEFAULT 0,  -- 食材成本
            gross_margin_fen        BIGINT      NOT NULL DEFAULT 0,  -- 真实毛利
            gross_margin_rate       NUMERIC(5,4) NOT NULL DEFAULT 0, -- 毛利率
            order_count             INT         NOT NULL DEFAULT 0,
            last_event_id           UUID,
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (tenant_id, store_id, stat_date, channel)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mv_channel_margin_tenant_date
            ON mv_channel_margin (tenant_id, stat_date DESC)
    """)
    op.execute("COMMENT ON TABLE mv_channel_margin IS '渠道真实毛利投影视图 — 因果链②'")

    # ─────────────────────────────────────────────────────────────────
    # mv_inventory_bom — 库存BOM差异视图（因果链③）
    # 数据来源：inventory.* + order.submitted 事件
    # 消费者：Agent、后厨管理
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS mv_inventory_bom (
            tenant_id               UUID        NOT NULL,
            store_id                UUID        NOT NULL,
            stat_date               DATE        NOT NULL,
            ingredient_id           UUID        NOT NULL,
            ingredient_name         VARCHAR(128),
            theoretical_usage_g     NUMERIC(10,3) NOT NULL DEFAULT 0,  -- BOM理论耗用(克)
            actual_usage_g          NUMERIC(10,3) NOT NULL DEFAULT 0,  -- 实际出库(克)
            waste_g                 NUMERIC(10,3) NOT NULL DEFAULT 0,  -- 登记损耗(克)
            unexplained_loss_g      NUMERIC(10,3) NOT NULL DEFAULT 0,  -- 未解释差异
            loss_rate               NUMERIC(5,4) NOT NULL DEFAULT 0,   -- 损耗率
            last_event_id           UUID,
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (tenant_id, store_id, stat_date, ingredient_id)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mv_inventory_bom_tenant_date
            ON mv_inventory_bom (tenant_id, stat_date DESC)
    """)
    op.execute("COMMENT ON TABLE mv_inventory_bom IS 'BOM损耗追踪投影视图 — 因果链③'")

    # ─────────────────────────────────────────────────────────────────
    # mv_member_clv — 会员生命周期价值视图（因果链⑤）
    # 数据来源：member.* + order.paid 事件
    # 消费者：Agent会员洞察、营销决策
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS mv_member_clv (
            tenant_id               UUID        NOT NULL,
            customer_id             UUID        NOT NULL,
            total_spend_fen         BIGINT      NOT NULL DEFAULT 0,   -- 累计消费（分）
            visit_count             INT         NOT NULL DEFAULT 0,
            voucher_used_count      INT         NOT NULL DEFAULT 0,
            voucher_cost_fen        BIGINT      NOT NULL DEFAULT 0,   -- 券成本（分）
            stored_value_balance_fen BIGINT     NOT NULL DEFAULT 0,   -- 储值余额
            clv_fen                 BIGINT      NOT NULL DEFAULT 0,   -- 生命周期价值
            churn_probability       NUMERIC(4,3) NOT NULL DEFAULT 0,  -- 流失概率0.0-1.0
            next_visit_days         INT,                               -- 预计下次到店天数
            last_visit_at           TIMESTAMPTZ,
            rfm_segment             VARCHAR(16),                       -- R/F/M分层
            last_event_id           UUID,
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (tenant_id, customer_id)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mv_member_clv_tenant_churn
            ON mv_member_clv (tenant_id, churn_probability DESC)
    """)
    op.execute("COMMENT ON TABLE mv_member_clv IS '会员生命周期价值投影视图 — 因果链⑤'")

    # ─────────────────────────────────────────────────────────────────
    # mv_store_pnl — 门店实时P&L视图（因果链④多品牌P&L）
    # 数据来源：所有流水类事件
    # 消费者：老板仪表盘、Agent
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS mv_store_pnl (
            tenant_id               UUID        NOT NULL,
            brand_id                UUID,
            store_id                UUID        NOT NULL,
            stat_date               DATE        NOT NULL,
            gross_revenue_fen       BIGINT      NOT NULL DEFAULT 0,   -- 总营收
            net_revenue_fen         BIGINT      NOT NULL DEFAULT 0,   -- 净营收（去渠道费）
            cogs_fen                BIGINT      NOT NULL DEFAULT 0,   -- 食材成本
            gross_profit_fen        BIGINT      NOT NULL DEFAULT 0,   -- 毛利润
            gross_margin_rate       NUMERIC(5,4) NOT NULL DEFAULT 0,  -- 毛利率
            labor_cost_fen          BIGINT      NOT NULL DEFAULT 0,   -- 人工成本
            overhead_fen            BIGINT      NOT NULL DEFAULT 0,   -- 其他费用
            net_profit_fen          BIGINT      NOT NULL DEFAULT 0,   -- 净利润
            order_count             INT         NOT NULL DEFAULT 0,
            customer_count          INT         NOT NULL DEFAULT 0,
            avg_check_fen           BIGINT      NOT NULL DEFAULT 0,   -- 客单价
            stored_value_new_fen    BIGINT      NOT NULL DEFAULT 0,   -- 新充值（负债）
            stored_value_consumed_fen BIGINT    NOT NULL DEFAULT 0,   -- 储值消费转收入
            last_event_id           UUID,
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (tenant_id, store_id, stat_date)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mv_store_pnl_tenant_date
            ON mv_store_pnl (tenant_id, stat_date DESC)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mv_store_pnl_brand_date
            ON mv_store_pnl (tenant_id, brand_id, stat_date DESC)
    """)
    op.execute("COMMENT ON TABLE mv_store_pnl IS '门店实时P&L投影视图 — 因果链④'")

    # ─────────────────────────────────────────────────────────────────
    # mv_daily_settlement — 日清日结状态视图（因果链⑦）
    # 数据来源：payment.confirmed + settlement.* 事件
    # 消费者：财务、Agent
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS mv_daily_settlement (
            tenant_id                   UUID        NOT NULL,
            store_id                    UUID        NOT NULL,
            stat_date                   DATE        NOT NULL,
            status                      VARCHAR(32) NOT NULL DEFAULT 'open',
            -- open / pending_reconcile / closed / discrepancy
            cash_declared_fen           BIGINT      NOT NULL DEFAULT 0,
            cash_system_fen             BIGINT      NOT NULL DEFAULT 0,
            cash_discrepancy_fen        BIGINT      NOT NULL DEFAULT 0,
            wechat_received_fen         BIGINT      NOT NULL DEFAULT 0,
            alipay_received_fen         BIGINT      NOT NULL DEFAULT 0,
            card_received_fen           BIGINT      NOT NULL DEFAULT 0,
            stored_value_consumed_fen   BIGINT      NOT NULL DEFAULT 0,
            total_revenue_fen           BIGINT      NOT NULL DEFAULT 0,
            pending_items               JSONB       NOT NULL DEFAULT '[]',  -- 待确认差异列表
            closed_at                   TIMESTAMPTZ,
            closed_by                   UUID,
            last_event_id               UUID,
            updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (tenant_id, store_id, stat_date)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mv_daily_settlement_tenant_date
            ON mv_daily_settlement (tenant_id, stat_date DESC)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mv_daily_settlement_status
            ON mv_daily_settlement (tenant_id, status, stat_date DESC)
    """)
    op.execute("COMMENT ON TABLE mv_daily_settlement IS '日清日结状态投影视图 — 因果链⑦'")

    # ─────────────────────────────────────────────────────────────────
    # mv_safety_compliance — 食安合规视图（新模块⑧）
    # 数据来源：safety.* 事件
    # 消费者：管理后台、Agent
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS mv_safety_compliance (
            tenant_id                   UUID        NOT NULL,
            store_id                    UUID        NOT NULL,
            stat_week                   DATE        NOT NULL,  -- ISO周开始日期（周一）
            sample_logged_count         INT         NOT NULL DEFAULT 0,   -- 留样记录数
            inspection_required         INT         NOT NULL DEFAULT 0,   -- 应检查项
            inspection_done             INT         NOT NULL DEFAULT 0,   -- 已完成检查
            inspection_rate             NUMERIC(4,3) NOT NULL DEFAULT 0,  -- 检查完成率
            violation_count             INT         NOT NULL DEFAULT 0,   -- 违规次数
            expiry_alerts               JSONB       NOT NULL DEFAULT '[]', -- 临期/过期明细
            overdue_certificates        JSONB       NOT NULL DEFAULT '[]', -- 过期证件
            compliance_score            INT         NOT NULL DEFAULT 100,  -- 合规评分0-100
            last_event_id               UUID,
            updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (tenant_id, store_id, stat_week)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mv_safety_compliance_tenant_week
            ON mv_safety_compliance (tenant_id, stat_week DESC)
    """)
    op.execute("COMMENT ON TABLE mv_safety_compliance IS '食安合规投影视图 — 法律义务'")

    # ─────────────────────────────────────────────────────────────────
    # mv_energy_efficiency — 能耗效率视图（新模块⑨）
    # 数据来源：energy.* 事件（IoT传感器）
    # 消费者：管理后台、Agent
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS mv_energy_efficiency (
            tenant_id                   UUID        NOT NULL,
            store_id                    UUID        NOT NULL,
            stat_date                   DATE        NOT NULL,
            electricity_kwh             NUMERIC(10,3) NOT NULL DEFAULT 0,
            gas_m3                      NUMERIC(10,3) NOT NULL DEFAULT 0,
            water_ton                   NUMERIC(10,3) NOT NULL DEFAULT 0,
            energy_cost_fen             BIGINT      NOT NULL DEFAULT 0,
            revenue_fen                 BIGINT      NOT NULL DEFAULT 0,
            energy_revenue_ratio        NUMERIC(5,4) NOT NULL DEFAULT 0,  -- 能耗/营收比
            anomaly_count               INT         NOT NULL DEFAULT 0,
            off_hours_anomalies         JSONB       NOT NULL DEFAULT '[]', -- 非营业时段异常
            last_event_id               UUID,
            updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (tenant_id, store_id, stat_date)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mv_energy_efficiency_tenant_date
            ON mv_energy_efficiency (tenant_id, stat_date DESC)
    """)
    op.execute("COMMENT ON TABLE mv_energy_efficiency IS '能耗效率投影视图 — IoT数据'")

    # ─────────────────────────────────────────────────────────────────
    # 投影器刷新锁表（防止并发重建视图冲突）
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS projector_rebuild_locks (
            projector_name  VARCHAR(64)     NOT NULL PRIMARY KEY,
            locked_at       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            locked_by       VARCHAR(128),
            expires_at      TIMESTAMPTZ     NOT NULL
        )
    """)


def downgrade() -> None:
    for view in [
        "mv_discount_health",
        "mv_channel_margin",
        "mv_inventory_bom",
        "mv_member_clv",
        "mv_store_pnl",
        "mv_daily_settlement",
        "mv_safety_compliance",
        "mv_energy_efficiency",
        "projector_rebuild_locks",
    ]:
        op.execute(f"DROP TABLE IF EXISTS {view}")
