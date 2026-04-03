"""触达归因链路（Attribution Chain）数据层

打通"触达→点击→到店→复购"完整归因链路，新增 3 张表：
  touch_events              — 每次营销触达事件（含 touch_id 短码追踪链接）
  attribution_conversions   — 归因转化记录（关联触达与预订/订单）
  campaign_summaries        — 活动汇总看板（定时聚合，供驾驶舱消费）

设计要点：
  - touch_id 使用短码格式（"tx_" + 8位 URL-safe），嵌入追踪链接
  - attribution_window_hours 默认 72h，可在 campaign 级别配置
  - 支持 last_touch / first_touch / linear 三种归因模型
  - campaign_summaries 按 (tenant_id, campaign_id, period_start, period_end) 唯一
  - 全部表使用 v006+ 标准 RLS（4 操作 + NULL guard + FORCE ROW LEVEL SECURITY）

Revision ID: v088
Revises: v087
Create Date: 2026-03-31
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = 'v088'
down_revision = 'v087'
branch_labels = None
depends_on = None

_RLS_COND = (
    "current_setting('app.tenant_id', TRUE) IS NOT NULL "
    "AND current_setting('app.tenant_id', TRUE) <> '' "
    "AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID"
)


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # 1. touch_events — 营销触达事件记录
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS touch_events (
            id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID        NOT NULL,

            -- 短码追踪 ID，嵌入追踪链接，格式 "tx_xxxxxxxx"
            touch_id                VARCHAR(20) NOT NULL,

            -- 触达渠道
            channel                 VARCHAR(30) NOT NULL
                CHECK (channel IN ('wecom', 'sms', 'miniapp_push', 'poster_qr')),

            -- 关联活动/旅程步骤（可为空：手动触达时无活动）
            campaign_id             UUID,
            journey_enrollment_id   UUID,

            -- 客户信息
            customer_id             UUID        NOT NULL,
            phone                   VARCHAR(20),

            -- 内容信息
            content_type            VARCHAR(30) NOT NULL
                CHECK (content_type IN ('coupon', 'invitation', 'product_recommend', 'recall')),
            content_snapshot        JSONB       NOT NULL DEFAULT '{}',

            -- 时间追踪
            sent_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            delivered_at            TIMESTAMPTZ,
            clicked_at              TIMESTAMPTZ,
            click_count             INTEGER     NOT NULL DEFAULT 0,

            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        COMMENT ON TABLE touch_events IS
            '营销触达事件表：记录每次向客户发送的触达，含短码 touch_id 用于链路追踪';
        COMMENT ON COLUMN touch_events.touch_id IS
            '追踪短码，格式 tx_xxxxxxxx，嵌入追踪 URL，全局唯一';
        COMMENT ON COLUMN touch_events.content_snapshot IS
            '发送内容快照 JSONB：{title, body, offer_id, coupon_code, landing_url, ...}';
        COMMENT ON COLUMN touch_events.click_count IS
            '点击次数（同一 touch_id 可多次点击，防刷后累加）';

        -- 追踪链接回调查询：按 touch_id 快速定位记录
        CREATE UNIQUE INDEX IF NOT EXISTS uq_touch_events_touch_id
            ON touch_events (touch_id);

        -- 归因查询：按客户 + 发送时间倒序查最近触点
        CREATE INDEX IF NOT EXISTS ix_te_tenant_customer_sent
            ON touch_events (tenant_id, customer_id, sent_at DESC);

        -- 活动维度汇总
        CREATE INDEX IF NOT EXISTS ix_te_tenant_campaign
            ON touch_events (tenant_id, campaign_id, sent_at)
            WHERE campaign_id IS NOT NULL;

        -- 渠道维度分析
        CREATE INDEX IF NOT EXISTS ix_te_tenant_channel_sent
            ON touch_events (tenant_id, channel, sent_at);
    """)

    op.execute("ALTER TABLE touch_events ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE touch_events FORCE ROW LEVEL SECURITY;")
    for op_name in ("select", "insert", "update", "delete"):
        check = f"WITH CHECK ({_RLS_COND})" if op_name in ("insert", "update") else ""
        op.execute(f"""
            CREATE POLICY rls_te_{op_name}
                ON touch_events
                FOR {op_name.upper()}
                USING ({_RLS_COND})
                {check};
        """)

    # ─────────────────────────────────────────────────────────────────
    # 2. attribution_conversions — 归因转化记录
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS attribution_conversions (
            id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID        NOT NULL,

            -- 关联触达
            touch_id                VARCHAR(20) NOT NULL,  -- 关联 touch_events.touch_id

            -- 转化客户
            customer_id             UUID        NOT NULL,

            -- 转化类型
            conversion_type         VARCHAR(20) NOT NULL
                CHECK (conversion_type IN ('reservation', 'order', 'repurchase', 'referral')),

            -- 关联业务实体（预订 ID 或订单 ID）
            conversion_id           UUID        NOT NULL,

            -- 转化金额（元，2位小数）
            conversion_value        NUMERIC(12, 2) NOT NULL DEFAULT 0,

            -- 转化时间
            converted_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            -- 归因窗口：触达后多少小时内算作归因（默认72）
            attribution_window_hours INTEGER    NOT NULL DEFAULT 72,

            -- 该触达的首次转化标志
            is_first_conversion     BOOLEAN     NOT NULL DEFAULT TRUE,

            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        COMMENT ON TABLE attribution_conversions IS
            '归因转化记录：将预订/订单/复购归因到具体触达事件（touch_id）';
        COMMENT ON COLUMN attribution_conversions.touch_id IS
            '关联 touch_events.touch_id，归因模型选定的触达来源';
        COMMENT ON COLUMN attribution_conversions.conversion_value IS
            '转化消费金额（元），订单金额或预订订金';
        COMMENT ON COLUMN attribution_conversions.is_first_conversion IS
            '是否为该 touch_id 的首次转化（同一触达可归因多次消费，如预订+实际消费）';

        -- 按 touch_id 查询所有转化
        CREATE INDEX IF NOT EXISTS ix_ac_touch_id
            ON attribution_conversions (touch_id);

        -- 按客户查询转化历史
        CREATE INDEX IF NOT EXISTS ix_ac_tenant_customer
            ON attribution_conversions (tenant_id, customer_id, converted_at DESC);

        -- 转化类型统计
        CREATE INDEX IF NOT EXISTS ix_ac_tenant_type_converted
            ON attribution_conversions (tenant_id, conversion_type, converted_at);

        -- 去重：同一 touch_id + 同一 conversion_id 只归因一次
        CREATE UNIQUE INDEX IF NOT EXISTS uq_ac_touch_conversion
            ON attribution_conversions (touch_id, conversion_id);
    """)

    op.execute("ALTER TABLE attribution_conversions ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE attribution_conversions FORCE ROW LEVEL SECURITY;")
    for op_name in ("select", "insert", "update", "delete"):
        check = f"WITH CHECK ({_RLS_COND})" if op_name in ("insert", "update") else ""
        op.execute(f"""
            CREATE POLICY rls_ac_{op_name}
                ON attribution_conversions
                FOR {op_name.upper()}
                USING ({_RLS_COND})
                {check};
        """)

    # ─────────────────────────────────────────────────────────────────
    # 3. campaign_summaries — 活动汇总看板（定时聚合）
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS campaign_summaries (
            id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID        NOT NULL,

            -- 活动维度（NULL 表示全渠道汇总）
            campaign_id             UUID,
            campaign_name           VARCHAR(200) NOT NULL DEFAULT '',

            -- 统计周期
            period_start            DATE        NOT NULL,
            period_end              DATE        NOT NULL,

            -- 触达漏斗指标
            total_touches           INTEGER     NOT NULL DEFAULT 0,
            delivered_count         INTEGER     NOT NULL DEFAULT 0,
            clicked_count           INTEGER     NOT NULL DEFAULT 0,

            -- 转化指标
            reservations_attributed INTEGER     NOT NULL DEFAULT 0,
            orders_attributed       INTEGER     NOT NULL DEFAULT 0,
            revenue_attributed      NUMERIC(14, 2) NOT NULL DEFAULT 0,

            -- 效率指标
            cac                     NUMERIC(10, 2) NOT NULL DEFAULT 0,  -- 获客成本（元）
            roi                     NUMERIC(10, 4) NOT NULL DEFAULT 0,  -- ROI 倍数

            -- 各人群效果分解 JSONB: [{segment: str, touches: int, conversions: int, revenue: float}]
            top_segments            JSONB       NOT NULL DEFAULT '[]',

            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        COMMENT ON TABLE campaign_summaries IS
            '活动汇总看板：由定时任务聚合，供驾驶舱和报表消费，避免实时聚合查询开销';
        COMMENT ON COLUMN campaign_summaries.cac IS
            '获客成本（元）= 活动总成本 / 新增客户数';
        COMMENT ON COLUMN campaign_summaries.roi IS
            'ROI 倍数 = (归因收入 - 活动成本) / 活动成本';
        COMMENT ON COLUMN campaign_summaries.top_segments IS
            '各人群效果 JSONB 数组：[{segment_name, touches, conversions, revenue, conversion_rate}]';

        -- 活动 + 周期唯一（upsert key）
        CREATE UNIQUE INDEX IF NOT EXISTS uq_cs_campaign_period
            ON campaign_summaries (tenant_id, campaign_id, period_start, period_end)
            WHERE campaign_id IS NOT NULL;

        -- 全渠道汇总唯一（campaign_id IS NULL 的行）
        CREATE UNIQUE INDEX IF NOT EXISTS uq_cs_overall_period
            ON campaign_summaries (tenant_id, period_start, period_end)
            WHERE campaign_id IS NULL;

        -- 按周期范围查询
        CREATE INDEX IF NOT EXISTS ix_cs_tenant_period
            ON campaign_summaries (tenant_id, period_start, period_end);

        -- 按 ROI 排序（看板 Top 活动）
        CREATE INDEX IF NOT EXISTS ix_cs_tenant_roi
            ON campaign_summaries (tenant_id, roi DESC);
    """)

    op.execute("ALTER TABLE campaign_summaries ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE campaign_summaries FORCE ROW LEVEL SECURITY;")
    for op_name in ("select", "insert", "update", "delete"):
        check = f"WITH CHECK ({_RLS_COND})" if op_name in ("insert", "update") else ""
        op.execute(f"""
            CREATE POLICY rls_cs_{op_name}
                ON campaign_summaries
                FOR {op_name.upper()}
                USING ({_RLS_COND})
                {check};
        """)


def downgrade() -> None:
    # 移除 campaign_summaries
    for op_name in ("select", "insert", "update", "delete"):
        op.execute(f"DROP POLICY IF EXISTS rls_cs_{op_name} ON campaign_summaries;")
    op.execute("DROP TABLE IF EXISTS campaign_summaries CASCADE;")

    # 移除 attribution_conversions
    for op_name in ("select", "insert", "update", "delete"):
        op.execute(f"DROP POLICY IF EXISTS rls_ac_{op_name} ON attribution_conversions;")
    op.execute("DROP TABLE IF EXISTS attribution_conversions CASCADE;")

    # 移除 touch_events
    for op_name in ("select", "insert", "update", "delete"):
        op.execute(f"DROP POLICY IF EXISTS rls_te_{op_name} ON touch_events;")
    op.execute("DROP TABLE IF EXISTS touch_events CASCADE;")
