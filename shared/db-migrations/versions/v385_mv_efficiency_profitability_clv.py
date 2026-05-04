"""v385 — 物化视图扩展：翻台率/菜品盈利/人效/客户LTV（Phase 3）

Event Sourcing + CQRS Phase 3 核心迁移：
- 创建 4 个新物化视图，补齐 G9 差距：
  mv_table_turnover       — 翻台率（客流量/桌数/翻台次数，因果链④扩展）
  mv_dish_profitability   — 菜品维度的真实盈利（BOM 成本+渠道费用分摊）
  mv_employee_efficiency  — 人效指标（人效贡献/出勤率/效能指数）
  mv_customer_ltv         — 客户生命周期价值（累消费/到店频次/流失风险）
- 添加 RLS 安全策略（FORCE ROW LEVEL SECURITY）
- 创建配套的唯一索引和统计索引

Revision: v385
Down revision: v384
"""

from alembic import op

revision = "v385"
down_revision = "v384"
branch_labels = None
depends_on = None


def upgrade() -> None:

    # ─────────────────────────────────────────────────────────────────
    # mv_table_turnover — 翻台率视图（因果链④扩展）
    # 数据来源：order.* + table_session.* 事件
    # 消费者：M5 Agent出餐调度、店长报表
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS mv_table_turnover (
            tenant_id           UUID        NOT NULL,
            store_id            UUID        NOT NULL,
            stat_date           DATE        NOT NULL,
            stat_hour           INT         NOT NULL DEFAULT 0,  -- 小时(0-23)，0=全天汇总
            total_tables        INT         NOT NULL DEFAULT 0,  -- 门店桌台总数
            occupied_tables     INT         NOT NULL DEFAULT 0,  -- 当前占用桌数
            turnover_count      INT         NOT NULL DEFAULT 0,  -- 翻台次数
            avg_occupancy_mins  INT         NOT NULL DEFAULT 0,  -- 平均每桌占用时长（分钟）
            peak_hour_tables    INT         NOT NULL DEFAULT 0,  -- 高峰期占用桌数
            avg_party_size      NUMERIC(6,2) NOT NULL DEFAULT 0, -- 平均每桌人数
            revenue_per_table_fen BIGINT   NOT NULL DEFAULT 0,  -- 桌均营收（分）
            table_utilization_rate NUMERIC(5,4) NOT NULL DEFAULT 0, -- 桌台利用率
            last_event_id       UUID,
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (tenant_id, store_id, stat_date, stat_hour)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mv_table_turnover_tenant_date
            ON mv_table_turnover (tenant_id, stat_date DESC)
    """)
    op.execute("""ALTER TABLE mv_table_turnover ENABLE ROW LEVEL SECURITY""")
    op.execute("""ALTER TABLE mv_table_turnover FORCE ROW LEVEL SECURITY""")
    op.execute("""
        CREATE POLICY mv_table_turnover_policy ON mv_table_turnover
            FOR ALL USING (tenant_id = (current_setting('app.tenant_id', true))::uuid)
            WITH CHECK (tenant_id = (current_setting('app.tenant_id', true))::uuid)
    """)
    op.execute("COMMENT ON TABLE mv_table_turnover IS '翻台率投影视图 — 因果链④扩展'")

    # ─────────────────────────────────────────────────────────────────
    # mv_dish_profitability — 菜品盈利视图
    # 数据来源：order.* + menu.* + channel.* 事件
    # 消费者：M2 Agent智能排菜、菜品定价报告
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS mv_dish_profitability (
            tenant_id           UUID        NOT NULL,
            store_id            UUID        NOT NULL,
            dish_id             UUID        NOT NULL,
            stat_date           DATE        NOT NULL,
            dish_name           VARCHAR(128) NOT NULL DEFAULT '',
            category            VARCHAR(64)  NOT NULL DEFAULT '',
            order_count         INT         NOT NULL DEFAULT 0,  -- 下单份数
            gross_revenue_fen   BIGINT      NOT NULL DEFAULT 0,  -- 菜品毛收入
            discount_fen        BIGINT      NOT NULL DEFAULT 0,  -- 折扣金额
            net_revenue_fen     BIGINT      NOT NULL DEFAULT 0,  -- 折后收入
            bom_cost_fen        BIGINT      NOT NULL DEFAULT 0,  -- BOM食材成本
            channel_fee_fen     BIGINT      NOT NULL DEFAULT 0,  -- 渠道费用分摊
            gross_margin_fen    BIGINT      NOT NULL DEFAULT 0,  -- 菜品毛利
            gross_margin_rate   NUMERIC(5,4) NOT NULL DEFAULT 0, -- 毛利率
            profitability_rank  INT         NOT NULL DEFAULT 0,  -- 盈利排名（同类中）
            popularity_rank     INT         NOT NULL DEFAULT 0,  -- 热度排名
            recommendation_score NUMERIC(5,2) NOT NULL DEFAULT 0, -- 综合推荐分
            last_event_id       UUID,
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (tenant_id, store_id, dish_id, stat_date)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mv_dish_profitability_tenant_date
            ON mv_dish_profitability (tenant_id, stat_date DESC)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mv_dish_profitability_margin
            ON mv_dish_profitability (tenant_id, store_id, gross_margin_rate)
    """)
    op.execute("""ALTER TABLE mv_dish_profitability ENABLE ROW LEVEL SECURITY""")
    op.execute("""ALTER TABLE mv_dish_profitability FORCE ROW LEVEL SECURITY""")
    op.execute("""
        CREATE POLICY mv_dish_profitability_policy ON mv_dish_profitability
            FOR ALL USING (tenant_id = (current_setting('app.tenant_id', true))::uuid)
            WITH CHECK (tenant_id = (current_setting('app.tenant_id', true))::uuid)
    """)
    op.execute("COMMENT ON TABLE mv_dish_profitability IS '菜品盈利投影视图'")

    # ─────────────────────────────────────────────────────────────────
    # mv_employee_efficiency — 人效视图
    # 数据来源：order.* + shift.* + scheduling.* 事件
    # 消费者：M7 Agent巡店质检、店长KPI
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS mv_employee_efficiency (
            tenant_id           UUID        NOT NULL,
            store_id            UUID        NOT NULL,
            employee_id         UUID        NOT NULL,
            stat_date           DATE        NOT NULL,
            employee_name       VARCHAR(64)  NOT NULL DEFAULT '',
            role_type           VARCHAR(32)  NOT NULL DEFAULT '', -- chef/waiter/cashier/manager
            shift_hours         NUMERIC(5,2) NOT NULL DEFAULT 0,  -- 出勤时长（小时）
            orders_handled      INT         NOT NULL DEFAULT 0,   -- 经手订单数
            revenue_contributed_fen BIGINT  NOT NULL DEFAULT 0,   -- 贡献营收（分）
            avg_service_time_sec INT        NOT NULL DEFAULT 0,   -- 平均服务时长（秒）
            tips_fen            BIGINT      NOT NULL DEFAULT 0,   -- 小费/打赏
            efficiency_score    NUMERIC(5,2) NOT NULL DEFAULT 0,  -- 综合效能分
            attendance_score    NUMERIC(5,2) NOT NULL DEFAULT 0,  -- 出勤评分
            error_incidents     INT         NOT NULL DEFAULT 0,   -- 差错次数
            last_event_id       UUID,
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (tenant_id, store_id, employee_id, stat_date)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mv_employee_efficiency_tenant_date
            ON mv_employee_efficiency (tenant_id, stat_date DESC)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mv_employee_efficiency_score
            ON mv_employee_efficiency (tenant_id, store_id, efficiency_score DESC)
    """)
    op.execute("""ALTER TABLE mv_employee_efficiency ENABLE ROW LEVEL SECURITY""")
    op.execute("""ALTER TABLE mv_employee_efficiency FORCE ROW LEVEL SECURITY""")
    op.execute("""
        CREATE POLICY mv_employee_efficiency_policy ON mv_employee_efficiency
            FOR ALL USING (tenant_id = (current_setting('app.tenant_id', true))::uuid)
            WITH CHECK (tenant_id = (current_setting('app.tenant_id', true))::uuid)
    """)
    op.execute("COMMENT ON TABLE mv_employee_efficiency IS '人效指标投影视图'")

    # ─────────────────────────────────────────────────────────────────
    # mv_customer_ltv — 客户生命周期价值视图
    # 数据来源：order.* + member.* 事件
    # 消费者：M4 Agent会员洞察、CRM报表
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS mv_customer_ltv (
            tenant_id           UUID        NOT NULL,
            customer_id         UUID        NOT NULL,
            customer_name       VARCHAR(64)  NOT NULL DEFAULT '',
            member_level        VARCHAR(32)  NOT NULL DEFAULT 'regular',
            first_order_date    DATE,
            last_order_date     DATE,
            total_orders        INT         NOT NULL DEFAULT 0,
            total_spent_fen     BIGINT      NOT NULL DEFAULT 0,  -- 总消费（分）
            avg_order_value_fen BIGINT      NOT NULL DEFAULT 0,  -- 客单价（分）
            visit_frequency_days NUMERIC(7,2) NOT NULL DEFAULT 0, -- 平均到店间隔（天）
            preferred_channel   VARCHAR(32)  NOT NULL DEFAULT '', -- 偏好渠道
            preferred_categories JSONB      NOT NULL DEFAULT '[]', -- 偏好菜品品类
            discount_sensitivity NUMERIC(5,4) NOT NULL DEFAULT 0, -- 折扣敏感度
            churn_risk          NUMERIC(5,4) NOT NULL DEFAULT 0,  -- 流失风险（0-1）
            predicted_ltv_fen   BIGINT      NOT NULL DEFAULT 0,   -- 预测 LTV（分）
            ltv_tier            VARCHAR(16)  NOT NULL DEFAULT '',  -- LTV 分层
            last_event_id       UUID,
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (tenant_id, customer_id)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mv_customer_ltv_ltv
            ON mv_customer_ltv (tenant_id, predicted_ltv_fen DESC)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mv_customer_ltv_churn
            ON mv_customer_ltv (tenant_id, churn_risk DESC)
            WHERE churn_risk > 0.3
    """)
    op.execute("""ALTER TABLE mv_customer_ltv ENABLE ROW LEVEL SECURITY""")
    op.execute("""ALTER TABLE mv_customer_ltv FORCE ROW LEVEL SECURITY""")
    op.execute("""
        CREATE POLICY mv_customer_ltv_policy ON mv_customer_ltv
            FOR ALL USING (tenant_id = (current_setting('app.tenant_id', true))::uuid)
            WITH CHECK (tenant_id = (current_setting('app.tenant_id', true))::uuid)
    """)
    op.execute("COMMENT ON TABLE mv_customer_ltv IS '客户生命周期价值投影视图 — 因果链⑤扩展'")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS mv_customer_ltv CASCADE")
    op.execute("DROP TABLE IF EXISTS mv_employee_efficiency CASCADE")
    op.execute("DROP TABLE IF EXISTS mv_dish_profitability CASCADE")
    op.execute("DROP TABLE IF EXISTS mv_table_turnover CASCADE")
