"""v231 — brands 核心表（多品牌管理基础设施）

品牌层是屯象OS四层治理结构（集团→品牌→业态→门店）的第二层。
本迁移创建 brands 表，支撑多品牌运营的完整生命周期管理：
  - 品牌基础信息（名称/编码/类型/Logo/主色调）
  - 品牌运营配置（strategy_config JSONB，存储定价策略/促销规则等）
  - 多租户隔离（tenant_id + RLS NULLIF 安全策略）
  - 软删除（is_deleted）

首批接入客户：尝在一起、最黔线、尚宫厨。

RLS 采用 NULLIF 安全格式，防止 app.tenant_id 为空时发生跨租户数据泄露。

Revision ID: v231
Revises: v230
Create Date: 2026-04-12
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "v231"
down_revision = "v230"
branch_labels = None
depends_on = None

# 标准安全 RLS 条件（NULLIF 保护，与 v230 规范一致）
_RLS_COND = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID"


def upgrade() -> None:
    # ──────────────────────────────────────────────────────────────────
    # brands — 品牌主表
    # ──────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS brands (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID        NOT NULL,
            name            VARCHAR(100) NOT NULL,
            brand_code      VARCHAR(20)  NOT NULL UNIQUE,
            brand_type      VARCHAR(50),
            logo_url        TEXT,
            primary_color   VARCHAR(7)   NOT NULL DEFAULT '#FF6B35',
            description     TEXT,
            hq_store_id     UUID,
            status          VARCHAR(20)  NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'inactive', 'archived')),
            strategy_config JSONB        NOT NULL DEFAULT '{}',
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN      NOT NULL DEFAULT FALSE
        );

        COMMENT ON TABLE brands IS
            '品牌主表：多品牌管理核心实体，对应四层治理结构第二层（集团→品牌→业态→门店）';
        COMMENT ON COLUMN brands.brand_code IS
            '品牌编码，全局唯一，建议用拼音首字母缩写（如 CZ=尝在一起）';
        COMMENT ON COLUMN brands.brand_type IS
            '品牌业态类型：seafood/hotpot/canteen/quick_service/banquet';
        COMMENT ON COLUMN brands.primary_color IS
            '品牌主色调（Hex 格式，如 #FF6B35），用于前端 UI 品牌色适配';
        COMMENT ON COLUMN brands.hq_store_id IS
            '总店/旗舰店 ID，用于品牌标杆门店标记和数据对标';
        COMMENT ON COLUMN brands.strategy_config IS
            '品牌运营策略配置（JSONB 全量存储）：定价区间/折扣上限/促销规则/KPI阈值等';
        COMMENT ON COLUMN brands.status IS
            '品牌状态：active=正常运营 inactive=暂停 archived=已归档';

        -- 租户下按名称检索
        CREATE INDEX IF NOT EXISTS ix_brands_tenant_name
            ON brands (tenant_id, name)
            WHERE is_deleted = FALSE;

        -- 租户下按状态筛选
        CREATE INDEX IF NOT EXISTS ix_brands_tenant_status
            ON brands (tenant_id, status)
            WHERE is_deleted = FALSE;

        -- 品牌编码精确查询（全局唯一）
        CREATE INDEX IF NOT EXISTS ix_brands_code
            ON brands (brand_code)
            WHERE is_deleted = FALSE;
    """)

    # ──────────────────────────────────────────────────────────────────
    # RLS 多租户隔离（NULLIF 安全格式，防空串绕过）
    # ──────────────────────────────────────────────────────────────────
    op.execute("ALTER TABLE brands ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE brands FORCE ROW LEVEL SECURITY;")
    op.execute(f"""
        CREATE POLICY brands_rls ON brands
            USING ({_RLS_COND})
            WITH CHECK ({_RLS_COND});
    """)

    # ──────────────────────────────────────────────────────────────────
    # stores.brand_id 外键（从 VARCHAR(50) 升级为 UUID 引用）
    # 注意：存量 stores 表的 brand_id 为 VARCHAR(50)，此处仅添加索引，
    # 外键约束需等待数据迁移完成后再添加，避免阻断现有门店操作。
    # ──────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_stores_brand_id
            ON stores (brand_id)
            WHERE is_deleted = FALSE AND brand_id IS NOT NULL;
    """)


def downgrade() -> None:
    # 移除 stores 索引
    op.execute("DROP INDEX IF EXISTS ix_stores_brand_id;")

    # 移除 brands RLS 策略
    op.execute("DROP POLICY IF EXISTS brands_rls ON brands;")

    # 删除 brands 表（CASCADE 清理依赖）
    op.execute("DROP TABLE IF EXISTS brands CASCADE;")
