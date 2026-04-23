"""v267 — 宴会商机漏斗模型

对应规划：docs/reservation-roadmap-2026-q2.md §6 Sprint R1
依据路线图任务：
  宴会商机漏斗模型
  全部商机 → 商机阶段 → 订单阶段 → 失效 四阶段漏斗
  按销售经理维度 / 渠道归因统计

本迁移只建表，不含业务路由。banquet_growth Agent 在 Sprint R2 接入
lead_funnel_analytics / source_attribution 两个 action。

表清单：
  banquet_leads — 宴会商机主表

金额单位：分（fen，整数，对齐 CLAUDE.md §15）
RLS：tenant_id = app.tenant_id（对齐 CLAUDE.md §14）
事件：BanquetLeadEventType.CREATED / STAGE_CHANGED / CONVERTED

Revision: v267
Revises: v266
Create Date: 2026-04-23
"""

from alembic import op

revision = "v267"
down_revision = "v266"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # 1. 枚举类型
    # ─────────────────────────────────────────────────────────────────
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE banquet_type_enum AS ENUM (
                'wedding',
                'birthday',
                'corporate',
                'baby_banquet',
                'reunion',
                'graduation'
            );
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )

    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE banquet_source_channel_enum AS ENUM (
                'booking_desk',
                'referral',
                'hunliji',
                'dianping',
                'internal',
                'meituan',
                'gaode',
                'baidu'
            );
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )

    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE banquet_lead_stage_enum AS ENUM (
                'all',
                'opportunity',
                'order',
                'invalid'
            );
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )

    # ─────────────────────────────────────────────────────────────────
    # 2. banquet_leads 主表
    # ─────────────────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS banquet_leads (
            lead_id                 UUID                            NOT NULL DEFAULT gen_random_uuid(),
            tenant_id               UUID                            NOT NULL,
            store_id                UUID,
            customer_id             UUID                            NOT NULL,
            sales_employee_id       UUID,
            banquet_type            banquet_type_enum               NOT NULL,
            source_channel          banquet_source_channel_enum     NOT NULL DEFAULT 'booking_desk',
            stage                   banquet_lead_stage_enum         NOT NULL DEFAULT 'all',
            estimated_amount_fen    BIGINT                          NOT NULL DEFAULT 0,
            estimated_tables        INTEGER                         NOT NULL DEFAULT 0,
            scheduled_date          DATE,
            stage_changed_at        TIMESTAMPTZ                     NOT NULL DEFAULT NOW(),
            previous_stage          banquet_lead_stage_enum,
            invalidation_reason     VARCHAR(200),
            converted_reservation_id UUID,
            metadata                JSONB                           NOT NULL DEFAULT '{}',
            created_by              UUID,
            created_at              TIMESTAMPTZ                     NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ                     NOT NULL DEFAULT NOW(),
            CONSTRAINT banquet_leads_pkey PRIMARY KEY (lead_id),
            CONSTRAINT banquet_leads_amount_chk CHECK (estimated_amount_fen >= 0),
            CONSTRAINT banquet_leads_tables_chk CHECK (estimated_tables >= 0),
            CONSTRAINT banquet_leads_invalid_chk
                CHECK (
                    stage <> 'invalid' OR invalidation_reason IS NOT NULL
                )
        )
        """
    )

    # 核心索引：按 (tenant_id, stage, sales_employee_id) 查漏斗
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_banquet_leads_stage_sales
            ON banquet_leads (tenant_id, stage, sales_employee_id)
        """
    )
    # 索引：按客户维度查历史商机
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_banquet_leads_customer
            ON banquet_leads (tenant_id, customer_id)
        """
    )
    # 索引：按渠道做 source_attribution
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_banquet_leads_source
            ON banquet_leads (tenant_id, source_channel, stage)
        """
    )
    # 索引：按预定日期做档期视图
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_banquet_leads_scheduled
            ON banquet_leads (tenant_id, scheduled_date)
            WHERE scheduled_date IS NOT NULL
        """
    )
    # 索引：按 stage_changed_at 做漏斗时长分析
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_banquet_leads_stage_changed
            ON banquet_leads (tenant_id, stage_changed_at DESC)
        """
    )
    # GIN 索引：metadata 查询
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_banquet_leads_metadata_gin
            ON banquet_leads USING GIN (metadata)
        """
    )

    # ─────────────────────────────────────────────────────────────────
    # 3. RLS 多租户隔离
    # ─────────────────────────────────────────────────────────────────
    op.execute("ALTER TABLE banquet_leads ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE banquet_leads FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS banquet_leads_tenant ON banquet_leads")
    op.execute(
        """
        CREATE POLICY banquet_leads_tenant ON banquet_leads
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID)
        """
    )

    # ─────────────────────────────────────────────────────────────────
    # 4. 注释
    # ─────────────────────────────────────────────────────────────────
    op.execute(
        "COMMENT ON TABLE banquet_leads IS "
        "'宴会商机漏斗 — 全部商机→商机→订单→失效（R1 新增，对标食尚订）'"
    )
    op.execute(
        "COMMENT ON COLUMN banquet_leads.stage IS "
        "'漏斗阶段：all/opportunity/order/invalid'"
    )
    op.execute(
        "COMMENT ON COLUMN banquet_leads.source_channel IS "
        "'渠道归因：booking_desk/referral/hunliji/dianping/internal/meituan/gaode/baidu'"
    )
    op.execute(
        "COMMENT ON COLUMN banquet_leads.estimated_amount_fen IS "
        "'预估金额（分/整数，对齐金额公约）'"
    )
    op.execute(
        "COMMENT ON COLUMN banquet_leads.converted_reservation_id IS "
        "'转正式预订后指向 reservations.id（stage=order 时写入）'"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS banquet_leads CASCADE")
    op.execute("DROP TYPE IF EXISTS banquet_lead_stage_enum")
    op.execute("DROP TYPE IF EXISTS banquet_source_channel_enum")
    op.execute("DROP TYPE IF EXISTS banquet_type_enum")
