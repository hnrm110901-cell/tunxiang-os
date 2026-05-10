"""v410: Class C LIVE 表 revive — brand_groups / cook_time_baselines / delivery_auto_accept_rules

PR #357 ORM↔migration drift 检测捕获 7 张 Class C ORM-only 表。承 PR #369
(`docs/orm-drift-class-c-audit.md`) audit 后剩余 4 张 LIVE，本 PR revive 其中
3 张（kds_tasks 因揭露 6 列 ORM↔raw SQL 漂移单独 issue 跟进，同 #364 模式）：

──────── 本 PR 范围 ────────
1. brand_groups (tx-member/group_config.py:18) — 集团跨品牌管理
   - heavy raw SQL: services/tx-member/src/services/group_member_service.py 多处
     `SELECT FROM brand_groups WHERE id=:group_id` / `SELECT group_name FROM brand_groups`
   - 不 revive 即 group_member_service / group_routes / group_member_routes API 全炸

2. cook_time_baselines (tx-trade/cook_time_baseline.py:21) — 菜品制作时间基准
   - raw SQL: services/tx-trade/src/services/cook_time_stats.py:466
     `从 cook_time_baselines 表查询单条基准数据`
   - 不 revive 即 cook_time hot path 调用炸（虽 ORM 也可 fallback，但 raw SQL 走不通）

3. delivery_auto_accept_rules (tx-trade/delivery_auto_accept_rule.py:17) — 外卖自动接单规则
   - DeliveryAutoAcceptRuleRepository (delivery_order_repo.py:494) 通过 SQLAlchemy
     ORM CRUD（select / db.add）
   - 不 revive 即 takeaway_routes / delivery_panel_router API 全炸

──────── 不在本 PR 范围 ────────
- kds_tasks 第 4 张 LIVE 表 — ORM↔raw SQL 列漂移 6 列（banquet_session_id /
  banquet_section_id / store_id / platform / items / push_mode）需独立 audit
  + ORM 列补齐，归属 issue #(kds-tasks-column-drift) 跟进

──────── 列对齐验证（ORM ↔ DDL）────────
- brand_groups: 8 业务列（group_name/group_code/brand_tenant_ids/stored_value_interop/
  member_data_shared/status/created_by/updated_by）+ TenantBase 5 列 + UNIQUE(group_code)
  + INDEX(tenant_id, status)。raw SQL SELECT 子集（id/group_name/is_deleted）全在
- cook_time_baselines: 7 业务列（dish_id/dept_id/hour_bucket/day_type/p50_seconds/
  p90_seconds/sample_count/computed_at）+ TenantBase 5 列 + 4 索引（含复合 lookup）
- delivery_auto_accept_rules: 6 业务列（store_id/is_enabled/business_hours_*/
  max_concurrent_orders/excluded_platforms）+ TenantBase 5 列 + UNIQUE(tenant_id, store_id)

──────── RLS 策略 ────────
按 PR #361/#362/#363/#369 chain rescue helper 模板（class F2 修后）：
  SELECT/DELETE: USING only
  INSERT:        WITH CHECK only
  UPDATE:        USING + WITH CHECK (PG.7 防 tenant_id 行漂移)

Revision ID: v410_class_c_live_revive
Revises: v409_fund_settlement_revive
Create Date: 2026-05-10
"""
from typing import Sequence, Union

from alembic import op

revision: str = "v410_class_c_live_revive"
down_revision: Union[str, Sequence[str], None] = "v409_fund_settlement_revive"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TENANT_PREDICATE = (
    "current_setting('app.tenant_id', TRUE) IS NOT NULL "
    "AND current_setting('app.tenant_id', TRUE) <> '' "
    "AND tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::UUID"
)


