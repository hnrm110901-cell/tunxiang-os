"""[Tier1][SECURITY] v406 — NLQ reports schema 收尾视图 (4 个 mv_* 全暴露完成)

S4-02 PR2 (issue #289) 子拆 PR2.A.3 — 续补 NLQ 沙箱可读视图，收尾 mv_* 8 表暴露层：

  - reports.discount_health    ← mv_discount_health    去 top_operators(PII)
  - reports.inventory_bom      ← mv_inventory_bom      全暴露（食材损耗聚合）
  - reports.safety_compliance  ← mv_safety_compliance  去 expiry_alerts/overdue_certificates JSONB 明细
  - reports.energy_efficiency  ← mv_energy_efficiency  去 off_hours_anomalies JSONB 明细

延续 v404/v405 模式（PR2.A #325 / PR2.A.2 #326）：
  - 视图 WITH (security_invoker = on)（PG 15+）— RLS 跟调用者 app.tenant_id
  - GRANT SELECT 给 v404 已建的 tx_nlq_readonly role
  - 不引入新 role / schema
  - JSONB 明细字段一律不暴露（含批次/证件/操作员等 PII 风险）

收尾完成 mv_* 8 表全部暴露：
  - daily_revenue / member_clv（v404, #325）
  - store_pnl / channel_margin（v405, #326）
  - discount_health / inventory_bom / safety_compliance / energy_efficiency（本迁移）

Revision ID: v406_nlq_reports_views_p3
Revises: v405_nlq_reports_views_p2
Create Date: 2026-05-09
"""

from typing import Sequence, Union

from alembic import op

revision: str = "v406_nlq_reports_views_p3"
down_revision: Union[str, None] = "v405_nlq_reports_views_p2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ROLE = "tx_nlq_readonly"
_SCHEMA = "reports"


def upgrade() -> None:
    # 1. reports.discount_health ← mv_discount_health（去 top_operators PII）
    op.execute(f"DROP VIEW IF EXISTS {_SCHEMA}.discount_health;")
    op.execute(
        f"""
        CREATE VIEW {_SCHEMA}.discount_health
        WITH (security_invoker = on) AS
        SELECT
            tenant_id,
            store_id,
            stat_date AS day,
            total_orders,
            discounted_orders,
            discount_rate,
            total_discount_fen,
            unauthorized_count,
            leak_types,
            threshold_breaches
            -- 不暴露 top_operators（操作员 PII）/ last_event_id / updated_at
        FROM mv_discount_health;
        """
    )
    op.execute(
        f"COMMENT ON VIEW {_SCHEMA}.discount_health IS "
        f"'NLQ readonly: 折扣健康日聚合，去操作员 PII（issue #289 PR2.A.3）'"
    )

    # 2. reports.inventory_bom ← mv_inventory_bom（食材聚合，无敏感字段）
    op.execute(f"DROP VIEW IF EXISTS {_SCHEMA}.inventory_bom;")
    op.execute(
        f"""
        CREATE VIEW {_SCHEMA}.inventory_bom
        WITH (security_invoker = on) AS
        SELECT
            tenant_id,
            store_id,
            stat_date AS day,
            ingredient_id,
            ingredient_name,
            theoretical_usage_g,
            actual_usage_g,
            waste_g,
            unexplained_loss_g,
            loss_rate
            -- 不暴露 last_event_id / updated_at
        FROM mv_inventory_bom;
        """
    )
    op.execute(
        f"COMMENT ON VIEW {_SCHEMA}.inventory_bom IS "
        f"'NLQ readonly: 食材 BOM 损耗日聚合（issue #289 PR2.A.3）'"
    )

    # 3. reports.safety_compliance ← mv_safety_compliance（去 JSONB 明细）
    op.execute(f"DROP VIEW IF EXISTS {_SCHEMA}.safety_compliance;")
    op.execute(
        f"""
        CREATE VIEW {_SCHEMA}.safety_compliance
        WITH (security_invoker = on) AS
        SELECT
            tenant_id,
            store_id,
            stat_week AS week_start,
            sample_logged_count,
            inspection_required,
            inspection_done,
            inspection_rate,
            violation_count,
            compliance_score
            -- 不暴露 expiry_alerts / overdue_certificates（JSONB 明细含批次/证件 PII）
            -- 不暴露 last_event_id / updated_at
        FROM mv_safety_compliance;
        """
    )
    op.execute(
        f"COMMENT ON VIEW {_SCHEMA}.safety_compliance IS "
        f"'NLQ readonly: 食安合规周聚合，去 JSONB 明细（issue #289 PR2.A.3）'"
    )

    # 4. reports.energy_efficiency ← mv_energy_efficiency（去异常明细 JSONB）
    op.execute(f"DROP VIEW IF EXISTS {_SCHEMA}.energy_efficiency;")
    op.execute(
        f"""
        CREATE VIEW {_SCHEMA}.energy_efficiency
        WITH (security_invoker = on) AS
        SELECT
            tenant_id,
            store_id,
            stat_date AS day,
            electricity_kwh,
            gas_m3,
            water_ton,
            energy_cost_fen,
            revenue_fen,
            energy_revenue_ratio,
            anomaly_count
            -- 不暴露 off_hours_anomalies（JSONB 异常明细 / 设备 ID）
            -- 不暴露 last_event_id / updated_at
        FROM mv_energy_efficiency;
        """
    )
    op.execute(
        f"COMMENT ON VIEW {_SCHEMA}.energy_efficiency IS "
        f"'NLQ readonly: 能耗效率日聚合，去 JSONB 明细（issue #289 PR2.A.3）'"
    )

    # 5. GRANT SELECT — role 已存在（v404 建），只补视图权限
    op.execute(f"GRANT SELECT ON {_SCHEMA}.discount_health TO {_ROLE};")
    op.execute(f"GRANT SELECT ON {_SCHEMA}.inventory_bom TO {_ROLE};")
    op.execute(f"GRANT SELECT ON {_SCHEMA}.safety_compliance TO {_ROLE};")
    op.execute(f"GRANT SELECT ON {_SCHEMA}.energy_efficiency TO {_ROLE};")


def downgrade() -> None:
    # 反向：先撤 GRANT，再 DROP 视图
    op.execute(f"REVOKE ALL ON {_SCHEMA}.discount_health FROM {_ROLE};")
    op.execute(f"REVOKE ALL ON {_SCHEMA}.inventory_bom FROM {_ROLE};")
    op.execute(f"REVOKE ALL ON {_SCHEMA}.safety_compliance FROM {_ROLE};")
    op.execute(f"REVOKE ALL ON {_SCHEMA}.energy_efficiency FROM {_ROLE};")
    op.execute(f"DROP VIEW IF EXISTS {_SCHEMA}.energy_efficiency;")
    op.execute(f"DROP VIEW IF EXISTS {_SCHEMA}.safety_compliance;")
    op.execute(f"DROP VIEW IF EXISTS {_SCHEMA}.inventory_bom;")
    op.execute(f"DROP VIEW IF EXISTS {_SCHEMA}.discount_health;")
    # ROLE / SCHEMA 不主动删（v404 owner，cluster-level）
