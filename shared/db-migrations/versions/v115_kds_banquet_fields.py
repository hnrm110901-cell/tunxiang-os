"""v115 — KDS任务表新增宴席关联字段 + 活鲜称重关联字段

Revision ID: v115
Revises: v114
Create Date: 2026-04-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "v115"
down_revision = "v114"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── kds_tasks 新增宴席关联字段 ──────────────────────────────────
    op.add_column("kds_tasks", sa.Column(
        "banquet_session_id", UUID(as_uuid=True), nullable=True,
        comment="关联宴席场次ID，NULL=普通堂食任务"
    ))
    op.add_column("kds_tasks", sa.Column(
        "banquet_section_id", UUID(as_uuid=True), nullable=True,
        comment="关联宴席菜单节ID（凉菜/热菜/海鲜等），用于按节统计进度"
    ))
    op.add_column("kds_tasks", sa.Column(
        "weigh_record_id", UUID(as_uuid=True), nullable=True,
        comment="关联活鲜称重记录ID（仅活鲜菜品有）"
    ))
    op.add_column("kds_tasks", sa.Column(
        "is_live_seafood", sa.Boolean, nullable=False, server_default="false",
        comment="是否为活鲜菜品（需要称重确认后才能开始制作）"
    ))
    op.add_column("kds_tasks", sa.Column(
        "weigh_confirmed", sa.Boolean, nullable=False, server_default="false",
        comment="活鲜称重是否已确认（True后才能开始制作）"
    ))

    # ── dish_dept_mappings 菜品→档口映射表（若不存在则创建）────────────
    # 该表决定每道菜分到哪个KDS档口
    op.create_table(
        "dish_dept_mappings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", UUID(as_uuid=True), nullable=True,
                  comment="NULL=集团通用映射 / 有值=门店专属覆盖"),
        sa.Column("dish_id", UUID(as_uuid=True), nullable=False),
        sa.Column("dept_id", UUID(as_uuid=True), nullable=False,
                  comment="档口ID（凉菜/热菜/海鲜/点心/主食档口）"),
        sa.Column("dept_name", sa.String(50), nullable=False,
                  comment="档口名称快照，便于KDS展示"),
        sa.Column("is_primary", sa.Boolean, nullable=False, server_default="true",
                  comment="主档口（一道菜有时需要多档口协同，如半成品在备菜档，成品在热菜档）"),
        sa.Column("priority", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        sa.UniqueConstraint("tenant_id", "dish_id", "dept_id",
                            name="uq_dish_dept_mapping"),
    )

    # ── 索引 ────────────────────────────────────────────────────────
    op.create_index("ix_kds_tasks_banquet_session", "kds_tasks", ["banquet_session_id"])
    op.create_index("ix_kds_tasks_banquet_section", "kds_tasks", ["banquet_section_id"])
    op.create_index("ix_dish_dept_mappings_dish", "dish_dept_mappings", ["dish_id", "tenant_id"])
    op.create_index("ix_dish_dept_mappings_dept", "dish_dept_mappings", ["dept_id"])

    # ── RLS ─────────────────────────────────────────────────────────
    op.execute("ALTER TABLE dish_dept_mappings ENABLE ROW LEVEL SECURITY;")
    op.execute("""
        CREATE POLICY dish_dept_mappings_tenant_isolation ON dish_dept_mappings
        USING (tenant_id = (current_setting('app.tenant_id', true)::uuid));
    """)


def downgrade() -> None:
    op.drop_table("dish_dept_mappings")
    for col in ["banquet_session_id", "banquet_section_id",
                "weigh_record_id", "is_live_seafood", "weigh_confirmed"]:
        op.drop_column("kds_tasks", col)
