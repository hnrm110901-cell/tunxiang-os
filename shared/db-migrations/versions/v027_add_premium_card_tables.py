"""v027: 添加付费会员卡三张表（次卡/周期卡体系）

新增三张表：
  premium_card_templates  — 付费卡模板（总部配置，count_card/period_card）
  premium_cards           — 会员持有的付费卡实例
  premium_card_usages     — 卡使用记录（核销/权益使用/续费）

索引：
  premium_card_templates:
    - (tenant_id)
    - (tenant_id, is_active)
    - (tenant_id, card_type)
  premium_cards:
    - (customer_id, status, tenant_id)    — 查某人有效卡
    - (template_id, tenant_id)            — 按模板查卡
    - (tenant_id, status)
    - (tenant_id, next_renewal_at)        — 续费提醒任务
    - (tenant_id, expires_at)             — 到期提醒任务
  premium_card_usages:
    - (card_id, tenant_id)
    - (customer_id, tenant_id)
    - (tenant_id, used_at)

RLS 策略：
  使用 v006+ 标准安全模式（4 操作 + NULL 值 guard + FORCE ROW LEVEL SECURITY）
  current_setting('app.tenant_id', TRUE) IS NOT NULL
  AND current_setting('app.tenant_id', TRUE) <> ''
  AND tenant_id = current_setting('app.tenant_id')::UUID

Revision ID: v027
Revises: v025
Create Date: 2026-03-30
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "v027"
down_revision = "v026"
branch_labels = None
depends_on = None

# RLS 条件（v006+ 标准模式）
_RLS_COND = (
    "current_setting('app.tenant_id', TRUE) IS NOT NULL "
    "AND current_setting('app.tenant_id', TRUE) <> '' "
    "AND tenant_id = current_setting('app.tenant_id')::UUID"
)

# 所有表名
_T_TEMPLATES = "premium_card_templates"
_T_CARDS = "premium_cards"
_T_USAGES = "premium_card_usages"


def _base_cols() -> list:
    """TenantBase 公共列"""
    return [
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
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
    ]


def _rls_4ops(table: str) -> None:
    """为指定表建立标准 4 操作 RLS 策略"""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")

    op.execute(f"""
        CREATE POLICY rls_{table}_select
            ON {table} FOR SELECT
            USING ({_RLS_COND});
    """)
    op.execute(f"""
        CREATE POLICY rls_{table}_insert
            ON {table} FOR INSERT
            WITH CHECK ({_RLS_COND});
    """)
    op.execute(f"""
        CREATE POLICY rls_{table}_update
            ON {table} FOR UPDATE
            USING ({_RLS_COND})
            WITH CHECK ({_RLS_COND});
    """)
    op.execute(f"""
        CREATE POLICY rls_{table}_delete
            ON {table} FOR DELETE
            USING ({_RLS_COND});
    """)


def upgrade() -> None:
    # ────────────────────────────────────────────────────────────
    # 1. premium_card_templates — 付费卡模板
    # ────────────────────────────────────────────────────────────
    op.create_table(
        _T_TEMPLATES,
        *_base_cols(),

        sa.Column("name", sa.String(100), nullable=False, comment="模板名称，如「月度次卡·10次」"),
        sa.Column(
            "card_type", sa.String(20), nullable=False,
            comment="count_card | period_card",
        ),
        sa.Column("price_fen", sa.Integer(), nullable=False, comment="售价（分）"),

        # 次卡专属
        sa.Column("total_uses", sa.Integer(), nullable=True, comment="总次数（次卡）"),

        # 周期卡专属
        sa.Column(
            "period_type", sa.String(20), nullable=True,
            comment="monthly | quarterly | yearly",
        ),

        # 权益配置 JSONB
        # 示例：[{"type":"discount","value":0.9},
        #        {"type":"free_dish","dish_id":"xxx","quota_per_period":1},
        #        {"type":"priority_queue"},{"type":"free_parking"}]
        sa.Column(
            "benefits", JSONB(), nullable=False, server_default="'[]'::jsonb",
            comment="权益配置列表（JSONB）",
        ),

        # 有效天数（次卡用，购买后 N 天内有效）
        sa.Column("valid_days", sa.Integer(), nullable=True, comment="购买后有效天数（次卡）"),

        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true", comment="是否上架"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0", comment="排序"),

        comment="付费卡模板（总部配置）",
    )

    op.create_index("idx_pct_tenant_id", _T_TEMPLATES, ["tenant_id"])
    op.create_index("idx_pct_tenant_active", _T_TEMPLATES, ["tenant_id", "is_active"])
    op.create_index("idx_pct_tenant_card_type", _T_TEMPLATES, ["tenant_id", "card_type"])

    _rls_4ops(_T_TEMPLATES)

    # ────────────────────────────────────────────────────────────
    # 2. premium_cards — 会员持有的付费卡
    # ────────────────────────────────────────────────────────────
    op.create_table(
        _T_CARDS,
        *_base_cols(),

        sa.Column(
            "template_id", UUID(as_uuid=True),
            sa.ForeignKey(f"{_T_TEMPLATES}.id", ondelete="RESTRICT"),
            nullable=True,    # 旧版年卡未关联模板时允许 NULL
            comment="关联模板（null=旧版年卡兼容）",
        ),
        sa.Column("customer_id", UUID(as_uuid=True), nullable=False, comment="持卡会员"),
        sa.Column("store_id", UUID(as_uuid=True), nullable=True, comment="购买门店"),

        sa.Column(
            "card_type", sa.String(20), nullable=False,
            comment="count_card | period_card",
        ),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="active",
            comment="active | expired | cancelled | suspended",
        ),

        # 次卡字段
        sa.Column("remaining_uses", sa.Integer(), nullable=True, comment="剩余次数（次卡）"),
        sa.Column("total_uses", sa.Integer(), nullable=True, comment="购买时总次数（次卡）"),

        # 周期卡字段
        sa.Column("period_start", sa.Date(), nullable=True, comment="当前周期开始日"),
        sa.Column("period_end", sa.Date(), nullable=True, comment="当前周期结束日"),
        sa.Column("next_renewal_at", sa.Date(), nullable=True, comment="下次续费日期"),

        # 有效期
        sa.Column(
            "purchased_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
            comment="购买时间",
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True, comment="到期时间"),

        # 当前周期已用权益（JSONB）
        # 示例：{"free_dish_used": 1, "parking_used": 0}
        sa.Column(
            "period_used_benefits", JSONB(), nullable=False, server_default="'{}'::jsonb",
            comment="当前周期已用权益计数（JSONB）",
        ),

        comment="会员持有的付费卡",
    )

    # 关键索引
    op.create_index(
        "idx_pc_customer_status_tenant",
        _T_CARDS,
        ["customer_id", "status", "tenant_id"],
    )
    op.create_index(
        "idx_pc_template_tenant",
        _T_CARDS,
        ["template_id", "tenant_id"],
        postgresql_where=sa.text("template_id IS NOT NULL"),
    )
    op.create_index("idx_pc_tenant_status", _T_CARDS, ["tenant_id", "status"])
    op.create_index(
        "idx_pc_tenant_next_renewal",
        _T_CARDS,
        ["tenant_id", "next_renewal_at"],
        postgresql_where=sa.text("next_renewal_at IS NOT NULL AND status = 'active'"),
    )
    op.create_index(
        "idx_pc_tenant_expires_at",
        _T_CARDS,
        ["tenant_id", "expires_at"],
        postgresql_where=sa.text("expires_at IS NOT NULL AND status = 'active'"),
    )

    _rls_4ops(_T_CARDS)

    # ────────────────────────────────────────────────────────────
    # 3. premium_card_usages — 使用记录
    # ────────────────────────────────────────────────────────────
    op.create_table(
        _T_USAGES,
        *_base_cols(),

        sa.Column(
            "card_id", UUID(as_uuid=True),
            sa.ForeignKey(f"{_T_CARDS}.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("customer_id", UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", UUID(as_uuid=True), nullable=True),
        sa.Column("order_id", UUID(as_uuid=True), nullable=True),

        sa.Column(
            "usage_type", sa.String(30), nullable=False,
            comment="count_deduct | benefit_use | period_renewal",
        ),
        sa.Column(
            "benefit_type", sa.String(50), nullable=True,
            comment="discount | free_dish | priority_queue 等（benefit_use 时填写）",
        ),

        # 次卡扣次快照
        sa.Column("uses_before", sa.Integer(), nullable=True, comment="扣减前剩余次数"),
        sa.Column("uses_after", sa.Integer(), nullable=True, comment="扣减后剩余次数"),

        sa.Column(
            "used_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
            comment="使用时间",
        ),
        sa.Column("operator_id", UUID(as_uuid=True), nullable=True, comment="操作员"),

        comment="付费卡使用记录",
    )

    op.create_index("idx_pcu_card_tenant", _T_USAGES, ["card_id", "tenant_id"])
    op.create_index("idx_pcu_customer_tenant", _T_USAGES, ["customer_id", "tenant_id"])
    op.create_index("idx_pcu_tenant_used_at", _T_USAGES, ["tenant_id", "used_at"])

    _rls_4ops(_T_USAGES)


def downgrade() -> None:
    # 按依赖顺序反向删除

    for table in [_T_USAGES, _T_CARDS, _T_TEMPLATES]:
        for op_name in ["select", "insert", "update", "delete"]:
            op.execute(f"DROP POLICY IF EXISTS rls_{table}_{op_name} ON {table};")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

    # 删索引
    for idx, tbl in [
        ("idx_pcu_tenant_used_at", _T_USAGES),
        ("idx_pcu_customer_tenant", _T_USAGES),
        ("idx_pcu_card_tenant", _T_USAGES),
        ("idx_pc_tenant_expires_at", _T_CARDS),
        ("idx_pc_tenant_next_renewal", _T_CARDS),
        ("idx_pc_tenant_status", _T_CARDS),
        ("idx_pc_template_tenant", _T_CARDS),
        ("idx_pc_customer_status_tenant", _T_CARDS),
        ("idx_pct_tenant_card_type", _T_TEMPLATES),
        ("idx_pct_tenant_active", _T_TEMPLATES),
        ("idx_pct_tenant_id", _T_TEMPLATES),
    ]:
        op.drop_index(idx, table_name=tbl)

    op.drop_table(_T_USAGES)
    op.drop_table(_T_CARDS)
    op.drop_table(_T_TEMPLATES)
