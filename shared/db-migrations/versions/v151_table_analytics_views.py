"""v151 — 桌台经营分析物化视图 (Table Analytics Views)

桌台中心化架构 Phase 3：经营决策层
基于 dining_sessions 事件流生成可直接读取的分析视图，
供 Agent、经营报表、总部大屏消费，不再跨服务查询。

新增 3 个物化视图（均为 Table 而非 MATERIALIZED VIEW，
与 v148 模式一致，由投影器异步填充）：

  mv_table_turnover       — 翻台率与时段分析（门店级/区域级/桌台级）
  mv_session_analytics    — 堂食会话质量分析（服务SLA/人均/时长分布）
  mv_waiter_performance   — 服务员效能看板（桌台数/服务呼叫响应/人均消费）

投影器消费的事件类型：
  table.opened / table.paid / table.cleared
  table.service_called / table.bill_requested / table.vip_identified

Revision: v151
"""

from alembic import op
from typing import Sequence, Union

revision: str = "v151"
down_revision: Union[str, None] = "v150"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:

    # ─────────────────────────────────────────────────────────────────
    # 1. mv_table_turnover — 翻台率分析
    #    粒度：门店 × 日期 × 区域 × 时段
    #    消费者：老板看翻台率、运营优化桌台布局、Agent识别高峰期
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS mv_table_turnover (
            tenant_id           UUID        NOT NULL,
            store_id            UUID        NOT NULL,
            stat_date           DATE        NOT NULL,
            zone_id             UUID,                       -- NULL = 全店汇总
            zone_name           VARCHAR(50),
            meal_period         VARCHAR(20) NOT NULL DEFAULT 'all',
            -- meal_period: breakfast/lunch/dinner/late_night/all

            -- 翻台指标
            total_sessions      INT         NOT NULL DEFAULT 0,  -- 已结账会话数（翻台次数）
            active_tables       INT         NOT NULL DEFAULT 0,  -- 当日有营业的桌台数
            turnover_rate       NUMERIC(5,2) NOT NULL DEFAULT 0, -- 翻台率 = total_sessions / active_tables

            -- 时长分析（分钟）
            avg_dining_minutes  NUMERIC(6,1) NOT NULL DEFAULT 0, -- 平均用餐时长
            p50_dining_minutes  NUMERIC(6,1) NOT NULL DEFAULT 0, -- 中位数用餐时长
            p90_dining_minutes  NUMERIC(6,1) NOT NULL DEFAULT 0, -- P90用餐时长

            -- 等候付款时长（买单到结账）
            avg_billing_minutes NUMERIC(6,1) NOT NULL DEFAULT 0, -- 平均等候结账时长

            -- 收入指标（分）
            total_revenue_fen   BIGINT      NOT NULL DEFAULT 0,
            avg_per_session_fen INT         NOT NULL DEFAULT 0,  -- 平均桌均消费
            avg_per_capita_fen  INT         NOT NULL DEFAULT 0,  -- 平均人均消费

            -- 超时预警（超过门店设定的翻台上限时间）
            overstay_sessions   INT         NOT NULL DEFAULT 0,
            overstay_rate       NUMERIC(5,2) NOT NULL DEFAULT 0,

            -- 投影器元数据
            last_updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            event_cursor        BIGINT      NOT NULL DEFAULT 0,

            CONSTRAINT pk_mv_table_turnover
                PRIMARY KEY (tenant_id, store_id, stat_date, meal_period, COALESCE(zone_id, '00000000-0000-0000-0000-000000000000'::UUID))
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_mv_tt_store_date ON mv_table_turnover (store_id, stat_date DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_mv_tt_zone ON mv_table_turnover (store_id, zone_id, stat_date DESC)")
    op.execute("""
        COMMENT ON TABLE mv_table_turnover IS
        'v151: 翻台率分析。粒度：门店×日期×区域×时段。由投影器消费 table.paid/cleared 事件填充。'
    """)

    # ─────────────────────────────────────────────────────────────────
    # 2. mv_session_analytics — 堂食会话质量分析
    #    粒度：门店 × 日期 × 会话类型
    #    消费者：服务质量报告、Agent触发超时预警、SLA追踪
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS mv_session_analytics (
            tenant_id           UUID        NOT NULL,
            store_id            UUID        NOT NULL,
            stat_date           DATE        NOT NULL,
            session_type        VARCHAR(20) NOT NULL DEFAULT 'dine_in',
            -- session_type: dine_in/banquet/vip_room/self_order/hotpot/all

            -- 会话数量
            total_sessions      INT         NOT NULL DEFAULT 0,
            vip_sessions        INT         NOT NULL DEFAULT 0,  -- 有VIP的会话数
            vip_rate            NUMERIC(5,2) NOT NULL DEFAULT 0,

            -- 点餐行为
            avg_orders_per_session  NUMERIC(4,1) NOT NULL DEFAULT 0,  -- 平均轮次（含加菜）
            add_order_sessions  INT         NOT NULL DEFAULT 0,  -- 有加菜的会话数
            add_order_rate      NUMERIC(5,2) NOT NULL DEFAULT 0, -- 加菜率

            -- 服务呼叫分析
            total_service_calls INT         NOT NULL DEFAULT 0,
            urge_dish_calls     INT         NOT NULL DEFAULT 0,  -- 催菜次数
            avg_calls_per_session NUMERIC(4,1) NOT NULL DEFAULT 0,
            avg_response_seconds  NUMERIC(8,1),                 -- 平均服务响应秒数

            -- 出餐时长（分钟，首道菜到桌时间）
            avg_first_dish_minutes NUMERIC(6,1),
            sla_breach_count    INT         NOT NULL DEFAULT 0,  -- 超出餐SLA次数

            -- 买单等待（分钟）
            avg_billing_wait_minutes NUMERIC(6,1),

            -- 消费分析（分）
            total_revenue_fen   BIGINT      NOT NULL DEFAULT 0,
            avg_per_session_fen INT         NOT NULL DEFAULT 0,
            avg_per_capita_fen  INT         NOT NULL DEFAULT 0,
            avg_guest_count     NUMERIC(4,1) NOT NULL DEFAULT 0,

            -- 高价值桌台（人均超过阈值）
            high_value_sessions INT         NOT NULL DEFAULT 0,

            -- 投影器元数据
            last_updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            event_cursor        BIGINT      NOT NULL DEFAULT 0,

            CONSTRAINT pk_mv_session_analytics
                PRIMARY KEY (tenant_id, store_id, stat_date, session_type)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_mv_sa_store_date ON mv_session_analytics (store_id, stat_date DESC)")
    op.execute("""
        COMMENT ON TABLE mv_session_analytics IS
        'v151: 堂食会话质量分析。粒度：门店×日期×会话类型。由投影器消费 table.* 事件填充。'
    """)

    # ─────────────────────────────────────────────────────────────────
    # 3. mv_waiter_performance — 服务员效能看板
    #    粒度：门店 × 日期 × 服务员
    #    消费者：提成计算、绩效评估、排班优化、服务质量管理
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS mv_waiter_performance (
            tenant_id           UUID        NOT NULL,
            store_id            UUID        NOT NULL,
            stat_date           DATE        NOT NULL,
            employee_id         UUID        NOT NULL,
            employee_name       VARCHAR(50),
            zone_name           VARCHAR(50),

            -- 桌台负责
            sessions_served     INT         NOT NULL DEFAULT 0,  -- 负责的会话数
            total_guests        INT         NOT NULL DEFAULT 0,  -- 服务总人次
            avg_dining_minutes  NUMERIC(6,1) NOT NULL DEFAULT 0, -- 平均用餐时长

            -- 服务质量
            service_calls_received  INT     NOT NULL DEFAULT 0,  -- 收到的服务呼叫数
            service_calls_handled   INT     NOT NULL DEFAULT 0,  -- 处理的呼叫数
            avg_response_seconds    NUMERIC(8,1),                -- 平均响应时长
            sla_compliance_rate     NUMERIC(5,2),                -- SLA达标率（<180秒）

            -- 催菜分析
            urge_dish_count     INT         NOT NULL DEFAULT 0,  -- 被催菜次数
            urge_dish_rate      NUMERIC(5,2) NOT NULL DEFAULT 0, -- 催菜率（urge/sessions）

            -- 收入贡献
            total_revenue_fen   BIGINT      NOT NULL DEFAULT 0,  -- 责任桌台总收入
            revenue_per_session INT         NOT NULL DEFAULT 0,  -- 桌均收入
            vip_sessions_served INT         NOT NULL DEFAULT 0,  -- 服务VIP的次数

            -- 投影器元数据
            last_updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            event_cursor        BIGINT      NOT NULL DEFAULT 0,

            CONSTRAINT pk_mv_waiter_performance
                PRIMARY KEY (tenant_id, store_id, stat_date, employee_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_mv_wp_store_date ON mv_waiter_performance (store_id, stat_date DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_mv_wp_employee ON mv_waiter_performance (employee_id, stat_date DESC)")
    op.execute("""
        COMMENT ON TABLE mv_waiter_performance IS
        'v151: 服务员效能看板。粒度：门店×日期×服务员。供提成计算和绩效评估使用。'
    """)

    # ─────────────────────────────────────────────────────────────────
    # 4. 在 projector_checkpoints 注册新的投影器游标
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        INSERT INTO projector_checkpoints (projector_name, last_event_id, last_processed_at)
        VALUES
            ('TableTurnoverProjector',   NULL, NOW()),
            ('SessionAnalyticsProjector', NULL, NOW()),
            ('WaiterPerformanceProjector', NULL, NOW())
        ON CONFLICT (projector_name) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DELETE FROM projector_checkpoints WHERE projector_name IN ("
               "'TableTurnoverProjector', 'SessionAnalyticsProjector', 'WaiterPerformanceProjector')")
    op.execute("DROP TABLE IF EXISTS mv_waiter_performance")
    op.execute("DROP TABLE IF EXISTS mv_session_analytics")
    op.execute("DROP TABLE IF EXISTS mv_table_turnover")
