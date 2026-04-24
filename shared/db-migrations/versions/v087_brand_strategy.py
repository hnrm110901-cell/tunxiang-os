"""品牌策略中枢（Brand Strategy Hub）数据层

新增 3 张表，为所有内容生成、分群、触达提供统一的品牌约束层：
  brand_profiles              — 品牌档案（品牌语气/目标客群/场景/禁忌词等）
  brand_seasonal_calendar     — 营销日历（节气/节日/自定义营销节点）
  brand_content_constraints   — 内容约束规则（各渠道字数/必须/禁止元素）

设计要点：
  - brand_profiles 支持版本管理（version 字段），更新时 version +1
  - brand_profiles.is_active 标记当前激活档案，同一 tenant_id 同一时间只有一个活跃
  - brand_voice / target_segments / key_scenarios / color_palette 均用 JSONB 存储，灵活扩展
  - brand_seasonal_calendar 支持 period_type 区分节气/节日/自定义
  - brand_content_constraints 按 channel 维度约束内容生成规则

RLS：全部使用 v006+ 标准安全模式（4 操作 + NULL guard + FORCE ROW LEVEL SECURITY）

Revision ID: v087
Revises: v086
Create Date: 2026-03-31
"""

from alembic import op

revision = "v087"
down_revision = "v086"
branch_labels = None
depends_on = None

