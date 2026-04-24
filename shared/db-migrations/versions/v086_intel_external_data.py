"""外部数据采集层 — Market Intel OS 外部数据入口

新增 5 张表，支持竞对监测、点评情报、市场趋势和采集任务调度：
  competitor_brands        — 竞对品牌档案
  competitor_snapshots     — 竞对周期性快照
  review_intel             — 全渠道点评情报
  market_trend_signals     — 市场趋势信号
  intel_crawl_tasks        — 采集任务调度

设计要点：
  - 全部表含 tenant_id，启用 RLS（v006+ 标准安全模式）
  - competitor_snapshots 保存完整 raw_data JSONB，方便回溯
  - review_intel 同时支持自家门店（is_own_store=TRUE）和竞对门店
  - market_trend_signals 支持多维度趋势评分和方向标记
  - intel_crawl_tasks 记录调度状态和最近错误日志

RLS：全部使用 v006+ 标准安全模式（4 操作 + NULL guard + FORCE ROW LEVEL SECURITY）

Revision ID: v086
Revises: v085
Create Date: 2026-03-31
"""

from alembic import op

revision = "v086"
down_revision = "v085"
branch_labels = None
depends_on = None

_RLS_COND = (
    "current_setting('app.tenant_id', TRUE) IS NOT NULL "
    "AND current_setting('app.tenant_id', TRUE) <> '' "
    "AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID"
)


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # 1. competitor_brands — 竞对品牌档案
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS competitor_brands (
            id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID         NOT NULL,
            name            VARCHAR(100) NOT NULL,
            cuisine_type    VARCHAR(50),
            price_tier      VARCHAR(20)
                CHECK (price_tier IN ('economy', 'mid_range', 'mid_premium', 'premium', 'luxury')),
            city            VARCHAR(50),
            district        VARCHAR(50),
            -- 各平台门店 ID 映射，如 {"meituan": "123", "douyin": "456"}
            platform_ids    JSONB        NOT NULL DEFAULT '{}',
            is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        );

        COMMENT ON TABLE competitor_brands IS
            '竞对品牌档案：记录需要持续监测的竞争对手基本信息及各平台 ID 映射';
        COMMENT ON COLUMN competitor_brands.platform_ids IS
            '各平台门店 ID 映射 JSONB，如 {"meituan": "store_id", "douyin": "store_id"}';

        CREATE INDEX IF NOT EXISTS ix_cb_tenant_active
            ON competitor_brands (tenant_id)
            WHERE is_active = TRUE;

        CREATE INDEX IF NOT EXISTS ix_cb_tenant_city
            ON competitor_brands (tenant_id, city, cuisine_type);
    """)

    op.execute("ALTER TABLE competitor_brands ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE competitor_brands FORCE ROW LEVEL SECURITY;")
    for op_name in ("select", "insert", "update", "delete"):
        check = f"WITH CHECK ({_RLS_COND})" if op_name in ("insert", "update") else ""
        using = f"USING ({_RLS_COND})" if op_name != "insert" else ""
        op.execute(f"""
            CREATE POLICY rls_cb_{op_name}
                ON competitor_brands
                FOR {op_name.upper()}
                {using}
                {check};
        """)

    # ─────────────────────────────────────────────────────────────────
    # 2. competitor_snapshots — 竞对快照
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS competitor_snapshots (
            id                   UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id            UUID        NOT NULL,
            competitor_brand_id  UUID        NOT NULL
                REFERENCES competitor_brands(id) ON DELETE CASCADE,
            snapshot_date        DATE        NOT NULL,
            avg_rating           NUMERIC(3,2),
            review_count         INTEGER,
            price_range          JSONB,          -- {"min_fen": 1500, "max_fen": 8800, "avg_fen": 4500}
            top_dishes           JSONB,          -- [{name, price_fen, monthly_sales, rank}]
            active_promotions    JSONB,          -- [{title, discount_type, discount_value, end_date}]
            raw_data             JSONB,          -- 原始平台返回数据，完整保存
            source               VARCHAR(30)     -- 'meituan', 'douyin', 'eleme', 'manual'
                CHECK (source IN ('meituan', 'douyin', 'eleme', 'dianping', 'manual')),
            created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        COMMENT ON TABLE competitor_snapshots IS
            '竞对快照：按日期记录竞对的评分/点评数/菜单/促销等快照数据';
        COMMENT ON COLUMN competitor_snapshots.raw_data IS
            '原始平台返回完整数据（JSONB），用于数据回溯和再分析';

        CREATE INDEX IF NOT EXISTS ix_cs_brand_date
            ON competitor_snapshots (competitor_brand_id, snapshot_date DESC);

        CREATE INDEX IF NOT EXISTS ix_cs_tenant_date
            ON competitor_snapshots (tenant_id, snapshot_date DESC);
    """)

    op.execute("ALTER TABLE competitor_snapshots ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE competitor_snapshots FORCE ROW LEVEL SECURITY;")
    for op_name in ("select", "insert", "update", "delete"):
        check = f"WITH CHECK ({_RLS_COND})" if op_name in ("insert", "update") else ""
        using = f"USING ({_RLS_COND})" if op_name != "insert" else ""
        op.execute(f"""
            CREATE POLICY rls_cs_{op_name}
                ON competitor_snapshots
                FOR {op_name.upper()}
                {using}
                {check};
        """)

    # ─────────────────────────────────────────────────────────────────
    # 3. review_intel — 点评情报
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS review_intel (
            id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id        UUID        NOT NULL,
            source           VARCHAR(30) NOT NULL
                CHECK (source IN ('meituan', 'douyin', 'eleme', 'dianping', 'xiaohongshu', 'manual')),
            source_store_id  VARCHAR(100) NOT NULL,   -- 平台门店 ID
            is_own_store     BOOLEAN      NOT NULL DEFAULT FALSE,
            content          TEXT         NOT NULL,
            rating           NUMERIC(3,1),            -- 1.0 ~ 5.0
            sentiment_score  NUMERIC(4,3),            -- -1.000 ~ 1.000（负面到正面）
            topics           JSONB,                   -- [{topic, sentiment, confidence}]
            author_level     VARCHAR(20),             -- 'regular', 'vip', 'kol', 'critic'
            review_date      DATE,
            collected_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        COMMENT ON TABLE review_intel IS
            '全渠道点评情报：同时支持自家门店和竞对门店的点评数据，含情感分析和主题标注';
        COMMENT ON COLUMN review_intel.sentiment_score IS
            '情感评分 -1.0 (极负面) ~ 1.0 (极正面)，由 Claude API 情感分析填充';
        COMMENT ON COLUMN review_intel.topics IS
            '主题列表 JSONB，如 [{topic: "服务", sentiment: "positive", confidence: 0.85}]';

        CREATE INDEX IF NOT EXISTS ix_ri_tenant_own_date
            ON review_intel (tenant_id, is_own_store, review_date DESC);

        CREATE INDEX IF NOT EXISTS ix_ri_tenant_source_store
            ON review_intel (tenant_id, source, source_store_id);

        CREATE INDEX IF NOT EXISTS ix_ri_tenant_sentiment
            ON review_intel (tenant_id, sentiment_score)
            WHERE sentiment_score IS NOT NULL;
    """)

    op.execute("ALTER TABLE review_intel ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE review_intel FORCE ROW LEVEL SECURITY;")
    for op_name in ("select", "insert", "update", "delete"):
        check = f"WITH CHECK ({_RLS_COND})" if op_name in ("insert", "update") else ""
        using = f"USING ({_RLS_COND})" if op_name != "insert" else ""
        op.execute(f"""
            CREATE POLICY rls_ri_{op_name}
                ON review_intel
                FOR {op_name.upper()}
                {using}
                {check};
        """)

    # ─────────────────────────────────────────────────────────────────
    # 4. market_trend_signals — 市场趋势信号
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS market_trend_signals (
            id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id        UUID        NOT NULL,
            signal_type      VARCHAR(30) NOT NULL
                CHECK (signal_type IN (
                    'dish_trend',       -- 菜品趋势
                    'ingredient_trend', -- 食材趋势
                    'flavor_trend',     -- 口味趋势
                    'format_trend',     -- 业态趋势
                    'price_trend',      -- 价格带趋势
                    'occasion_trend'    -- 消费场景趋势
                )),
            keyword          VARCHAR(100) NOT NULL,
            category         VARCHAR(50),
            trend_score      NUMERIC(5,2),          -- 0.00 ~ 100.00
            trend_direction  VARCHAR(10)
                CHECK (trend_direction IN ('rising', 'stable', 'declining')),
            source           VARCHAR(30)
                CHECK (source IN ('meituan', 'douyin', 'xiaohongshu', 'weibo', 'aggregated')),
            region           VARCHAR(50),
            period_start     DATE,
            period_end       DATE,
            raw_data         JSONB,                 -- 原始趋势数据（搜索量、曝光量等）
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        COMMENT ON TABLE market_trend_signals IS
            '市场趋势信号：记录菜品/食材/口味/业态等多维度趋势评分和方向标记';
        COMMENT ON COLUMN market_trend_signals.trend_score IS
            '趋势评分 0-100，综合搜索量/销量增速/点评频次等多维度计算';

        CREATE INDEX IF NOT EXISTS ix_mts_tenant_type_score
            ON market_trend_signals (tenant_id, signal_type, trend_score DESC);

        CREATE INDEX IF NOT EXISTS ix_mts_tenant_keyword
            ON market_trend_signals (tenant_id, keyword, period_end DESC);

        CREATE INDEX IF NOT EXISTS ix_mts_tenant_rising
            ON market_trend_signals (tenant_id, trend_direction, created_at DESC)
            WHERE trend_direction = 'rising';
    """)

    op.execute("ALTER TABLE market_trend_signals ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE market_trend_signals FORCE ROW LEVEL SECURITY;")
    for op_name in ("select", "insert", "update", "delete"):
        check = f"WITH CHECK ({_RLS_COND})" if op_name in ("insert", "update") else ""
        using = f"USING ({_RLS_COND})" if op_name != "insert" else ""
        op.execute(f"""
            CREATE POLICY rls_mts_{op_name}
                ON market_trend_signals
                FOR {op_name.upper()}
                {using}
                {check};
        """)

    # ─────────────────────────────────────────────────────────────────
    # 5. intel_crawl_tasks — 采集任务调度
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS intel_crawl_tasks (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID        NOT NULL,
            task_type       VARCHAR(30) NOT NULL
                CHECK (task_type IN (
                    'competitor_snapshot',  -- 竞对快照采集
                    'own_store_reviews',    -- 自家门店点评采集
                    'competitor_reviews',   -- 竞对点评采集
                    'dish_trends',          -- 菜品趋势扫描
                    'ingredient_trends'     -- 食材趋势扫描
                )),
            target_config   JSONB        NOT NULL DEFAULT '{}',
            -- 调度 Cron 表达式，如 "0 9 * * 1"（每周一9点）
            schedule_cron   VARCHAR(50),
            last_run_at     TIMESTAMPTZ,
            next_run_at     TIMESTAMPTZ,
            status          VARCHAR(20)  NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'paused', 'error', 'completed')),
            error_log       TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        COMMENT ON TABLE intel_crawl_tasks IS
            '采集任务调度：管理竞对/点评/趋势等外部数据的定时采集任务配置';
        COMMENT ON COLUMN intel_crawl_tasks.target_config IS
            '采集目标配置 JSONB，如 {competitor_brand_id, platform, days} 或 {city, cuisine_type}';
        COMMENT ON COLUMN intel_crawl_tasks.error_log IS
            '最近一次失败的错误日志，成功时清空';

        CREATE INDEX IF NOT EXISTS ix_ict_tenant_status
            ON intel_crawl_tasks (tenant_id, status)
            WHERE status = 'active';

        CREATE INDEX IF NOT EXISTS ix_ict_tenant_next_run
            ON intel_crawl_tasks (tenant_id, next_run_at)
            WHERE status = 'active' AND next_run_at IS NOT NULL;
    """)

    op.execute("ALTER TABLE intel_crawl_tasks ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE intel_crawl_tasks FORCE ROW LEVEL SECURITY;")
    for op_name in ("select", "insert", "update", "delete"):
        check = f"WITH CHECK ({_RLS_COND})" if op_name in ("insert", "update") else ""
        using = f"USING ({_RLS_COND})" if op_name != "insert" else ""
        op.execute(f"""
            CREATE POLICY rls_ict_{op_name}
                ON intel_crawl_tasks
                FOR {op_name.upper()}
                {using}
                {check};
        """)


def downgrade() -> None:
    # 按依赖顺序逆向删除
    for table, prefix in [
        ("intel_crawl_tasks", "ict"),
        ("market_trend_signals", "mts"),
        ("review_intel", "ri"),
        ("competitor_snapshots", "cs"),
        ("competitor_brands", "cb"),
    ]:
        for op_name in ("select", "insert", "update", "delete"):
            op.execute(f"DROP POLICY IF EXISTS rls_{prefix}_{op_name} ON {table};")
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE;")
