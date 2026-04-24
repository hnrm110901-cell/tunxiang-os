"""v261 — tx-menu 新增：菜谱方案 V2 + 批量推送 + 门店 Override

新建：
  menu_plans_v2               — 菜谱方案主表（品牌级）
  menu_plan_v2_items          — 方案品项明细
  menu_push_tasks             — 批量推送任务
  menu_push_logs              — 推送执行日志（门店级）
  menu_plan_store_overrides   — 门店价格/可售状态/份量 Override

所有含 tenant_id 的表启用 RLS（app.tenant_id）。

Revision ID: v261
Revises: v260
Create Date: 2026-04-16
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "v261"
down_revision = "v260"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    # ── menu_plans_v2 ─────────────────────────────────────────────────────────
    if "menu_plans_v2" not in existing:
        op.create_table(
            "menu_plans_v2",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("brand_id", UUID(as_uuid=True), nullable=False, comment="所属品牌 ID"),
            sa.Column("name", sa.String(200), nullable=False, comment="方案名称"),
            sa.Column("description", sa.Text, nullable=True, comment="方案描述"),
            sa.Column("effective_date", sa.Date, nullable=True, comment="生效日期（不填则立即生效）"),
            sa.Column(
                "status",
                sa.String(20),
                nullable=False,
                server_default="'draft'",
                comment="draft=草稿 / published=已发布 / archived=已归档",
            ),
            sa.Column("created_by", UUID(as_uuid=True), nullable=True, comment="创建人员工 ID"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        )
        op.create_index("ix_menu_plans_v2_tenant_brand", "menu_plans_v2", ["tenant_id", "brand_id"])
        op.create_index("ix_menu_plans_v2_status", "menu_plans_v2", ["tenant_id", "status"])

    op.execute("ALTER TABLE menu_plans_v2 ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS menu_plans_v2_tenant ON menu_plans_v2;")
    op.execute("""
        CREATE POLICY menu_plans_v2_tenant ON menu_plans_v2
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """)

    # ── menu_plan_v2_items ────────────────────────────────────────────────────
    if "menu_plan_v2_items" not in existing:
        op.create_table(
            "menu_plan_v2_items",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("plan_id", UUID(as_uuid=True), nullable=False, comment="关联 menu_plans_v2.id"),
            sa.Column("dish_id", UUID(as_uuid=True), nullable=False, comment="菜品 ID（逻辑引用 dishes.id）"),
            sa.Column("price_fen", sa.Integer, nullable=True, comment="方案定价（分），NULL 表示沿用菜品原价"),
            sa.Column("is_available", sa.Boolean, nullable=False, server_default="true", comment="是否上架"),
            sa.Column("sort_order", sa.Integer, nullable=False, server_default="0", comment="展示排序"),
            sa.ForeignKeyConstraint(["plan_id"], ["menu_plans_v2.id"], ondelete="CASCADE"),
        )
        op.create_index("ix_menu_plan_v2_items_plan_id", "menu_plan_v2_items", ["plan_id"])
        op.create_index("ix_menu_plan_v2_items_dish_id", "menu_plan_v2_items", ["dish_id"])

    # menu_plan_v2_items 通过 plan_id 关联受 menu_plans_v2 RLS 保护
    # 但仍需独立启用 RLS 并依赖 plan 关联查询；为简化，直接跟随 plan RLS
    op.execute("ALTER TABLE menu_plan_v2_items ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS menu_plan_v2_items_open ON menu_plan_v2_items;")
    op.execute("""
        CREATE POLICY menu_plan_v2_items_open ON menu_plan_v2_items
            USING (
                plan_id IN (
                    SELECT id FROM menu_plans_v2
                    WHERE tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                )
            );
    """)

    # ── menu_push_tasks ───────────────────────────────────────────────────────
    if "menu_push_tasks" not in existing:
        op.create_table(
            "menu_push_tasks",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("plan_id", UUID(as_uuid=True), nullable=True, comment="关联 menu_plans_v2.id"),
            sa.Column("push_mode", sa.String(20), nullable=True, comment="immediate=立即推送 / scheduled=定时推送"),
            sa.Column(
                "scheduled_at",
                sa.TIMESTAMP(timezone=True),
                nullable=True,
                comment="定时推送时间（push_mode=scheduled 时有效）",
            ),
            sa.Column("total_stores", sa.Integer, nullable=False, server_default="0", comment="目标门店总数"),
            sa.Column("queued", sa.Integer, nullable=False, server_default="0", comment="已入队数"),
            sa.Column("success", sa.Integer, nullable=False, server_default="0", comment="推送成功数"),
            sa.Column("failed", sa.Integer, nullable=False, server_default="0", comment="推送失败数"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
            sa.ForeignKeyConstraint(["plan_id"], ["menu_plans_v2.id"], ondelete="SET NULL"),
        )
        op.create_index("ix_menu_push_tasks_tenant", "menu_push_tasks", ["tenant_id"])
        op.create_index("ix_menu_push_tasks_plan_id", "menu_push_tasks", ["plan_id"])

    op.execute("ALTER TABLE menu_push_tasks ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS menu_push_tasks_tenant ON menu_push_tasks;")
    op.execute("""
        CREATE POLICY menu_push_tasks_tenant ON menu_push_tasks
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """)

    # ── menu_push_logs ────────────────────────────────────────────────────────
    if "menu_push_logs" not in existing:
        op.create_table(
            "menu_push_logs",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("task_id", UUID(as_uuid=True), nullable=True, comment="关联 menu_push_tasks.id"),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False, comment="目标门店 ID"),
            sa.Column("status", sa.String(20), nullable=True, comment="queued=已入队 / success=成功 / failed=失败"),
            sa.Column("error_msg", sa.Text, nullable=True, comment="失败错误信息"),
            sa.Column("pushed_at", sa.TIMESTAMP(timezone=True), nullable=True, comment="实际推送时间"),
            sa.ForeignKeyConstraint(["task_id"], ["menu_push_tasks.id"], ondelete="CASCADE"),
        )
        op.create_index("ix_menu_push_logs_task_id", "menu_push_logs", ["task_id"])
        op.create_index("ix_menu_push_logs_store_id", "menu_push_logs", ["store_id"])

    # menu_push_logs 通过 task_id 关联受 menu_push_tasks RLS 保护
    op.execute("ALTER TABLE menu_push_logs ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS menu_push_logs_open ON menu_push_logs;")
    op.execute("""
        CREATE POLICY menu_push_logs_open ON menu_push_logs
            USING (
                task_id IN (
                    SELECT id FROM menu_push_tasks
                    WHERE tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                )
            );
    """)

    # ── menu_plan_store_overrides ─────────────────────────────────────────────
    if "menu_plan_store_overrides" not in existing:
        op.create_table(
            "menu_plan_store_overrides",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("store_id", UUID(as_uuid=True), nullable=False, comment="门店 ID"),
            sa.Column("dish_id", UUID(as_uuid=True), nullable=False, comment="菜品 ID"),
            sa.Column(
                "override_type",
                sa.String(30),
                nullable=True,
                comment="price=价格覆盖 / availability=上下架 / portion=份量",
            ),
            sa.Column("value", JSONB, nullable=True, comment="Override 值（类型相关，如 {price_fen: 3800}）"),
            sa.Column("reason", sa.Text, nullable=True, comment="Override 原因说明"),
            sa.Column("valid_from", sa.Date, nullable=True, comment="生效起始日"),
            sa.Column("valid_until", sa.Date, nullable=True, comment="失效日（含当天）"),
            sa.Column("created_by", UUID(as_uuid=True), nullable=True, comment="创建人员工 ID"),
            sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        )
        op.create_index(
            "ix_menu_plan_store_overrides_tenant_store", "menu_plan_store_overrides", ["tenant_id", "store_id"]
        )
        op.create_index("ix_menu_plan_store_overrides_dish_id", "menu_plan_store_overrides", ["dish_id"])
        op.create_index("ix_menu_plan_store_overrides_store_dish", "menu_plan_store_overrides", ["store_id", "dish_id"])

    op.execute("ALTER TABLE menu_plan_store_overrides ENABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS menu_plan_store_overrides_tenant ON menu_plan_store_overrides;")
    op.execute("""
        CREATE POLICY menu_plan_store_overrides_tenant ON menu_plan_store_overrides
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """)


def downgrade() -> None:
    op.drop_table("menu_plan_store_overrides")
    op.drop_table("menu_push_logs")
    op.drop_table("menu_push_tasks")
    op.drop_table("menu_plan_v2_items")
    op.drop_table("menu_plans_v2")