_RLS_COND = (
    "current_setting('app.tenant_id', TRUE) IS NOT NULL "
    "AND current_setting('app.tenant_id', TRUE) <> '' "
    "AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID"
)


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # 1. brand_profiles — 品牌档案
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS brand_profiles (
            id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID        NOT NULL,

            -- 基础信息
            brand_name              VARCHAR(100) NOT NULL,
            brand_slogan            TEXT,
            brand_story             TEXT,

            -- 品牌定位
            cuisine_type            VARCHAR(50),   -- 菜系（湘菜/川菜/粤菜等）
            price_tier              VARCHAR(20)  NOT NULL DEFAULT 'mid'
                CHECK (price_tier IN ('budget', 'mid', 'upscale', 'luxury')),
            core_value_proposition  TEXT,          -- 核心价值主张

            -- 目标客群 JSONB: [{segment_name, description, proportion}]
            target_segments         JSONB        NOT NULL DEFAULT '[]',

            -- 主打场景 JSONB: [{scenario, importance}]  例：家庭聚餐/商务宴请/朋友聚会
            key_scenarios           JSONB        NOT NULL DEFAULT '[]',

            -- 品牌语气 JSONB: {tone, style, forbidden_words[], preferred_words[]}
            brand_voice             JSONB        NOT NULL DEFAULT '{}',

            -- 品牌色 JSONB: {primary, secondary, accent, background}
            color_palette           JSONB        NOT NULL DEFAULT '{}',

            -- 版本管理
            is_active               BOOLEAN      NOT NULL DEFAULT TRUE,
            version                 INTEGER      NOT NULL DEFAULT 1,

            created_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        );

        COMMENT ON TABLE brand_profiles IS
            '品牌档案：记录品牌语气、目标客群、场景、禁忌词等，为内容生成提供约束层';
        COMMENT ON COLUMN brand_profiles.price_tier IS
            '价格带：budget=经济实惠 mid=中等消费 upscale=高档 luxury=奢华';
        COMMENT ON COLUMN brand_profiles.target_segments IS
            '目标客群 JSONB 数组，每项：{segment_name, description, proportion}';
        COMMENT ON COLUMN brand_profiles.key_scenarios IS
            '主打场景 JSONB 数组，每项：{scenario, importance}，如家庭聚餐/商务宴请';
        COMMENT ON COLUMN brand_profiles.brand_voice IS
            '品牌语气配置：{tone, style, forbidden_words[], preferred_words[]}';
        COMMENT ON COLUMN brand_profiles.version IS
            '版本号，每次更新自动 +1，保留历史记录';

        -- 常用查询：获取租户当前激活的品牌档案
        CREATE INDEX IF NOT EXISTS ix_bp_tenant_active
            ON brand_profiles (tenant_id)
            WHERE is_active = TRUE;

        -- 品牌名检索
        CREATE INDEX IF NOT EXISTS ix_bp_tenant_name
            ON brand_profiles (tenant_id, brand_name);
    """)

    # RLS
    op.execute("ALTER TABLE brand_profiles ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE brand_profiles FORCE ROW LEVEL SECURITY;")
    for op_name in ("select", "insert", "update", "delete"):
        check = f"WITH CHECK ({_RLS_COND})" if op_name in ("insert", "update") else ""
        using = f"USING ({_RLS_COND})" if op_name != "insert" else ""
        op.execute(f"""
            CREATE POLICY rls_bp_{op_name}
                ON brand_profiles
                FOR {op_name.upper()}
                {using}
                {check};
        """)

    # ─────────────────────────────────────────────────────────────────
    # 2. brand_seasonal_calendar — 营销日历
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS brand_seasonal_calendar (
            id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID        NOT NULL,
            brand_profile_id    UUID        NOT NULL
                REFERENCES brand_profiles(id) ON DELETE CASCADE,

            -- 时间节点类型
            period_type         VARCHAR(20)  NOT NULL
                CHECK (period_type IN ('节气', '节日', '自定义')),
            period_name         VARCHAR(100) NOT NULL,  -- 春节/元宵/七夕/大暑等

            start_date          DATE        NOT NULL,
            end_date            DATE        NOT NULL,

            -- 营销内容
            campaign_theme      TEXT,                   -- 营销主题
            recommended_dishes  JSONB        NOT NULL DEFAULT '[]',  -- 推荐菜品列表
            marketing_focus     TEXT,                   -- 主推内容方向

            -- 本次活动目标人群 JSONB: [{segment_name, priority}]
            target_segments     JSONB        NOT NULL DEFAULT '[]',

            created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

            CONSTRAINT chk_bsc_date_order CHECK (end_date >= start_date)
        );

        COMMENT ON TABLE brand_seasonal_calendar IS
            '营销日历：记录节气/节日/自定义营销节点，供内容生成获取时令上下文';
        COMMENT ON COLUMN brand_seasonal_calendar.period_type IS
            '节点类型：节气（24节气）/ 节日（传统节日+现代节日）/ 自定义（品牌自定义活动）';
        COMMENT ON COLUMN brand_seasonal_calendar.recommended_dishes IS
            '推荐菜品 JSONB 数组：[{dish_name, reason, discount_pct}]';
        COMMENT ON COLUMN brand_seasonal_calendar.target_segments IS
            '本次活动目标人群：[{segment_name, priority}]';

        -- 按日期范围查询当前营销节点
        CREATE INDEX IF NOT EXISTS ix_bsc_tenant_dates
            ON brand_seasonal_calendar (tenant_id, start_date, end_date);

        -- 按品牌档案查询
        CREATE INDEX IF NOT EXISTS ix_bsc_brand_profile
            ON brand_seasonal_calendar (brand_profile_id);
    """)

    # RLS
    op.execute("ALTER TABLE brand_seasonal_calendar ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE brand_seasonal_calendar FORCE ROW LEVEL SECURITY;")
    for op_name in ("select", "insert", "update", "delete"):
        check = f"WITH CHECK ({_RLS_COND})" if op_name in ("insert", "update") else ""
        using = f"USING ({_RLS_COND})" if op_name != "insert" else ""
        op.execute(f"""
            CREATE POLICY rls_bsc_{op_name}
                ON brand_seasonal_calendar
                FOR {op_name.upper()}
                {using}
                {check};
        """)

    # ─────────────────────────────────────────────────────────────────
    # 3. brand_content_constraints — 内容约束规则
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS brand_content_constraints (
            id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           UUID        NOT NULL,
            brand_profile_id    UUID        NOT NULL
                REFERENCES brand_profiles(id) ON DELETE CASCADE,

            -- 约束维度
            constraint_type     VARCHAR(20)  NOT NULL
                CHECK (constraint_type IN ('tone', 'format', 'channel')),
            channel             VARCHAR(30)  NOT NULL
                CHECK (channel IN (
                    'wechat',      -- 微信公众号
                    'miniapp',     -- 小程序
                    'sms',         -- 短信
                    'poster',      -- 海报/物料
                    'wecom',       -- 企业微信
                    'douyin',      -- 抖音
                    'xiaohongshu', -- 小红书
                    'all'          -- 全渠道通用
                )),

            -- 格式约束
            max_length          INTEGER,     -- 最大字符数（NULL=不限）

            -- 内容规则 JSONB
            required_elements   JSONB        NOT NULL DEFAULT '[]',  -- 必须包含的元素
            forbidden_elements  JSONB        NOT NULL DEFAULT '[]',  -- 禁止出现的内容
            template_hints      JSONB        NOT NULL DEFAULT '{}',  -- 内容模板提示

            created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        );

        COMMENT ON TABLE brand_content_constraints IS
            '内容约束规则：按渠道定义内容生成的格式/风格/禁忌，供内容引擎消费';
        COMMENT ON COLUMN brand_content_constraints.constraint_type IS
            '约束类型：tone=语气约束 format=格式约束 channel=渠道特定约束';
        COMMENT ON COLUMN brand_content_constraints.required_elements IS
            '必须包含元素 JSONB 数组：["品牌名", "联系方式", "营业时间"]';
        COMMENT ON COLUMN brand_content_constraints.forbidden_elements IS
            '禁止出现内容 JSONB 数组：["最低价", "全网最便宜", "免费送"]';
        COMMENT ON COLUMN brand_content_constraints.template_hints IS
            '内容模板提示 JSONB：{opening_line, closing_line, cta_style, tone_examples[]}';

        -- 按渠道查询约束规则
        CREATE INDEX IF NOT EXISTS ix_bcc_tenant_channel
            ON brand_content_constraints (tenant_id, channel);

        -- 按品牌档案查询
        CREATE INDEX IF NOT EXISTS ix_bcc_brand_profile
            ON brand_content_constraints (brand_profile_id);
    """)

    # RLS
    op.execute("ALTER TABLE brand_content_constraints ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE brand_content_constraints FORCE ROW LEVEL SECURITY;")
    for op_name in ("select", "insert", "update", "delete"):
        check = f"WITH CHECK ({_RLS_COND})" if op_name in ("insert", "update") else ""
        using = f"USING ({_RLS_COND})" if op_name != "insert" else ""
        op.execute(f"""
            CREATE POLICY rls_bcc_{op_name}
                ON brand_content_constraints
                FOR {op_name.upper()}
                {using}
                {check};
        """)


def downgrade() -> None:
    # 移除 brand_content_constraints
    for op_name in ("select", "insert", "update", "delete"):
        op.execute(f"DROP POLICY IF EXISTS rls_bcc_{op_name} ON brand_content_constraints;")
    op.execute("DROP TABLE IF EXISTS brand_content_constraints CASCADE;")

    # 移除 brand_seasonal_calendar
    for op_name in ("select", "insert", "update", "delete"):
        op.execute(f"DROP POLICY IF EXISTS rls_bsc_{op_name} ON brand_seasonal_calendar;")
    op.execute("DROP TABLE IF EXISTS brand_seasonal_calendar CASCADE;")

    # 移除 brand_profiles
    for op_name in ("select", "insert", "update", "delete"):
        op.execute(f"DROP POLICY IF EXISTS rls_bp_{op_name} ON brand_profiles;")
    op.execute("DROP TABLE IF EXISTS brand_profiles CASCADE;")
