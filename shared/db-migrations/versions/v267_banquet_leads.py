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
    # 2. banquet_leads 主表 — 类 A 副本去重 (B'-4, 2026-05-09)
    #
    # 原 v267 设计的 schema (lead_id PK + ENUM 列 + customer_id FK) 与生产
    # ORM model (services/tx-trade/src/models/banquet_lead.py) **不匹配**。
    # 生产用 v315_banquet_leads.py 的 schema (id PK + lead_no + status
    # VARCHAR + 22 列含 customer_name / phone / event_type 等)。
    #
    # 仅保留本文件的 3 个 ENUM 类型创建（被 v282_banquet_contracts.py
    # references），删除 banquet_leads 表创建块 + 索引 + RLS + COMMENT。
    # 真表创建走 v315_banquet_leads（canonical）。
    # ─────────────────────────────────────────────────────────────────


def downgrade() -> None:
    # banquet_leads 表的 DROP 由 v315 downgrade 负责（canonical 持有者）
    # 仅 DROP 本文件 upgrade() 中创建的 3 个 ENUM 类型
    op.execute("DROP TYPE IF EXISTS banquet_lead_stage_enum")
    op.execute("DROP TYPE IF EXISTS banquet_source_channel_enum")
    op.execute("DROP TYPE IF EXISTS banquet_type_enum")
