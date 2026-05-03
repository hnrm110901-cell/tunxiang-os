"""v281 — 区域服务模式扩展（service_mode + coupon_config + pre_order_config）

将 pay_mode(2态) 扩展为 service_mode(3态)，驱动收银台全流程分支。
新增区域级券核销配置和预点单配置。

场景说明：
  dine_first   — 先吃后付（包厢/卡座/正餐，传统堂食）
  scan_and_pay — 扫码即付（大厅快餐，扫码→选菜→核销券→付款→出餐）
  retail       — 纯零售（便利店窗口，扫商品码→付款→走人，无桌台无会话）

Revision ID: v281
Revises: v280_salary_anomaly
Create Date: 2026-04-24
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v281b"
down_revision: Union[str, None] = "v280_salary_anomaly"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _col_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    result = bind.execute(sa.text(
        "SELECT COUNT(*) FROM information_schema.columns "
        "WHERE table_name = :t AND column_name = :c"
    ), {"t": table, "c": column})
    return result.scalar() > 0


def upgrade() -> None:
    # ── 1. table_zones.service_mode ────────────────────────────────────────
    if not _col_exists("table_zones", "service_mode"):
        op.add_column(
            "table_zones",
            sa.Column(
                "service_mode", sa.String(20), nullable=False,
                server_default="dine_first",
                comment="服务模式：dine_first=先吃后付 / scan_and_pay=扫码即付 / retail=纯零售",
            ),
        )
        op.execute(sa.text("""
            ALTER TABLE table_zones
            ADD CONSTRAINT ck_table_zones_service_mode
            CHECK (service_mode IN ('dine_first', 'scan_and_pay', 'retail'));
        """))

    # ── 2. 用已有 pay_mode 回填 service_mode ──────────────────────────────
    op.execute(sa.text("""
        UPDATE table_zones
        SET service_mode = CASE
            WHEN pay_mode = 'prepay' THEN 'scan_and_pay'
            ELSE 'dine_first'
        END
        WHERE service_mode = 'dine_first';
    """))

    # ── 3. table_zones.coupon_config ───────────────────────────────────────
    if not _col_exists("table_zones", "coupon_config"):
        op.add_column(
            "table_zones",
            sa.Column(
                "coupon_config", sa.dialects.postgresql.JSONB(),
                nullable=False, server_default="{}",
                comment="券核销配置：{allows_platform_voucher, allows_cash_voucher, "
                        "allows_member_points, voucher_deduct_timing: on_order|on_settle}",
            ),
        )

    # ── 4. table_zones.pre_order_config ────────────────────────────────────
    if not _col_exists("table_zones", "pre_order_config"):
        op.add_column(
            "table_zones",
            sa.Column(
                "pre_order_config", sa.dialects.postgresql.JSONB(),
                nullable=False, server_default="{}",
                comment="预点单配置：{allows_pre_order, pre_order_hold_min, "
                        "auto_fire_on_arrival, requires_deposit}",
            ),
        )


def downgrade() -> None:
    for col in ("pre_order_config", "coupon_config"):
        op.execute(sa.text(
            f"ALTER TABLE table_zones DROP COLUMN IF EXISTS {col};"
        ))

    op.execute(sa.text(
        "ALTER TABLE table_zones DROP CONSTRAINT IF EXISTS ck_table_zones_service_mode;"
    ))
    op.execute(sa.text(
        "ALTER TABLE table_zones DROP COLUMN IF EXISTS service_mode;"
    ))
