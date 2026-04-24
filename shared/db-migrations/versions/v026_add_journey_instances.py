"""v026: 添加旅程实例表（journey_instances）

将旅程实例从内存 dict 迁移到数据库持久化存储，解决服务重启后数据丢失问题。

新增表：
  journey_instances — 每行代表一个会员在某条营销旅程中的执行进度

索引：
  - (status, next_execute_at, tenant_id)  — 执行器 tick 轮询用
  - (journey_id, customer_id, tenant_id)  — 防重复触发查重用
  - 部分唯一索引：(journey_id, customer_id, tenant_id) WHERE status='running'
    保证同一会员在同一旅程中只有一个运行中实例

RLS 策略：
  使用 v006+ 标准安全模式（4 操作 + NULL 值 guard + FORCE ROW LEVEL SECURITY）
  current_setting('app.tenant_id', TRUE) IS NOT NULL
  AND current_setting('app.tenant_id', TRUE) <> ''
  AND tenant_id = current_setting('app.tenant_id')::UUID

Revision ID: v026
Revises: v025
Create Date: 2026-03-30
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "v026"
down_revision = "v025"
branch_labels = None
depends_on = None

# RLS 条件（v006+ 标准模式）
_RLS_COND = (
    "current_setting('app.tenant_id', TRUE) IS NOT NULL "
    "AND current_setting('app.tenant_id', TRUE) <> '' "
    "AND tenant_id = current_setting('app.tenant_id')::UUID"
)


def upgrade() -> None:
    # ----------------------------------------------------------------
    # 1. 创建 journey_instances 表
    # ----------------------------------------------------------------
    op.create_table(
        "journey_instances",
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
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        # 关联字段
        sa.Column(
            "journey_id",
            sa.String(64),
            nullable=False,
            comment="旅程ID（来自 journey_orchestrator 内存 key，8位UUID前缀）",
        ),
        sa.Column(
            "customer_id",
            UUID(as_uuid=True),
            nullable=False,
            comment="目标会员 UUID",
        ),
        # 执行状态
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="running",
            comment="running | completed | failed | paused",
        ),
        sa.Column(
            "current_node_id",
            sa.String(64),
            nullable=True,
            comment="当前待执行节点ID；NULL 表示旅程已无下一节点",
        ),
        sa.Column(
            "next_execute_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="下次允许执行的最早时间（wait 节点会推迟此时间）",
        ),
        # 执行统计
        sa.Column(
            "retry_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="当前节点重试次数，超过 _MAX_RETRY 后转为 failed",
        ),
        sa.Column(
            "last_error",
            sa.Text(),
            nullable=True,
            comment="最近一次错误描述",
        ),
        sa.Column(
            "completed_nodes",
            JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
            comment="已成功执行的节点 ID 列表（JSONB array of str）",
        ),
        # 生命周期时间戳
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="旅程实例创建/启动时间",
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="旅程完成或失败时间",
        ),
        comment="旅程实例表 — 每行代表一个会员在某条营销旅程中的执行进度",
    )

    # ----------------------------------------------------------------
    # 2. 普通索引
    # ----------------------------------------------------------------

    # 执行器轮询索引：查 running + 到期实例
    op.create_index(
        "idx_journey_instances_poll",
        "journey_instances",
        ["status", "next_execute_at", "tenant_id"],
    )

    # 防重复触发查重索引
    op.create_index(
        "idx_journey_instances_dedup",
        "journey_instances",
        ["journey_id", "customer_id", "tenant_id"],
    )

    # tenant_id 单列索引（RLS 基础索引）
    op.create_index(
        "idx_journey_instances_tenant_id",
        "journey_instances",
        ["tenant_id"],
    )

    # ----------------------------------------------------------------
    # 3. 部分唯一索引：同一会员在同一旅程只能有一个 running 实例
    #    使用 op.execute 直接执行 DDL，SQLAlchemy UniqueConstraint
    #    不支持带 WHERE 条件的局部唯一索引。
    # ----------------------------------------------------------------
    op.execute("""
        CREATE UNIQUE INDEX uq_journey_instance_running
            ON journey_instances (journey_id, customer_id, tenant_id)
            WHERE status = 'running';
    """)

    # ----------------------------------------------------------------
    # 4. RLS — journey_instances
    # ----------------------------------------------------------------
    op.execute("ALTER TABLE journey_instances ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE journey_instances FORCE ROW LEVEL SECURITY;")

    op.execute(f"""
        CREATE POLICY rls_journey_instances_select
            ON journey_instances FOR SELECT
            USING ({_RLS_COND});
    """)
    op.execute(f"""
        CREATE POLICY rls_journey_instances_insert
            ON journey_instances FOR INSERT
            WITH CHECK ({_RLS_COND});
    """)
    op.execute(f"""
        CREATE POLICY rls_journey_instances_update
            ON journey_instances FOR UPDATE
            USING ({_RLS_COND})
            WITH CHECK ({_RLS_COND});
    """)
    op.execute(f"""
        CREATE POLICY rls_journey_instances_delete
            ON journey_instances FOR DELETE
            USING ({_RLS_COND});
    """)


def downgrade() -> None:
    # 先删 RLS 策略
    for policy in [
        "rls_journey_instances_select",
        "rls_journey_instances_insert",
        "rls_journey_instances_update",
        "rls_journey_instances_delete",
    ]:
        op.execute(f"DROP POLICY IF EXISTS {policy} ON journey_instances;")
    op.execute("ALTER TABLE journey_instances DISABLE ROW LEVEL SECURITY;")

    # 删部分唯一索引
    op.execute("DROP INDEX IF EXISTS uq_journey_instance_running;")

    # 删普通索引
    for idx in [
        "idx_journey_instances_tenant_id",
        "idx_journey_instances_dedup",
        "idx_journey_instances_poll",
    ]:
        op.drop_index(idx, table_name="journey_instances")

    # 删表
    op.drop_table("journey_instances")
