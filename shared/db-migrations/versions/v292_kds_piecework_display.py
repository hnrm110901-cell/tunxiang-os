"""v292 — KDS计件配菜

3张新表：
  - kds_piecework_records   — 计件记录（员工×菜品×班次）
  - kds_piecework_schemes   — 计件方案（按菜品/做法/档口）
  - kds_display_configs     — KDS显示配置（档口>门店>默认层级）

所有表启用 RLS 租户隔离。

Revision ID: v292
Revises: v291
Create Date: 2026-04-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "v292"
down_revision: Union[str, None] = "v291"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── kds_piecework_records ──
    op.execute("""
    CREATE TABLE kds_piecework_records (
        tenant_id            UUID          NOT NULL,
        id                   UUID          DEFAULT gen_random_uuid() PRIMARY KEY,
        store_id             UUID          NOT NULL,
        employee_id          UUID          NOT NULL,
        shift_date           DATE          NOT NULL,
        dish_id              UUID,
        dish_name            VARCHAR(100),
        practice_names       TEXT,
        quantity             INTEGER       DEFAULT 1,
        unit_commission_fen  INTEGER       DEFAULT 0,
        total_commission_fen INTEGER       DEFAULT 0,
        confirmed_by         VARCHAR(20)   DEFAULT 'auto',
        kds_task_id          UUID,
        recorded_at          TIMESTAMPTZ   DEFAULT now(),
        created_at           TIMESTAMPTZ   DEFAULT now(),
        updated_at           TIMESTAMPTZ   DEFAULT now(),
        is_deleted           BOOLEAN       DEFAULT FALSE
    );

    ALTER TABLE kds_piecework_records ENABLE ROW LEVEL SECURITY;
    CREATE POLICY kds_piecework_records_tenant ON kds_piecework_records
        USING (tenant_id = current_setting('app.tenant_id', true)::UUID);

    CREATE INDEX ix_kds_piecework_records_tenant_store_date
        ON kds_piecework_records (tenant_id, store_id, shift_date);
    CREATE INDEX ix_kds_piecework_records_employee
        ON kds_piecework_records (tenant_id, employee_id, shift_date);
    CREATE UNIQUE INDEX ux_kds_piecework_records_task
        ON kds_piecework_records (kds_task_id) WHERE kds_task_id IS NOT NULL;
    """)

    # ── kds_piecework_schemes ──
    op.execute("""
    CREATE TABLE kds_piecework_schemes (
        tenant_id       UUID          NOT NULL,
        id              UUID          DEFAULT gen_random_uuid() PRIMARY KEY,
        store_id        UUID,
        scheme_name     VARCHAR(100)  NOT NULL,
        scheme_type     VARCHAR(20)   CHECK (scheme_type IN ('by_dish', 'by_practice', 'by_station')),
        is_active       BOOLEAN       DEFAULT TRUE,
        rules           JSONB         NOT NULL DEFAULT '[]',
        effective_from  DATE          NOT NULL,
        effective_until DATE,
        created_at      TIMESTAMPTZ   DEFAULT now(),
        updated_at      TIMESTAMPTZ   DEFAULT now(),
        is_deleted      BOOLEAN       DEFAULT FALSE
    );

    ALTER TABLE kds_piecework_schemes ENABLE ROW LEVEL SECURITY;
    CREATE POLICY kds_piecework_schemes_tenant ON kds_piecework_schemes
        USING (tenant_id = current_setting('app.tenant_id', true)::UUID);

    CREATE INDEX ix_kds_piecework_schemes_tenant_store
        ON kds_piecework_schemes (tenant_id, store_id);
    """)

    # ── kds_display_configs ──
    op.execute("""
    CREATE TABLE kds_display_configs (
        tenant_id       UUID          NOT NULL,
        id              UUID          DEFAULT gen_random_uuid() PRIMARY KEY,
        store_id        UUID          NOT NULL,
        station_id      UUID,
        config_key      VARCHAR(50)   NOT NULL,
        config_value    JSONB         NOT NULL,
        created_at      TIMESTAMPTZ   DEFAULT now(),
        updated_at      TIMESTAMPTZ   DEFAULT now(),
        is_deleted      BOOLEAN       DEFAULT FALSE
    );

    ALTER TABLE kds_display_configs ENABLE ROW LEVEL SECURITY;
    CREATE POLICY kds_display_configs_tenant ON kds_display_configs
        USING (tenant_id = current_setting('app.tenant_id', true)::UUID);

    CREATE UNIQUE INDEX ux_kds_display_configs_key
        ON kds_display_configs (
            tenant_id,
            store_id,
            COALESCE(station_id, '00000000-0000-0000-0000-000000000000'::UUID),
            config_key
        );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS kds_display_configs CASCADE;")
    op.execute("DROP TABLE IF EXISTS kds_piecework_schemes CASCADE;")
    op.execute("DROP TABLE IF EXISTS kds_piecework_records CASCADE;")
