"""v031: 新增 AB 测试框架核心表

新建表：
  ab_tests              — AB测试实验定义
  ab_test_assignments   — 用户分组记录（唯一约束 test_id + customer_id）

两张表均包含：
  id, tenant_id, created_at, updated_at, is_deleted（TenantBase 标准字段）

索引：
  idx_ab_tests_tenant_status            — 按租户+状态列举实验
  idx_ab_tests_campaign                 — 按关联活动查找实验
  idx_ab_tests_journey                  — 按关联旅程查找实验
  uq_ab_test_assignments_test_customer  — UNIQUE 保证幂等分组
  idx_ab_test_assignments_test_id       — 按实验查所有分配（统计用）
  idx_ab_test_assignments_customer      — 按客户查历史参与
  idx_ab_test_assignments_converted     — 按转化状态过滤

RLS 策略：
  使用 v006+ 标准安全模式（app.tenant_id），禁止 NULL 绕过。

Revision ID: v031
Revises: v030
Create Date: 2026-03-30
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "v032"
down_revision = "v031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. ab_tests 表
    # ------------------------------------------------------------------
    op.create_table(
        "ab_tests",
        # TenantBase 标准字段
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False,
                  comment="租户ID，RLS 隔离"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),

        # 业务字段
        sa.Column("name", sa.String(200), nullable=False,
                  comment="实验名称，如：生日祝福文案AB测试"),
        sa.Column("campaign_id", sa.String(64), nullable=True,
                  comment="关联的营销活动ID（可选）"),
        sa.Column("journey_id", sa.String(64), nullable=True,
                  comment="关联的营销旅程ID（可选）"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft",
                  comment="draft | running | paused | completed"),
        sa.Column("split_type", sa.String(20), nullable=False, server_default="random",
                  comment="random | rfm_based | store_based"),
        sa.Column("variants", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  server_default="[]",
                  comment="变体列表 [{variant, name, weight, content}]"),
        sa.Column("primary_metric", sa.String(30), nullable=False,
                  server_default="conversion_rate",
                  comment="conversion_rate | revenue | click_rate"),
        sa.Column("min_sample_size", sa.Integer(), nullable=False,
                  server_default="100",
                  comment="每组最小样本量"),
        sa.Column("confidence_level", sa.Float(), nullable=False,
                  server_default="0.95",
                  comment="置信水平，默认 0.95"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True,
                  comment="实验开始时间"),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True,
                  comment="实验结束时间"),
        sa.Column("winner_variant", sa.String(10), nullable=True,
                  comment="统计显著后的胜出变体（A / B）"),

        comment="AB测试实验表 — 定义变体内容与分流规则",
    )

    # ab_tests 索引
    op.create_index("idx_ab_tests_tenant_status", "ab_tests",
                    ["tenant_id", "status"])
    op.create_index("idx_ab_tests_campaign", "ab_tests",
                    ["tenant_id", "campaign_id"])
    op.create_index("idx_ab_tests_journey", "ab_tests",
                    ["tenant_id", "journey_id"])

    # ab_tests RLS（app.tenant_id 标准安全模式）
    op.execute("ALTER TABLE ab_tests ENABLE ROW LEVEL SECURITY;")
    op.execute("""
        CREATE POLICY ab_tests_tenant_isolation ON ab_tests
            USING (tenant_id = current_setting('app.tenant_id')::uuid);
    """)

    # ------------------------------------------------------------------
    # 2. ab_test_assignments 表
    # ------------------------------------------------------------------
    op.create_table(
        "ab_test_assignments",
        # TenantBase 标准字段
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False,
                  comment="租户ID，RLS 隔离"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),

        # 业务字段
        sa.Column("test_id", postgresql.UUID(as_uuid=True), nullable=False,
                  comment="所属AB测试 UUID"),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False,
                  comment="被分配的客户 UUID"),
        sa.Column("variant", sa.String(10), nullable=False,
                  comment="分配到的变体：A 或 B"),

        # 转化追踪
        sa.Column("is_converted", sa.Boolean(), nullable=False,
                  server_default=sa.text("false"),
                  comment="是否在实验期间内产生转化"),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=True,
                  comment="转化关联的订单 UUID"),
        sa.Column("order_amount_fen", sa.Integer(), nullable=True,
                  comment="转化订单金额（分）"),
        sa.Column("converted_at", sa.DateTime(timezone=True), nullable=True,
                  comment="转化时间"),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False,
                  comment="分配到变体的时间"),

        comment="AB测试用户分组记录 — 幂等分配，追踪转化",
    )

    # ab_test_assignments 唯一约束（幂等分组核心）
    op.create_unique_constraint(
        "uq_ab_test_assignments_test_customer",
        "ab_test_assignments",
        ["test_id", "customer_id"],
    )

    # ab_test_assignments 索引
    op.create_index("idx_ab_test_assignments_test_id", "ab_test_assignments",
                    ["tenant_id", "test_id"])
    op.create_index("idx_ab_test_assignments_customer", "ab_test_assignments",
                    ["tenant_id", "customer_id"])
    op.create_index("idx_ab_test_assignments_converted", "ab_test_assignments",
                    ["tenant_id", "test_id", "is_converted"])

    # ab_test_assignments RLS
    op.execute("ALTER TABLE ab_test_assignments ENABLE ROW LEVEL SECURITY;")
    op.execute("""
        CREATE POLICY ab_test_assignments_tenant_isolation ON ab_test_assignments
            USING (tenant_id = current_setting('app.tenant_id')::uuid);
    """)


def downgrade() -> None:
    # ------------------------------------------------------------------
    # 删除 ab_test_assignments
    # ------------------------------------------------------------------
    op.execute("DROP POLICY IF EXISTS ab_test_assignments_tenant_isolation ON ab_test_assignments;")
    op.drop_index("idx_ab_test_assignments_converted", table_name="ab_test_assignments")
    op.drop_index("idx_ab_test_assignments_customer", table_name="ab_test_assignments")
    op.drop_index("idx_ab_test_assignments_test_id", table_name="ab_test_assignments")
    op.drop_constraint("uq_ab_test_assignments_test_customer", "ab_test_assignments",
                       type_="unique")
    op.drop_table("ab_test_assignments")

    # ------------------------------------------------------------------
    # 删除 ab_tests
    # ------------------------------------------------------------------
    op.execute("DROP POLICY IF EXISTS ab_tests_tenant_isolation ON ab_tests;")
    op.drop_index("idx_ab_tests_journey", table_name="ab_tests")
    op.drop_index("idx_ab_tests_campaign", table_name="ab_tests")
    op.drop_index("idx_ab_tests_tenant_status", table_name="ab_tests")
    op.drop_table("ab_tests")
