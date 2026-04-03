"""v030: 为 customers 表添加外卖平台身份字段

新增字段（均可 NULL，允许逐步回填）：
  meituan_user_id   — 美团用户ID
  meituan_openid    — 美团小程序openid
  douyin_openid     — 抖音openid
  eleme_user_id     — 饿了么用户ID

索引：
  idx_customer_meituan_user_id  — 美团订单核销查询
  idx_customer_meituan_openid   — 美团小程序openid查询
  idx_customer_douyin_openid    — 抖音openid查询
  idx_customer_eleme_user_id    — 饿了么用户ID查询

RLS 策略保持使用 v006+ 标准安全模式（app.tenant_id），不对 customers 表单独操作
（customers 表的 RLS 已在早期迁移中配置，此处仅 ALTER TABLE ADD COLUMN）。

Revision ID: v030
Revises: v029
Create Date: 2026-03-30
"""
from alembic import op
import sqlalchemy as sa

revision = "v030"
down_revision = "v029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 添加外卖平台身份字段
    op.add_column("customers", sa.Column("meituan_user_id", sa.String(128), nullable=True, comment="美团用户ID"))
    op.add_column("customers", sa.Column("meituan_openid", sa.String(128), nullable=True, comment="美团小程序openid"))
    op.add_column("customers", sa.Column("douyin_openid", sa.String(128), nullable=True, comment="抖音openid"))
    op.add_column("customers", sa.Column("eleme_user_id", sa.String(128), nullable=True, comment="饿了么用户ID"))

    # 创建查询索引
    op.create_index("idx_customer_meituan_user_id", "customers", ["meituan_user_id"])
    op.create_index("idx_customer_meituan_openid", "customers", ["meituan_openid"])
    op.create_index("idx_customer_douyin_openid", "customers", ["douyin_openid"])
    op.create_index("idx_customer_eleme_user_id", "customers", ["eleme_user_id"])


def downgrade() -> None:
    op.drop_index("idx_customer_eleme_user_id", table_name="customers")
    op.drop_index("idx_customer_douyin_openid", table_name="customers")
    op.drop_index("idx_customer_meituan_openid", table_name="customers")
    op.drop_index("idx_customer_meituan_user_id", table_name="customers")

    op.drop_column("customers", "eleme_user_id")
    op.drop_column("customers", "douyin_openid")
    op.drop_column("customers", "meituan_openid")
    op.drop_column("customers", "meituan_user_id")
