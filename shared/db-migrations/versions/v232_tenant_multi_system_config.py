"""v232 — 租户多系统配置扩展（三品牌四系统）

为 tenants 表新增两列：
  systems_config  JSONB  — 四系统（品智/奥琦玮CRM/奥琦玮供应链/易订）凭证配置
  sync_enabled    BOOLEAN — 是否启用自动同步

同时为三个首批品牌写入配置骨架（凭证待客户提供后填入）：
  t-czq — 尝在一起
  t-zqx — 最黔线
  t-sgc — 尚宫厨

Revision ID: v232
Revises: v231
Create Date: 2026-04-12
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "v232"
down_revision = "v231"
branch_labels = None
depends_on = None

# 配置骨架：凭证全部用 PLACEHOLDER，待客户提供后通过管理 API 更新
_CONFIG_SKELETON = """{
    "pinzhi": {
        "enabled": true,
        "base_url": "",
        "app_id": "",
        "app_secret": "",
        "org_id": ""
    },
    "aoqiwei_crm": {
        "enabled": true,
        "api_url": "https://api.acewill.net",
        "appid": "",
        "appkey": "",
        "shop_id": ""
    },
    "aoqiwei_supply": {
        "enabled": true,
        "api_url": "https://openapi.acescm.cn",
        "app_id": "",
        "app_secret": "",
        "shop_code": ""
    },
    "yiding": {
        "enabled": true,
        "base_url": "",
        "api_key": "",
        "hotel_id": ""
    }
}"""


def upgrade() -> None:
    # ── 1. 新增列（幂等，IF NOT EXISTS） ────────────────────────────
    op.execute("""
        ALTER TABLE tenants
            ADD COLUMN IF NOT EXISTS systems_config JSONB NOT NULL DEFAULT '{}';
    """)
    op.execute("""
        ALTER TABLE tenants
            ADD COLUMN IF NOT EXISTS sync_enabled BOOLEAN NOT NULL DEFAULT FALSE;
    """)

    # ── 2. 为三品牌写入配置骨架（仅当 systems_config 为空时更新） ───
    for tenant_code in ("t-czq", "t-zqx", "t-sgc"):
        op.execute(
            sa.text("""
                UPDATE tenants
                   SET systems_config = :cfg::jsonb
                 WHERE code = :code
                   AND (systems_config IS NULL OR systems_config = '{}'::jsonb)
            """).bindparams(
                cfg=_CONFIG_SKELETON,
                code=tenant_code,
            )
        )

    # ── 3. GIN 索引（加速 JSONB 路径查询） ───────────────────────────
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_tenants_systems_config_gin
            ON tenants USING gin (systems_config);
    """)


def downgrade() -> None:
    op.execute("""
        DROP INDEX IF EXISTS ix_tenants_systems_config_gin;
    """)
    op.execute("""
        ALTER TABLE tenants
            DROP COLUMN IF EXISTS sync_enabled;
    """)
    op.execute("""
        ALTER TABLE tenants
            DROP COLUMN IF EXISTS systems_config;
    """)
