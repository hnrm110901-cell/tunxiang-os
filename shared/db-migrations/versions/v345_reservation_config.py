"""v345 — 预订配置表（包间/区域 + 时段配置）

将硬编码的包间配置和时段配置迁移到数据库驱动：
- reservation_configs: 包间/区域配置（房型、容量、押金、排序）
- reservation_time_slots: 预订时段配置（午餐/晚餐/自定义时段、用餐时长、最大预订数）

两表均启用 RLS 租户隔离。

Revision: v345_reservation_config
Revises: v344_banquet_aftercare
Create Date: 2026-04-25
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "v345_reservation_config"
down_revision: Union[str, None] = "v345_mall_enhancements"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_TABLES = [
    "reservation_configs",
    "reservation_time_slots",
]


_RLS_CONDITION = (
    "current_setting('app.tenant_id', TRUE) IS NOT NULL "
    "AND current_setting('app.tenant_id', TRUE) <> '' "
    "AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID"
)


def _enable_rls(table_name: str) -> None:
    """为表启用 RLS + 创建租户隔离策略（v006+ safe pattern: NULL guard + FORCE）"""
    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")
    for action, clause in [
        ("select", f"FOR SELECT USING ({_RLS_CONDITION})"),
        ("insert", f"FOR INSERT WITH CHECK ({_RLS_CONDITION})"),
        ("update", f"FOR UPDATE USING ({_RLS_CONDITION}) WITH CHECK ({_RLS_CONDITION})"),
        ("delete", f"FOR DELETE USING ({_RLS_CONDITION})"),
    ]:
        op.execute(
            f"CREATE POLICY {table_name}_rls_{action} ON {table_name} "
            f"AS PERMISSIVE {clause}"
        )


def _disable_rls(table_name: str) -> None:
    for suffix in ("select", "insert", "update", "delete"):
        op.execute(f"DROP POLICY IF EXISTS {table_name}_rls_{suffix} ON {table_name}")
    op.execute(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY")


def upgrade() -> None:
    # ---------------------------------------------------------------
    # 1. reservation_configs — 包间/区域配置
    # ---------------------------------------------------------------
    op.create_table(
        "reservation_configs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", sa.String(64), nullable=False),
        sa.Column("room_code", sa.String(50), nullable=False, comment="包间编码，门店内唯一"),
        sa.Column("room_name", sa.String(100), nullable=False, comment="包间名称"),
        sa.Column("room_type", sa.String(20), nullable=False, server_default="private",
                  comment="private|hall|outdoor"),
        sa.Column("min_guests", sa.Integer, nullable=False, server_default="2", comment="最少人数"),
        sa.Column("max_guests", sa.Integer, nullable=False, server_default="12", comment="最多人数"),
        sa.Column("deposit_fen", sa.BigInteger, nullable=False, server_default="0", comment="定金(分)"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )
    op.create_index("ix_reservation_configs_store", "reservation_configs", ["store_id"])
    op.create_index(
        "ix_reservation_configs_store_room_code",
        "reservation_configs",
        ["store_id", "room_code"],
        unique=True,
    )

    # ---------------------------------------------------------------
    # 2. reservation_time_slots — 预订时段配置
    # ---------------------------------------------------------------
    op.create_table(
        "reservation_time_slots",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("store_id", sa.String(64), nullable=False),
        sa.Column("slot_name", sa.String(50), nullable=False, comment="时段名称如午餐/晚餐"),
        sa.Column("start_time", sa.Time, nullable=False, comment="开始时间"),
        sa.Column("end_time", sa.Time, nullable=False, comment="结束时间"),
        sa.Column("dining_duration_min", sa.Integer, nullable=False, server_default="120",
                  comment="默认用餐时长(分钟)"),
        sa.Column("max_reservations", sa.Integer, nullable=False, server_default="0",
                  comment="最大预订数,0=不限"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
    )
    op.create_index("ix_reservation_time_slots_store", "reservation_time_slots", ["store_id"])

    # ---------------------------------------------------------------
    # Enable RLS on all new tables
    # ---------------------------------------------------------------
    for table in NEW_TABLES:
        _enable_rls(table)


def downgrade() -> None:
    for table in reversed(NEW_TABLES):
        _disable_rls(table)
        op.drop_table(table)
