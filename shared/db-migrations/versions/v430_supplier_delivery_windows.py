"""v430 — supplier_delivery_windows + supplier_delivery_violations（PRD-05 / Phase 2 W8 / Tier 1 食安）

业务背景：
  生鲜必须 4-7 点到货（厨房 9 点开档前完成质检/分拣）。供应商晚到 10 分钟 = 当餐
  缺菜。屯象 smart_replenishment 是 AI 建议，无硬约束 — 本 PR 把时间窗变成物理约束，
  违约自动扣 supplier_scoring.delivery_rate 分。

设计要点：
  1. supplier_delivery_windows — 时间窗配置（按 supplier × store × weekday_mask 维度）
     - weekday_mask:   1-127 bitmask（位 0 = 周一 ... 位 6 = 周日；7 位齐全 = 127）
     - earliest_time / latest_time:  配送时间窗（TIME 不含日期）
     - grace_minutes:  容忍度（earliest - grace ~ latest + grace 算合规）
     - auto_reject_on_late: 保留字段，default FALSE — P0 仅记录，不自动拒收
     - approved_by / approved_at: 二级审批（NULL = 草稿；NOT NULL = 已生效）
  2. supplier_delivery_violations — 违约记录（append-only log）
     - receiving_order_id / supplier_id / store_id
     - scheduled_earliest / scheduled_latest:  签收时刻的时间窗快照
     - actual_signed_at:    实际签收 TIMESTAMPTZ
     - violation_minutes:   超出窗口分钟数（晚到为正；早到亦正用 ABS）
     - 由 supplier_scoring_engine._aggregate_dimensions_from_db 按 period 聚合扣分

  3. RLS 标准模式：tenant_id::text = current_setting('app.tenant_id', true)
  4. inspector-and-skip 模式（与 v421/v423/v424/v428/v429 一致）

Revision ID: v430_supplier_delivery_windows
Revises: v429_ingredient_yield_standards
Create Date: 2026-05-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v430_supplier_delivery_windows"
down_revision: Union[str, Sequence[str], None] = "v429_ingredient_yield_standards"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    # ───── 配置表 ───────────────────────────────────────────────────────────
    if "supplier_delivery_windows" not in existing:
        op.execute(
            """
            CREATE TABLE supplier_delivery_windows (
                id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id               UUID NOT NULL,
                supplier_id             UUID NOT NULL,
                store_id                UUID NOT NULL,
                weekday_mask            INTEGER NOT NULL DEFAULT 127,
                earliest_time           TIME NOT NULL,
                latest_time             TIME NOT NULL,
                grace_minutes           INTEGER NOT NULL DEFAULT 15,
                auto_reject_on_late     BOOLEAN NOT NULL DEFAULT FALSE,
                approved_by             UUID,
                approved_at             TIMESTAMPTZ,
                notes                   TEXT,
                created_by              UUID NOT NULL,
                created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                is_deleted              BOOLEAN NOT NULL DEFAULT FALSE,
                CONSTRAINT chk_sdw_weekday_mask_range
                    CHECK (weekday_mask >= 1 AND weekday_mask <= 127),
                CONSTRAINT chk_sdw_grace_minutes_range
                    CHECK (grace_minutes >= 0 AND grace_minutes <= 240),
                CONSTRAINT chk_sdw_time_order
                    CHECK (earliest_time < latest_time)
            )
            """
        )

        op.execute("ALTER TABLE supplier_delivery_windows ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE supplier_delivery_windows FORCE ROW LEVEL SECURITY")

        op.execute(
            """
            CREATE POLICY supplier_delivery_windows_tenant_isolation
            ON supplier_delivery_windows
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
            """
        )

        # 主查询路径：按 supplier × store 找配置（receiving 主流程会反复查）
        op.execute(
            """
            CREATE INDEX idx_sdw_tenant_supplier_store
            ON supplier_delivery_windows (tenant_id, supplier_id, store_id)
            """
        )

        # active 配置覆盖索引（部分索引压缩存储）
        op.execute(
            """
            CREATE INDEX idx_sdw_active
            ON supplier_delivery_windows (tenant_id, supplier_id, store_id, weekday_mask)
            WHERE approved_by IS NOT NULL AND is_deleted = FALSE
            """
        )

    # ───── 违约日志表 ─────────────────────────────────────────────────────────
    if "supplier_delivery_violations" not in existing:
        op.execute(
            """
            CREATE TABLE supplier_delivery_violations (
                id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id               UUID NOT NULL,
                supplier_id             UUID NOT NULL,
                store_id                UUID NOT NULL,
                receiving_order_id      UUID NOT NULL,
                window_id               UUID,
                scheduled_earliest      TIME NOT NULL,
                scheduled_latest        TIME NOT NULL,
                actual_signed_at        TIMESTAMPTZ NOT NULL,
                violation_minutes       INTEGER NOT NULL,
                violation_kind          VARCHAR(10) NOT NULL,
                recorded_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT chk_sdv_violation_kind
                    CHECK (violation_kind IN ('late', 'early')),
                CONSTRAINT chk_sdv_violation_minutes_positive
                    CHECK (violation_minutes > 0)
            )
            """
        )

        op.execute("ALTER TABLE supplier_delivery_violations ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE supplier_delivery_violations FORCE ROW LEVEL SECURITY")

        op.execute(
            """
            CREATE POLICY supplier_delivery_violations_tenant_isolation
            ON supplier_delivery_violations
            USING (tenant_id::text = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
            """
        )

        # supplier_scoring_engine 聚合主查询路径（按 supplier + 时间区间）
        op.execute(
            """
            CREATE INDEX idx_sdv_tenant_supplier_recorded
            ON supplier_delivery_violations (tenant_id, supplier_id, recorded_at)
            """
        )

        # receiving_order 反查（一单一记录的唯一性 — 防重复 record）
        op.execute(
            """
            CREATE UNIQUE INDEX uq_sdv_receiving_order
            ON supplier_delivery_violations (tenant_id, receiving_order_id)
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "supplier_delivery_violations" in existing:
        op.execute("DROP TABLE supplier_delivery_violations CASCADE")
    if "supplier_delivery_windows" in existing:
        op.execute("DROP TABLE supplier_delivery_windows CASCADE")