def _apply_rls(table_name: str) -> None:
    """ENABLE+FORCE RLS + 4 条 RESTRICTIVE 策略（INSERT WITH CHECK / UPDATE 双子句）。"""
    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY;")

    # SELECT — USING only
    op.execute(f"""
        CREATE POLICY {table_name}_select_tenant ON {table_name}
        AS RESTRICTIVE FOR SELECT
        USING ({_TENANT_PREDICATE});
    """)

    # INSERT — WITH CHECK only (PG: USING invalid for INSERT)
    op.execute(f"""
        CREATE POLICY {table_name}_insert_tenant ON {table_name}
        AS RESTRICTIVE FOR INSERT
        WITH CHECK ({_TENANT_PREDICATE});
    """)

    # UPDATE — USING + WITH CHECK (PG.7 防 tenant_id 行漂移)
    op.execute(f"""
        CREATE POLICY {table_name}_update_tenant ON {table_name}
        AS RESTRICTIVE FOR UPDATE
        USING ({_TENANT_PREDICATE})
        WITH CHECK ({_TENANT_PREDICATE});
    """)

    # DELETE — USING only
    op.execute(f"""
        CREATE POLICY {table_name}_delete_tenant ON {table_name}
        AS RESTRICTIVE FOR DELETE
        USING ({_TENANT_PREDICATE});
    """)


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────
    # brand_groups — 集团跨品牌管理
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS brand_groups (
            id                    UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id             UUID         NOT NULL,
            is_deleted            BOOLEAN      NOT NULL DEFAULT FALSE,
            created_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            group_name            VARCHAR(100) NOT NULL,
            group_code            VARCHAR(50)  NOT NULL,
            brand_tenant_ids      JSON         NOT NULL DEFAULT '[]'::JSON,
            stored_value_interop  BOOLEAN      NOT NULL DEFAULT FALSE,
            member_data_shared    BOOLEAN      NOT NULL DEFAULT FALSE,
            status                VARCHAR(20)  NOT NULL DEFAULT 'active',
            created_by            UUID,
            updated_by            UUID,
            CONSTRAINT uq_brand_group_code UNIQUE (group_code)
        );
    """)

    _apply_rls("brand_groups")

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_brand_group_tenant
            ON brand_groups (tenant_id, status);
    """)

    # ─────────────────────────────────────────────────────────────────
    # cook_time_baselines — 菜品制作时间基准
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS cook_time_baselines (
            id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id     UUID        NOT NULL,
            is_deleted    BOOLEAN     NOT NULL DEFAULT FALSE,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            dish_id       UUID        NOT NULL,
            dept_id       UUID        NOT NULL,
            hour_bucket   INTEGER     NOT NULL,
            day_type      VARCHAR(10) NOT NULL DEFAULT 'weekday',
            p50_seconds   INTEGER     NOT NULL,
            p90_seconds   INTEGER     NOT NULL,
            sample_count  INTEGER     NOT NULL DEFAULT 0,
            computed_at   TIMESTAMPTZ
        );
    """)

    _apply_rls("cook_time_baselines")

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_cook_time_baselines_dish_id
            ON cook_time_baselines (dish_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_cook_time_baselines_dept_id
            ON cook_time_baselines (dept_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_cook_time_baselines_lookup
            ON cook_time_baselines (tenant_id, dish_id, dept_id, hour_bucket, day_type);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_cook_time_baselines_dept_computed
            ON cook_time_baselines (tenant_id, dept_id, computed_at);
    """)

    # ─────────────────────────────────────────────────────────────────
    # delivery_auto_accept_rules — 外卖自动接单规则（每门店一条）
    # ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS delivery_auto_accept_rules (
            id                     UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id              UUID        NOT NULL,
            is_deleted             BOOLEAN     NOT NULL DEFAULT FALSE,
            created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            store_id               UUID        NOT NULL,
            is_enabled             BOOLEAN     NOT NULL DEFAULT FALSE,
            business_hours_start   TIME,
            business_hours_end     TIME,
            max_concurrent_orders  INTEGER     NOT NULL DEFAULT 10,
            excluded_platforms     JSONB       NOT NULL DEFAULT '[]'::JSONB,
            CONSTRAINT uq_auto_accept_rule_store UNIQUE (tenant_id, store_id)
        );
    """)

    _apply_rls("delivery_auto_accept_rules")

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_delivery_auto_accept_rules_store_id
            ON delivery_auto_accept_rules (store_id);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS delivery_auto_accept_rules CASCADE;")
    op.execute("DROP TABLE IF EXISTS cook_time_baselines CASCADE;")
    op.execute("DROP TABLE IF EXISTS brand_groups CASCADE;")
