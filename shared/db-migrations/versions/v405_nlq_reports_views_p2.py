"""[Tier1][SECURITY] v405 — NLQ reports schema 续补视图（store_pnl / channel_margin）

S4-02 PR2 (issue #289) 子拆 PR2.A.2 — 续补 NLQ 沙箱可读视图：

  - reports.store_pnl       ← mv_store_pnl       （门店 P&L 聚合，老板仪表盘最常问）
  - reports.channel_margin  ← mv_channel_margin  （渠道真实毛利，渠道决策最常问）

延续 v404 模式（PR2.A #325）：
  - 视图 WITH (security_invoker = on)（PG 15+）— RLS 跟调用者 app.tenant_id
  - GRANT SELECT 给 tx_nlq_readonly role
  - 字段全聚合（无 PII / 无操作员信息）→ 全列暴露
  - 不引入新 role / schema（v404 已建好）

部署约束（CLAUDE.md §17 Tier1 + §21 灰度）：
  - 无数据迁移；新视图仅 GRANT SELECT，不影响现有读路径
  - downgrade 反向 REVOKE + DROP VIEW（保留 role/schema 防误删）

Revision ID: v405_nlq_reports_views_p2
Revises: v404_nlq_readonly_views_role
Create Date: 2026-05-09
"""

from typing import Sequence, Union

from alembic import op

revision: str = "v405_nlq_reports_views_p2"
down_revision: Union[str, None] = "v404_nlq_readonly_views_role"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ROLE = "tx_nlq_readonly"
_SCHEMA = "reports"


def upgrade() -> None:
    # 1. reports.store_pnl ← mv_store_pnl（老板仪表盘聚合，全字段无敏感）
    op.execute(f"DROP VIEW IF EXISTS {_SCHEMA}.store_pnl;")
    op.execute(
        f"""
        CREATE VIEW {_SCHEMA}.store_pnl
        WITH (security_invoker = on) AS
        SELECT
            tenant_id,
            brand_id,
            store_id,
            stat_date AS day,
            gross_revenue_fen,
            net_revenue_fen,
            cogs_fen,
            gross_profit_fen,
            gross_margin_rate,
            labor_cost_fen,
            overhead_fen,
            net_profit_fen,
            order_count,
            customer_count,
            avg_check_fen,
            stored_value_new_fen,
            stored_value_consumed_fen
            -- 不暴露 last_event_id / updated_at（实现细节）
        FROM mv_store_pnl;
        """
    )
    op.execute(
        f"COMMENT ON VIEW {_SCHEMA}.store_pnl IS "
        f"'NLQ readonly: 门店 P&L 日聚合（issue #289 PR2.A.2）'"
    )

    # 2. reports.channel_margin ← mv_channel_margin（渠道真实毛利，全字段无敏感）
    op.execute(f"DROP VIEW IF EXISTS {_SCHEMA}.channel_margin;")
    op.execute(
        f"""
        CREATE VIEW {_SCHEMA}.channel_margin
        WITH (security_invoker = on) AS
        SELECT
            tenant_id,
            store_id,
            stat_date AS day,
            channel,
            gross_revenue_fen,
            commission_fen,
            promotion_subsidy_fen,
            net_revenue_fen,
            cogs_fen,
            gross_margin_fen,
            gross_margin_rate,
            order_count
            -- 不暴露 last_event_id / updated_at（实现细节）
        FROM mv_channel_margin;
        """
    )
    op.execute(
        f"COMMENT ON VIEW {_SCHEMA}.channel_margin IS "
        f"'NLQ readonly: 渠道真实毛利日聚合（issue #289 PR2.A.2）'"
    )

    # 3. GRANT SELECT — role 已存在（v404 建），只补视图权限
    op.execute(f"GRANT SELECT ON {_SCHEMA}.store_pnl TO {_ROLE};")
    op.execute(f"GRANT SELECT ON {_SCHEMA}.channel_margin TO {_ROLE};")


def downgrade() -> None:
    # 反向：先撤 GRANT，再 DROP 视图
    op.execute(f"REVOKE ALL ON {_SCHEMA}.store_pnl FROM {_ROLE};")
    op.execute(f"REVOKE ALL ON {_SCHEMA}.channel_margin FROM {_ROLE};")
    op.execute(f"DROP VIEW IF EXISTS {_SCHEMA}.channel_margin;")
    op.execute(f"DROP VIEW IF EXISTS {_SCHEMA}.store_pnl;")
    # ROLE / SCHEMA 不主动删（v404 owner，cluster-level）
