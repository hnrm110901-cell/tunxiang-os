"""v029: 添加 ROI 归因表（marketing_touches + attribution_summaries）

解决的问题：某笔订单是哪个营销活动/旅程/渠道带来的？

新增表：
  marketing_touches      — 每次营销触达记一条，支持转化回写
  attribution_summaries  — 按活动维度的每日 ROI 汇总快照

索引设计：
  marketing_touches：
    (tenant_id, customer_id, touched_at)  — 归因查询核心路径（避免全表扫描）
    (tenant_id, source_id, touched_at)    — 按活动汇总
    (tenant_id, is_converted, touched_at) — 转化率统计

  attribution_summaries：
    (tenant_id, source_id, stat_date)     — 按活动查每日数据
    (tenant_id, stat_date)                — 仪表盘按日期聚合
    (tenant_id, source_type, stat_date)   — 按来源类型过滤

RLS 策略：
  使用 v006+ 标准安全模式（4 操作 + NULL guard + FORCE ROW LEVEL SECURITY）
  current_setting('app.tenant_id', TRUE) IS NOT NULL
  AND current_setting('app.tenant_id', TRUE) <> ''
  AND tenant_id = current_setting('app.tenant_id')::UUID

Revision ID: v029
Revises: v026
Create Date: 2026-03-30
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "v029"
down_revision = "v028"
branch_labels = None
depends_on = None

# RLS 条件（v006+ 标准模式，禁止 NULL 绕过）
_RLS_COND = (
    "current_setting('app.tenant_id', TRUE) IS NOT NULL "
    "AND current_setting('app.tenant_id', TRUE) <> '' "
    "AND tenant_id = current_setting('app.tenant_id')::UUID"
)

# 需要配置 RLS 的表
_TABLES = ["marketing_touches", "attribution_summaries"]


def upgrade() -> None:
    # ----------------------------------------------------------------
    # 1. 创建 marketing_touches 表
    # ----------------------------------------------------------------
    op.create_table(
        "marketing_touches",
        # 基础字段（TenantBase）
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        # 客户关联
        sa.Column(
            "customer_id",
            UUID(as_uuid=True),
            nullable=False,
            comment="客户 UUID",
        ),
        # 来源信息
        sa.Column(
            "touch_type",
            sa.String(20),
            nullable=False,
            comment="campaign | journey | referral | manual",
        ),
        sa.Column(
            "source_id",
            sa.String(64),
            nullable=False,
            comment="来源ID：campaign_id / journey_id / referral_campaign_id",
        ),
        sa.Column(
            "source_name",
            sa.String(200),
            nullable=False,
            server_default="",
            comment="来源名称（冗余字段，避免关联查询）",
        ),
        sa.Column(
            "channel",
            sa.String(30),
            nullable=False,
            comment="触达渠道：wecom | sms | miniapp | pos_receipt",
        ),
        # 内容信息
        sa.Column(
            "message_title",
            sa.String(200),
            nullable=True,
            comment="消息标题",
        ),
        sa.Column(
            "offer_id",
            sa.String(64),
            nullable=True,
            comment="附带的优惠券/活动ID",
        ),
        # 转化追踪
        sa.Column(
            "is_converted",
            sa.Boolean(),
            nullable=False,
            server_default="false",
            comment="是否在归因窗口内产生订单",
        ),
        sa.Column(
            "order_id",
            UUID(as_uuid=True),
            nullable=True,
            comment="归因的订单 UUID",
        ),
        sa.Column(
            "order_amount_fen",
            sa.Integer(),
            nullable=True,
            comment="归因订单金额（分）",
        ),
        sa.Column(
            "converted_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="转化（下单）时间",
        ),
        # 触达时间
        sa.Column(
            "touched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="触达发生时间",
        ),
        comment="营销触达记录表 — 每次推送/触达记一条，支持归因回写",
    )

    # ----------------------------------------------------------------
    # 2. marketing_touches 索引
    # ----------------------------------------------------------------

    # 归因查询核心索引：按客户 + 触达时间（避免全表扫描）
    op.create_index(
        "idx_marketing_touches_customer_touched_at",
        "marketing_touches",
        ["tenant_id", "customer_id", "touched_at"],
    )

    # 按活动来源汇总索引
    op.create_index(
        "idx_marketing_touches_source",
        "marketing_touches",
        ["tenant_id", "source_id", "touched_at"],
    )

    # 转化状态过滤索引
    op.create_index(
        "idx_marketing_touches_converted",
        "marketing_touches",
        ["tenant_id", "is_converted", "touched_at"],
    )

    # tenant_id 单列索引（RLS 基础）
    op.create_index(
        "idx_marketing_touches_tenant_id",
        "marketing_touches",
        ["tenant_id"],
    )

    # ----------------------------------------------------------------
    # 3. 创建 attribution_summaries 表
    # ----------------------------------------------------------------
    op.create_table(
        "attribution_summaries",
        # 基础字段（TenantBase）
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        # 来源维度
        sa.Column(
            "source_type",
            sa.String(20),
            nullable=False,
            comment="campaign | journey | referral",
        ),
        sa.Column(
            "source_id",
            sa.String(64),
            nullable=False,
            comment="来源ID",
        ),
        sa.Column(
            "source_name",
            sa.String(200),
            nullable=False,
            server_default="",
            comment="来源名称（冗余）",
        ),
        # 日期维度
        sa.Column(
            "stat_date",
            sa.Date(),
            nullable=False,
            comment="统计日期（UTC）",
        ),
        # 触达指标
        sa.Column(
            "total_touches",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="触达记录总数",
        ),
        sa.Column(
            "unique_customers",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="触达去重客户数",
        ),
        # 转化指标
        sa.Column(
            "converted_customers",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="归因窗口内下单客户数",
        ),
        sa.Column(
            "conversion_rate",
            sa.Float(),
            nullable=False,
            server_default="0.0",
            comment="转化率 = converted_customers / unique_customers",
        ),
        # 收益与成本
        sa.Column(
            "attributed_revenue_fen",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="归因收入（分）",
        ),
        sa.Column(
            "cost_fen",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="发出的优惠总价值（分）",
        ),
        sa.Column(
            "roi",
            sa.Float(),
            nullable=False,
            server_default="0.0",
            comment="ROI = (revenue - cost) / cost",
        ),
        # 归因模型
        sa.Column(
            "model",
            sa.String(20),
            nullable=False,
            server_default="last_touch",
            comment="last_touch | first_touch | linear",
        ),
        comment="归因汇总表 — 按活动维度每日 ROI 指标快照",
    )

    # ----------------------------------------------------------------
    # 4. attribution_summaries 索引
    # ----------------------------------------------------------------

    # 主查询路径：按来源 + 日期
    op.create_index(
        "idx_attribution_summaries_source_date",
        "attribution_summaries",
        ["tenant_id", "source_id", "stat_date"],
    )

    # 仪表盘按日期范围汇总
    op.create_index(
        "idx_attribution_summaries_date",
        "attribution_summaries",
        ["tenant_id", "stat_date"],
    )

    # 按 source_type 过滤（区分活动/旅程/裂变）
    op.create_index(
        "idx_attribution_summaries_source_type",
        "attribution_summaries",
        ["tenant_id", "source_type", "stat_date"],
    )

    # tenant_id 单列索引（RLS 基础）
    op.create_index(
        "idx_attribution_summaries_tenant_id",
        "attribution_summaries",
        ["tenant_id"],
    )

    # ----------------------------------------------------------------
    # 5. RLS — marketing_touches
    # ----------------------------------------------------------------
    op.execute("ALTER TABLE marketing_touches ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE marketing_touches FORCE ROW LEVEL SECURITY;")

    op.execute(f"""
        CREATE POLICY rls_marketing_touches_select
            ON marketing_touches FOR SELECT
            USING ({_RLS_COND});
    """)
    op.execute(f"""
        CREATE POLICY rls_marketing_touches_insert
            ON marketing_touches FOR INSERT
            WITH CHECK ({_RLS_COND});
    """)
    op.execute(f"""
        CREATE POLICY rls_marketing_touches_update
            ON marketing_touches FOR UPDATE
            USING ({_RLS_COND})
            WITH CHECK ({_RLS_COND});
    """)
    op.execute(f"""
        CREATE POLICY rls_marketing_touches_delete
            ON marketing_touches FOR DELETE
            USING ({_RLS_COND});
    """)

    # ----------------------------------------------------------------
    # 6. RLS — attribution_summaries
    # ----------------------------------------------------------------
    op.execute("ALTER TABLE attribution_summaries ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE attribution_summaries FORCE ROW LEVEL SECURITY;")

    op.execute(f"""
        CREATE POLICY rls_attribution_summaries_select
            ON attribution_summaries FOR SELECT
            USING ({_RLS_COND});
    """)
    op.execute(f"""
        CREATE POLICY rls_attribution_summaries_insert
            ON attribution_summaries FOR INSERT
            WITH CHECK ({_RLS_COND});
    """)
    op.execute(f"""
        CREATE POLICY rls_attribution_summaries_update
            ON attribution_summaries FOR UPDATE
            USING ({_RLS_COND})
            WITH CHECK ({_RLS_COND});
    """)
    op.execute(f"""
        CREATE POLICY rls_attribution_summaries_delete
            ON attribution_summaries FOR DELETE
            USING ({_RLS_COND});
    """)


def downgrade() -> None:
    # 逆序：先删 RLS 再删索引再删表

    # attribution_summaries RLS
    for policy in [
        "rls_attribution_summaries_select",
        "rls_attribution_summaries_insert",
        "rls_attribution_summaries_update",
        "rls_attribution_summaries_delete",
    ]:
        op.execute(f"DROP POLICY IF EXISTS {policy} ON attribution_summaries;")
    op.execute("ALTER TABLE attribution_summaries DISABLE ROW LEVEL SECURITY;")

    # marketing_touches RLS
    for policy in [
        "rls_marketing_touches_select",
        "rls_marketing_touches_insert",
        "rls_marketing_touches_update",
        "rls_marketing_touches_delete",
    ]:
        op.execute(f"DROP POLICY IF EXISTS {policy} ON marketing_touches;")
    op.execute("ALTER TABLE marketing_touches DISABLE ROW LEVEL SECURITY;")

    # attribution_summaries 索引
    for idx in [
        "idx_attribution_summaries_tenant_id",
        "idx_attribution_summaries_source_type",
        "idx_attribution_summaries_date",
        "idx_attribution_summaries_source_date",
    ]:
        op.drop_index(idx, table_name="attribution_summaries")

    # marketing_touches 索引
    for idx in [
        "idx_marketing_touches_tenant_id",
        "idx_marketing_touches_converted",
        "idx_marketing_touches_source",
        "idx_marketing_touches_customer_touched_at",
    ]:
        op.drop_index(idx, table_name="marketing_touches")

    # 删表
    op.drop_table("attribution_summaries")
    op.drop_table("marketing_touches")
