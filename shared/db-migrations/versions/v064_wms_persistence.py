"""WMS 持久化层 — 盘点/移库/供应商档案/评分历史

新增表：
  stocktakes               — 盘点单主表（开单/进行中/完成/取消）
  stocktake_items          — 盘点明细（账面/实盘/差异 GENERATED STORED）
  warehouse_transfers      — 移库单主表（门店间调拨）
  warehouse_transfer_items — 移库明细
  supplier_profiles        — 供应商档案持久化版（含第三方系统 ID）
  supplier_score_history   — 供应商五维度评分历史 + AI 洞察

背景：
  tx-supply 的 stocktake_service / warehouse_ops / supplier_portal_service
  均使用内存存储（_stocktakes dict / _suppliers dict 等）。
  本迁移为上述三个服务补充 DB 持久化层，使数据在重启后得以保留，
  并支持跨门店、跨品牌的多租户安全隔离。

RLS 策略：
  全部使用 v056+ 标准安全模式
  （NULLIF + 四操作 PERMISSIVE + FORCE ROW LEVEL SECURITY）
  禁止使用 app.current_store_id / app.current_tenant 等错误变量名。

Revision ID: v064
Revises: v063
Create Date: 2026-03-31
"""
from typing import Sequence, Union

from alembic import op

revision: str = "v064"
down_revision: Union[str, None] = "v063"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# ─────────────────────────────────────────────────────────────────────────────
#  安全 RLS 条件 — NULLIF NULL-guard 防止空字符串绕过（v056+ 标准）
#  禁止使用 app.current_store_id 或 app.current_tenant（错误变量名）
# ─────────────────────────────────────────────────────────────────────────────
_SAFE_CONDITION = (
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::UUID"
)

_WMS_TABLES = [
    "stocktakes",
    "stocktake_items",
    "warehouse_transfers",
    "warehouse_transfer_items",
    "supplier_profiles",
    "supplier_score_history",
]


