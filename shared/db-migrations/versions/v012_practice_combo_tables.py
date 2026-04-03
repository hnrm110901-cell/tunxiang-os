"""v012: Create dish_practices + dish_combos tables with RLS

New tables:
  - dish_practices  菜品口味做法（辣度/温度/加料等）
  - dish_combos     套餐组合（含子项 JSON + 套餐价/原价）

RLS:
  - 两张表均启用 RLS，策略使用 current_setting('app.tenant_id') 隔离。
  - 与 v006 安全修复保持一致，使用 app.tenant_id（非 request.jwt.tenant_id）。

Revision ID: v012
Revises: v011
Create Date: 2026-03-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSON

revision: str = "v012"
down_revision: Union[str, None] = "v011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # =====================================================================
    # dish_practices — 菜品口味做法
    # =====================================================================
    op.create_table(
        "dish_practices",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
        # 业务字段
        sa.Column("dish_id", UUID(as_uuid=True), sa.ForeignKey("dishes.id"), nullable=False, index=True),
        sa.Column("practice_name", sa.String(100), nullable=False, comment="做法名称"),
        sa.Column("practice_group", sa.String(50), nullable=False, server_default="default",
                  comment="分组：辣度/温度/加料/烹饪方式"),
        sa.Column("additional_price_fen", sa.Integer, server_default="0",
                  comment="加价金额(分)"),
        sa.Column("is_default", sa.Boolean, server_default="false",
                  comment="是否该分组默认选项"),
        sa.Column("sort_order", sa.Integer, server_default="0", comment="排序"),
        comment="菜品口味做法",
    )

    # =====================================================================
    # dish_combos — 套餐组合
    # =====================================================================
    op.create_table(
        "dish_combos",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
        # 业务字段
        sa.Column("store_id", UUID(as_uuid=True), sa.ForeignKey("stores.id"),
                  index=True, comment="所属门店，NULL=集团通用套餐"),
        sa.Column("combo_name", sa.String(100), nullable=False, comment="套餐名称"),
        sa.Column("combo_price_fen", sa.Integer, nullable=False, comment="套餐售价(分)"),
        sa.Column("original_price_fen", sa.Integer, nullable=False, comment="原价合计(分)"),
        sa.Column("items_json", JSON, nullable=False, server_default="'[]'::jsonb",
                  comment='[{"dish_id":"..","dish_name":"..","qty":1,"price_fen":1800}]'),
        sa.Column("description", sa.Text, comment="套餐描述"),
        sa.Column("image_url", sa.String(500), comment="套餐图片"),
        sa.Column("is_active", sa.Boolean, server_default="true", comment="是否上架"),
        comment="套餐组合",
    )

    # =====================================================================
    # RLS — 使用 app.tenant_id（与 v006 修复一致）
    # =====================================================================
    for table_name in ("dish_practices", "dish_combos"):
        op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")

        # SELECT
        op.execute(f"""
            CREATE POLICY {table_name}_tenant_select ON {table_name}
            FOR SELECT
            USING (tenant_id = current_setting('app.tenant_id')::uuid)
        """)

        # INSERT
        op.execute(f"""
            CREATE POLICY {table_name}_tenant_insert ON {table_name}
            FOR INSERT
            WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid)
        """)

        # UPDATE
        op.execute(f"""
            CREATE POLICY {table_name}_tenant_update ON {table_name}
            FOR UPDATE
            USING (tenant_id = current_setting('app.tenant_id')::uuid)
            WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid)
        """)

        # DELETE
        op.execute(f"""
            CREATE POLICY {table_name}_tenant_delete ON {table_name}
            FOR DELETE
            USING (tenant_id = current_setting('app.tenant_id')::uuid)
        """)


def downgrade() -> None:
    for table_name in ("dish_combos", "dish_practices"):
        for action in ("delete", "update", "insert", "select"):
            op.execute(f"DROP POLICY IF EXISTS {table_name}_tenant_{action} ON {table_name}")
        op.execute(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY")

    op.drop_table("dish_combos")
    op.drop_table("dish_practices")
