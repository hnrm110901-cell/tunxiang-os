"""[Tier1][SECURITY] v404 — NLQ readonly role + reports schema 视图（thin slice）

S4-02 PR2 (issue #289) 子拆 PR2.A — 建 NLQ 沙箱第二层 DB 防御：

  1. CREATE SCHEMA reports — 暴露给 LLM 的安全 schema（仅含脱敏视图）
  2. CREATE ROLE tx_nlq_readonly NOLOGIN — tx-brain runtime SET ROLE 进入
  3. 视图（thin slice，先 2 个示范，PR2.A.2+ 续补）：
       - reports.daily_revenue   ←  mv_daily_settlement（仅 closed 状态，去 cash_discrepancy）
       - reports.member_clv      ←  mv_member_clv（去 churn_probability，仅暴露汇总字段）
     用 security_invoker=on（PG 15+），让 RLS 跟调用者 app.tenant_id 走，
     而非视图 owner 的上下文 — 关键：避免 view owner 持 BYPASSRLS 权限时绕过隔离。
  4. GRANT USAGE ON SCHEMA reports + GRANT SELECT ON 各视图 TO tx_nlq_readonly
     **不 grant** USAGE ON SCHEMA public — 防止 LLM SQL 直接查 mv_*/orders/customers 等敏感原表

PR2.A 范围（本迁移）：thin slice — schema + role + 2 视图 + GRANT
PR2.A.2 / PR2.A.3 续补（独立 PR）：
  - 更多 reports 视图（mv_store_pnl / mv_channel_margin 等）
  - orders.* 脱敏视图（去支付明细 / phone / address，给 LLM 看订单聚合）

PR2 后续（独立 PR，依赖 PR2.A）：
  - PR2.B sql_generator.py 接 ModelRouter 调 Claude API + prompt 注入 reports schema
  - PR2.C POST /nlq/query SSE 端点 + main.py 注册
  - PR2.D 真 PG integration test（依赖 #323 follow-up 的 docker-compose-pg fixture）

部署约束（CLAUDE.md §17 Tier1 + §21 灰度）：
  - CREATE ROLE 是 cluster-level，已存在时用 DO $$ EXCEPTION 块兜底（幂等）
  - GRANT 是表级，毫秒完成
  - 无数据迁移；现有 SET ROLE 调用方等 PR2.B 上线时再启用，本迁移不影响生产
  - 灰度：dev → staging → prod，回滚阈值 LLM SQL 误命中率 > 1%

Revision ID: v404_nlq_readonly_views_role
Revises: v403_dashboard_pinned
Create Date: 2026-05-09
"""

from typing import Sequence, Union

from alembic import op

revision: str = "v404_nlq_readonly_views_role"
down_revision: Union[str, None] = "v403_dashboard_pinned"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ROLE = "tx_nlq_readonly"
_SCHEMA = "reports"


def upgrade() -> None:
    # 1. Schema — IF NOT EXISTS 幂等
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {_SCHEMA};")

    # 2. Role — PG 无 CREATE ROLE IF NOT EXISTS，用 EXCEPTION 块兜底
    op.execute(
        f"""
        DO $$
        BEGIN
            CREATE ROLE {_ROLE} NOLOGIN;
        EXCEPTION
            WHEN duplicate_object THEN
                RAISE NOTICE 'role {_ROLE} already exists, skip';
        END
        $$;
        """
    )

    # 3. 视图 — security_invoker=on 让 RLS 跟调用者 app.tenant_id 走
    # reports.daily_revenue ← mv_daily_settlement（仅 closed 状态 + 去敏字段）
    op.execute(f"DROP VIEW IF EXISTS {_SCHEMA}.daily_revenue;")
    op.execute(
        f"""
        CREATE VIEW {_SCHEMA}.daily_revenue
        WITH (security_invoker = on) AS
        SELECT
            tenant_id,
            store_id,
            stat_date AS day,
            total_revenue_fen,
            cash_system_fen,
            wechat_received_fen,
            alipay_received_fen,
            card_received_fen,
            stored_value_consumed_fen
            -- 不暴露 cash_discrepancy_fen / pending_items / closed_by（操作人 PII）
        FROM mv_daily_settlement
        WHERE status = 'closed';
        """
    )
    op.execute(
        f"COMMENT ON VIEW {_SCHEMA}.daily_revenue IS "
        f"'NLQ readonly: 已结算的日营收聚合，去差异/审核人字段（issue #289 PR2.A）'"
    )

    # reports.member_clv ← mv_member_clv（去 churn_probability/next_visit_days 预测字段）
    op.execute(f"DROP VIEW IF EXISTS {_SCHEMA}.member_clv;")
    op.execute(
        f"""
        CREATE VIEW {_SCHEMA}.member_clv
        WITH (security_invoker = on) AS
        SELECT
            tenant_id,
            customer_id,
            total_spend_fen,
            visit_count,
            voucher_used_count,
            voucher_cost_fen,
            stored_value_balance_fen,
            clv_fen,
            rfm_segment,
            last_visit_at
            -- 不暴露 churn_probability / next_visit_days（预测值，LLM 误用风险）
        FROM mv_member_clv;
        """
    )
    op.execute(
        f"COMMENT ON VIEW {_SCHEMA}.member_clv IS "
        f"'NLQ readonly: 会员 CLV 聚合，去预测字段（issue #289 PR2.A）'"
    )

    # 4. GRANT — 仅 reports schema USAGE + 视图 SELECT，不给 public
    op.execute(f"GRANT USAGE ON SCHEMA {_SCHEMA} TO {_ROLE};")
    op.execute(f"GRANT SELECT ON {_SCHEMA}.daily_revenue TO {_ROLE};")
    op.execute(f"GRANT SELECT ON {_SCHEMA}.member_clv TO {_ROLE};")

    # 防御：显式 REVOKE public schema USAGE 避免环境配置漂移
    # （PG 默认所有 role 隐式有 USAGE ON public，必须显式撤）
    op.execute(f"REVOKE ALL ON SCHEMA public FROM {_ROLE};")


def downgrade() -> None:
    # 反向：先撤 GRANT，再 DROP 视图，再 DROP role / schema
    op.execute(f"REVOKE ALL ON SCHEMA {_SCHEMA} FROM {_ROLE};")
    op.execute(f"REVOKE ALL ON {_SCHEMA}.daily_revenue FROM {_ROLE};")
    op.execute(f"REVOKE ALL ON {_SCHEMA}.member_clv FROM {_ROLE};")
    op.execute(f"DROP VIEW IF EXISTS {_SCHEMA}.member_clv;")
    op.execute(f"DROP VIEW IF EXISTS {_SCHEMA}.daily_revenue;")
    # ROLE / SCHEMA 不主动删（cluster-level，可能被其他迁移依赖）；
    # 真要清理走运维手动 DROP ROLE / DROP SCHEMA CASCADE
