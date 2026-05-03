"""v385 — UnionID 查询索引（MU-1 性能优化）

为 customers 表补充索引，加速 UnionID 批量补全和跨品牌合并：
  idx_customers_unionid         — 按 unionid 查询（跨品牌合并）
  idx_customers_openid_tenant   — 按 openid + tenant 查询（backfill 分批）

Revision ID: v385_unionid_indexes
Revises: v384_wecom_channel_codes
Create Date: 2026-05-03
"""

from typing import Sequence, Union

from alembic import op

revision: str = "v385_unionid_indexes"
down_revision: Union[str, None] = "v384_wecom_channel_codes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_customers_unionid
        ON customers (wechat_unionid)
        WHERE wechat_unionid IS NOT NULL
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_customers_openid_tenant
        ON customers (wechat_openid, tenant_id)
        WHERE wechat_openid IS NOT NULL
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_customers_unionid_tenant
        ON customers (wechat_unionid, tenant_id)
        WHERE wechat_unionid IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_customers_unionid")
    op.execute("DROP INDEX IF EXISTS idx_customers_openid_tenant")
    op.execute("DROP INDEX IF EXISTS idx_customers_unionid_tenant")