def _apply_safe_rls(table: str) -> None:
    """创建标准安全 RLS：四操作 PERMISSIVE + NULLIF NULL-guard + FORCE。"""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {table}_rls_select ON {table}")
    op.execute(
        f"CREATE POLICY {table}_rls_select ON {table} "
        f"FOR SELECT USING ({_SAFE_CONDITION})"
    )
    op.execute(f"DROP POLICY IF EXISTS {table}_rls_insert ON {table}")
    op.execute(
        f"CREATE POLICY {table}_rls_insert ON {table} "
        f"FOR INSERT WITH CHECK ({_SAFE_CONDITION})"
    )
    op.execute(f"DROP POLICY IF EXISTS {table}_rls_update ON {table}")
    op.execute(
        f"CREATE POLICY {table}_rls_update ON {table} "
        f"FOR UPDATE USING ({_SAFE_CONDITION}) WITH CHECK ({_SAFE_CONDITION})"
    )
    op.execute(f"DROP POLICY IF EXISTS {table}_rls_delete ON {table}")
    op.execute(
        f"CREATE POLICY {table}_rls_delete ON {table} "
        f"FOR DELETE USING ({_SAFE_CONDITION})"
    )


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────────
    # 1. stocktakes — 盘点单主表
    #    对应 stocktake_service.py 中 _stocktakes dict 的持久化版本
    #    status 说明：
    #      draft       — 草稿（创建后尚未开始录入）
    #      in_progress — 进行中（正在逐条录入实盘数量）
    #      completed   — 已完成（finalize_stocktake 调用后）
    #      cancelled   — 已取消
    # ─────────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS stocktakes (
            id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id     UUID        NOT NULL,
            store_id      UUID        NOT NULL,
            stocktake_no  TEXT        UNIQUE,
            status        TEXT        NOT NULL DEFAULT 'draft'
                              CHECK (status IN ('draft', 'in_progress', 'completed', 'cancelled')),
            stocktaker_id UUID,
            started_at    TIMESTAMPTZ,
            completed_at  TIMESTAMPTZ,
            notes         TEXT,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted    BOOLEAN     NOT NULL DEFAULT FALSE
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_stocktakes_tenant_store "
        "ON stocktakes (tenant_id, store_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_stocktakes_tenant_status "
        "ON stocktakes (tenant_id, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_stocktakes_tenant_store_created "
        "ON stocktakes (tenant_id, store_id, created_at DESC)"
    )
    _apply_safe_rls("stocktakes")

    # ─────────────────────────────────────────────────────────────────────
    # 2. stocktake_items — 盘点明细
    #    每行对应一个原料的盘点记录。
    #    variance 为 GENERATED ALWAYS AS STORED 计算列，
    #    自动保持 actual_qty - expected_qty，无需应用层维护。
    #    对应 stocktake_service.py 中 items dict 内的每个条目。
    # ─────────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS stocktake_items (
            id               UUID           PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id        UUID           NOT NULL,
            stocktake_id     UUID           NOT NULL REFERENCES stocktakes(id),
            ingredient_id    UUID           NOT NULL,
            ingredient_name  TEXT,
            unit             TEXT,
            expected_qty     NUMERIC(10, 3),
            actual_qty       NUMERIC(10, 3),
            variance         NUMERIC(10, 3) GENERATED ALWAYS AS (actual_qty - expected_qty) STORED,
            cost_price       NUMERIC(10, 4),
            notes            TEXT,
            created_at       TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
            updated_at       TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
            is_deleted       BOOLEAN        NOT NULL DEFAULT FALSE
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_stocktake_items_tenant_stocktake "
        "ON stocktake_items (tenant_id, stocktake_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_stocktake_items_tenant_ingredient "
        "ON stocktake_items (tenant_id, ingredient_id)"
    )
    _apply_safe_rls("stocktake_items")

    # ─────────────────────────────────────────────────────────────────────
    # 3. warehouse_transfers — 移库单主表
    #    对应 warehouse_ops.py 中 create_transfer_order 产生的记录。
    #    from_store_id / to_store_id 对应原代码的 from_warehouse / to_warehouse。
    #    status 说明：
    #      pending    — 待审核/待发货
    #      in_transit — 在途
    #      received   — 目标门店已收货
    #      cancelled  — 已取消
    #    transfer_type 说明：
    #      normal    — 常规调拨
    #      emergency — 紧急调拨
    #      return    — 退货调回
    # ─────────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS warehouse_transfers (
            id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id      UUID        NOT NULL,
            transfer_no    TEXT        UNIQUE,
            from_store_id  UUID        NOT NULL,
            to_store_id    UUID        NOT NULL,
            status         TEXT        NOT NULL DEFAULT 'pending'
                               CHECK (status IN ('pending', 'in_transit', 'received', 'cancelled')),
            transfer_type  TEXT        NOT NULL DEFAULT 'normal'
                               CHECK (transfer_type IN ('normal', 'emergency', 'return')),
            initiated_by   UUID,
            approved_by    UUID,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted     BOOLEAN     NOT NULL DEFAULT FALSE
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_warehouse_transfers_tenant_from "
        "ON warehouse_transfers (tenant_id, from_store_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_warehouse_transfers_tenant_to "
        "ON warehouse_transfers (tenant_id, to_store_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_warehouse_transfers_tenant_status "
        "ON warehouse_transfers (tenant_id, status)"
    )
    _apply_safe_rls("warehouse_transfers")

    # ─────────────────────────────────────────────────────────────────────
    # 4. warehouse_transfer_items — 移库明细
    #    对应 create_transfer_order items 列表中的每个条目。
    #    requested_qty — 申请调拨数量
    #    actual_qty    — 实际出/入库数量（收货确认后填写）
    # ─────────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS warehouse_transfer_items (
            id              UUID           PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID           NOT NULL,
            transfer_id     UUID           NOT NULL REFERENCES warehouse_transfers(id),
            ingredient_id   UUID           NOT NULL,
            ingredient_name TEXT,
            unit            TEXT,
            requested_qty   NUMERIC(10, 3),
            actual_qty      NUMERIC(10, 3),
            cost_price      NUMERIC(10, 4),
            created_at      TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN        NOT NULL DEFAULT FALSE
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wt_items_tenant_transfer "
        "ON warehouse_transfer_items (tenant_id, transfer_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wt_items_tenant_ingredient "
        "ON warehouse_transfer_items (tenant_id, ingredient_id)"
    )
    _apply_safe_rls("warehouse_transfer_items")

    # ─────────────────────────────────────────────────────────────────────
    # 5. supplier_profiles — 供应商档案（持久化版）
    #    对应 supplier_portal_service.py 中 _suppliers dict 的持久化版本。
    #    新增 source / external_id 字段，支持奥琦玮/品智第三方数据接入。
    #    status 说明：
    #      active      — 正常合作
    #      suspended   — 暂停合作
    #      blacklisted — 已列入黑名单
    #    source 说明：
    #      manual   — 手动录入
    #      aoqiwei  — 奥琦玮平台同步
    #      pinzhi   — 品智平台同步
    #    categories 示例：["seafood", "meat"]
    # ─────────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS supplier_profiles (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID        NOT NULL,
            supplier_code   TEXT,
            supplier_name   TEXT        NOT NULL,
            contact_name    TEXT,
            contact_phone   TEXT,
            address         TEXT,
            status          TEXT        NOT NULL DEFAULT 'active'
                                CHECK (status IN ('active', 'suspended', 'blacklisted')),
            source          TEXT        NOT NULL DEFAULT 'manual',
            external_id     TEXT,
            categories      JSONB       NOT NULL DEFAULT '[]',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_deleted      BOOLEAN     NOT NULL DEFAULT FALSE
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_supplier_profiles_tenant_status "
        "ON supplier_profiles (tenant_id, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_supplier_profiles_tenant_source "
        "ON supplier_profiles (tenant_id, source)"
    )
    # 同一租户内，第三方系统来源 + 外部 ID 唯一
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_supplier_profiles_tenant_source_ext "
        "ON supplier_profiles (tenant_id, source, external_id) "
        "WHERE external_id IS NOT NULL AND is_deleted = FALSE"
    )
    _apply_safe_rls("supplier_profiles")

    # ─────────────────────────────────────────────────────────────────────
    # 6. supplier_score_history — 供应商评分历史
    #    对应 supplier_portal_service.py 中五维度评分逻辑的持久化版本。
    #    五维度：delivery_rate / quality_rate / price_stability /
    #            response_speed / compliance_rate（均为 0-1 小数）
    #    composite_score — 加权综合分（0-100 区间）
    #    ai_insight      — Claude API 生成的文字洞察
    # ─────────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS supplier_score_history (
            id               UUID           PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id        UUID           NOT NULL,
            supplier_id      UUID           NOT NULL REFERENCES supplier_profiles(id),
            period_start     DATE           NOT NULL,
            period_end       DATE           NOT NULL,
            delivery_rate    NUMERIC(5, 4)  CHECK (delivery_rate BETWEEN 0 AND 1),
            quality_rate     NUMERIC(5, 4)  CHECK (quality_rate BETWEEN 0 AND 1),
            price_stability  NUMERIC(5, 4)  CHECK (price_stability BETWEEN 0 AND 1),
            response_speed   NUMERIC(5, 4)  CHECK (response_speed BETWEEN 0 AND 1),
            compliance_rate  NUMERIC(5, 4)  CHECK (compliance_rate BETWEEN 0 AND 1),
            composite_score  NUMERIC(5, 2)  CHECK (composite_score BETWEEN 0 AND 100),
            ai_insight       TEXT,
            created_at       TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
            updated_at       TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
            is_deleted       BOOLEAN        NOT NULL DEFAULT FALSE
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_supplier_score_tenant_supplier "
        "ON supplier_score_history (tenant_id, supplier_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_supplier_score_tenant_supplier_period "
        "ON supplier_score_history (tenant_id, supplier_id, period_start DESC)"
    )
    _apply_safe_rls("supplier_score_history")


def downgrade() -> None:
    for table in reversed(_WMS_TABLES):
        for suffix in ("select", "insert", "update", "delete"):
            op.execute(f"DROP POLICY IF EXISTS {table}_rls_{suffix} ON {table}")
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
