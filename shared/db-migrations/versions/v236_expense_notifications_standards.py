"""v236 — 费控通知记录 + 差标库

Tables: expense_notifications, expense_standards, standard_city_tiers
Sprint: P0-S2

RLS 采用 NULLIF 安全格式，防止 app.tenant_id 为空时发生跨租户数据泄露。
所有金额字段单位为分（fen），前端展示时除以 100 转换为元。

Revision ID: v236
Revises: v235
Create Date: 2026-04-12
"""

from alembic import op
import sqlalchemy as sa

revision = "v236"
down_revision = "v235b"
branch_labels = None
depends_on = None

# 标准安全 RLS 条件（NULLIF 保护，与 v231 规范一致）
_RLS_COND = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID"


def upgrade() -> None:
    # ──────────────────────────────────────────────────────────────────
    # expense_notifications — 审批推送记录
    # ──────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS expense_notifications (
            id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id        UUID         NOT NULL,
            application_id   UUID         NOT NULL REFERENCES expense_applications(id) ON DELETE CASCADE,
            recipient_id     UUID         NOT NULL,
            recipient_role   VARCHAR(50),
            channel          VARCHAR(20)  NOT NULL,
            event_type       VARCHAR(50)  NOT NULL,
            message_title    VARCHAR(200) NOT NULL,
            message_body     TEXT         NOT NULL,
            push_status      VARCHAR(20)  NOT NULL DEFAULT 'pending',
            sent_at          TIMESTAMPTZ,
            failed_reason    TEXT,
            retry_count      INTEGER      DEFAULT 0,
            external_msg_id  VARCHAR(200),
            created_at       TIMESTAMPTZ  DEFAULT now()
        );

        COMMENT ON TABLE expense_notifications IS
            '审批推送记录：记录费用申请全流程中每条通知消息的发送状态，支持企微/钉钉/飞书/短信多渠道';
        COMMENT ON COLUMN expense_notifications.recipient_id IS
            '接收人员工 ID，对应 employees.id';
        COMMENT ON COLUMN expense_notifications.recipient_role IS
            '接收人角色，如 审批人/申请人；辅助调试和日志分析';
        COMMENT ON COLUMN expense_notifications.channel IS
            '推送渠道：wecom=企业微信 / dingtalk=钉钉 / feishu=飞书 / sms=短信';
        COMMENT ON COLUMN expense_notifications.event_type IS
            '触发事件：approval_requested=待审批 / approved=已批准 / rejected=已拒绝 / transferred=已转审 / reminder=催办提醒';
        COMMENT ON COLUMN expense_notifications.push_status IS
            '推送状态：pending=待发送 / sent=已发送 / failed=发送失败 / skipped=已跳过';
        COMMENT ON COLUMN expense_notifications.retry_count IS
            '已重试次数，由消息队列消费者维护，超过最大重试次数时置 push_status=failed';
        COMMENT ON COLUMN expense_notifications.external_msg_id IS
            '第三方平台返回的消息 ID（如企微 msgid），用于消息撤回和状态追踪';

        CREATE INDEX IF NOT EXISTS ix_expense_notifications_tenant_application
            ON expense_notifications (tenant_id, application_id);

        CREATE INDEX IF NOT EXISTS ix_expense_notifications_tenant_recipient_status
            ON expense_notifications (tenant_id, recipient_id, push_status);

        CREATE INDEX IF NOT EXISTS ix_expense_notifications_tenant_created
            ON expense_notifications (tenant_id, created_at DESC);
    """)

    op.execute("ALTER TABLE expense_notifications ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE expense_notifications FORCE ROW LEVEL SECURITY;")
    op.execute(f"""
        CREATE POLICY expense_notifications_rls ON expense_notifications
            USING ({_RLS_COND})
            WITH CHECK ({_RLS_COND});
    """)

    # ──────────────────────────────────────────────────────────────────
    # expense_standards — 差标规则
    # ──────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS expense_standards (
            id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID         NOT NULL,
            brand_id        UUID         NOT NULL,
            name            VARCHAR(100) NOT NULL,
            staff_level     VARCHAR(30)  NOT NULL,
            city_tier       VARCHAR(10)  NOT NULL,
            expense_type    VARCHAR(30)  NOT NULL,
            daily_limit     BIGINT       NOT NULL,
            single_limit    BIGINT,
            notes           TEXT,
            is_active       BOOLEAN      DEFAULT true,
            effective_from  DATE         NOT NULL DEFAULT CURRENT_DATE,
            effective_to    DATE,
            created_at      TIMESTAMPTZ  DEFAULT now(),
            updated_at      TIMESTAMPTZ  DEFAULT now()
        );

        COMMENT ON TABLE expense_standards IS
            '差标规则：按员工级别×城市级别×费用类型定义每日限额和单笔限额，支持品牌级精细化配置';
        COMMENT ON COLUMN expense_standards.name IS
            '差标规则名称，如 督导差标-一线城市，用于前端展示和审批提示';
        COMMENT ON COLUMN expense_standards.staff_level IS
            '员工级别：store_staff=门店员工 / store_manager=店长 / region_manager=区域经理 / brand_manager=品牌经理 / executive=高管';
        COMMENT ON COLUMN expense_standards.city_tier IS
            '城市级别：tier1=一线 / tier2=二线 / tier3=三线 / other=其他，与 standard_city_tiers 对应';
        COMMENT ON COLUMN expense_standards.expense_type IS
            '费用类型：accommodation=住宿 / meal=餐饮 / transport=交通 / other_travel=其他差旅';
        COMMENT ON COLUMN expense_standards.daily_limit IS
            '单位：分(fen)，展示时除以100转元；每日费用限额，审批时自动与申请金额对比预警';
        COMMENT ON COLUMN expense_standards.single_limit IS
            '单位：分(fen)，展示时除以100转元；单笔费用限额，NULL=不限单笔金额';
        COMMENT ON COLUMN expense_standards.effective_from IS
            '差标生效日期，支持提前配置未来差标，调薪/调级时自动切换';
        COMMENT ON COLUMN expense_standards.effective_to IS
            '差标失效日期，NULL=永久有效；设置后到期自动失效';

        CREATE UNIQUE INDEX IF NOT EXISTS uq_expense_standards_brand_dimension
            ON expense_standards (tenant_id, brand_id, staff_level, city_tier, expense_type);

        CREATE INDEX IF NOT EXISTS ix_expense_standards_tenant_brand_active
            ON expense_standards (tenant_id, brand_id, is_active);
    """)

    op.execute("ALTER TABLE expense_standards ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE expense_standards FORCE ROW LEVEL SECURITY;")
    op.execute(f"""
        CREATE POLICY expense_standards_rls ON expense_standards
            USING ({_RLS_COND})
            WITH CHECK ({_RLS_COND});
    """)

    # ──────────────────────────────────────────────────────────────────
    # standard_city_tiers — 城市级别映射
    # ──────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS standard_city_tiers (
            id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id   UUID        NOT NULL,
            city_name   VARCHAR(50) NOT NULL,
            city_code   VARCHAR(10),
            province    VARCHAR(20),
            tier        VARCHAR(10) NOT NULL,
            is_system   BOOLEAN     DEFAULT false,
            created_at  TIMESTAMPTZ DEFAULT now()
        );

        COMMENT ON TABLE standard_city_tiers IS
            '城市级别映射：将城市名称映射到差标城市级别（tier1/tier2/tier3/other），支持系统预置和租户自定义';
        COMMENT ON COLUMN standard_city_tiers.city_name IS
            '城市名称，如 北京/上海/成都；与 UNIQUE(tenant_id, city_name) 约束配合确保每租户不重复';
        COMMENT ON COLUMN standard_city_tiers.city_code IS
            '行政区划代码（民政部标准），如 110000=北京市；NULL 表示未维护代码';
        COMMENT ON COLUMN standard_city_tiers.tier IS
            '城市级别：tier1=一线 / tier2=二线 / tier3=三线 / other=其他；用于差标规则匹配';
        COMMENT ON COLUMN standard_city_tiers.is_system IS
            '是否为系统预置数据；true=系统内置（禁止租户删除），false=租户自定义（可编辑删除）';

        CREATE UNIQUE INDEX IF NOT EXISTS uq_standard_city_tiers_tenant_city
            ON standard_city_tiers (tenant_id, city_name);

        CREATE INDEX IF NOT EXISTS ix_standard_city_tiers_tenant_tier
            ON standard_city_tiers (tenant_id, tier);
    """)

    op.execute("ALTER TABLE standard_city_tiers ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE standard_city_tiers FORCE ROW LEVEL SECURITY;")
    op.execute(f"""
        CREATE POLICY standard_city_tiers_rls ON standard_city_tiers
            USING ({_RLS_COND})
            WITH CHECK ({_RLS_COND});
    """)

    # ──────────────────────────────────────────────────────────────────
    # 种子数据 — 系统预置城市级别
    # 注意：以下是系统级预置数据，is_system=true
    # 实际写入时 tenant_id 由应用层在初始化时按租户复制，此处仅作结构示例
    # ──────────────────────────────────────────────────────────────────
    op.execute("""
        INSERT INTO standard_city_tiers (id, tenant_id, city_name, city_code, province, tier, is_system)
        VALUES
          -- 一线城市 tier1
          (gen_random_uuid(), '00000000-0000-0000-0000-000000000001'::uuid, '北京', '110000', '北京市', 'tier1', true),
          (gen_random_uuid(), '00000000-0000-0000-0000-000000000001'::uuid, '上海', '310000', '上海市', 'tier1', true),
          (gen_random_uuid(), '00000000-0000-0000-0000-000000000001'::uuid, '广州', '440100', '广东省', 'tier1', true),
          (gen_random_uuid(), '00000000-0000-0000-0000-000000000001'::uuid, '深圳', '440300', '广东省', 'tier1', true),
          -- 二线城市 tier2（10个代表城市）
          (gen_random_uuid(), '00000000-0000-0000-0000-000000000001'::uuid, '成都', '510100', '四川省', 'tier2', true),
          (gen_random_uuid(), '00000000-0000-0000-0000-000000000001'::uuid, '杭州', '330100', '浙江省', 'tier2', true),
          (gen_random_uuid(), '00000000-0000-0000-0000-000000000001'::uuid, '重庆', '500000', '重庆市', 'tier2', true),
          (gen_random_uuid(), '00000000-0000-0000-0000-000000000001'::uuid, '武汉', '420100', '湖北省', 'tier2', true),
          (gen_random_uuid(), '00000000-0000-0000-0000-000000000001'::uuid, '西安', '610100', '陕西省', 'tier2', true),
          (gen_random_uuid(), '00000000-0000-0000-0000-000000000001'::uuid, '南京', '320100', '江苏省', 'tier2', true),
          (gen_random_uuid(), '00000000-0000-0000-0000-000000000001'::uuid, '天津', '120000', '天津市', 'tier2', true),
          (gen_random_uuid(), '00000000-0000-0000-0000-000000000001'::uuid, '苏州', '320500', '江苏省', 'tier2', true),
          (gen_random_uuid(), '00000000-0000-0000-0000-000000000001'::uuid, '长沙', '430100', '湖南省', 'tier2', true),
          (gen_random_uuid(), '00000000-0000-0000-0000-000000000001'::uuid, '郑州', '410100', '河南省', 'tier2', true);
        -- tier3 为其他所有城市，默认值
    """)


def downgrade() -> None:
    # 按依赖顺序反向删除（先删叶子表，后删被引用表）

    # standard_city_tiers
    op.execute("DROP POLICY IF EXISTS standard_city_tiers_rls ON standard_city_tiers;")
    op.execute("DROP TABLE IF EXISTS standard_city_tiers CASCADE;")

    # expense_standards
    op.execute("DROP POLICY IF EXISTS expense_standards_rls ON expense_standards;")
    op.execute("DROP TABLE IF EXISTS expense_standards CASCADE;")

    # expense_notifications
    op.execute("DROP POLICY IF EXISTS expense_notifications_rls ON expense_notifications;")
    op.execute("DROP TABLE IF EXISTS expense_notifications CASCADE;")
