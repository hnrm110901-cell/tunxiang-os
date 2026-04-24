"""v287 — 桌台利用率物化视图（mv_table_utilization）

为 tx-agent 桌台调度提供结构化数据。
从 dining_sessions + tables + table_zones + store_market_sessions 聚合计算。

Agent 决策场景：
1. 识别低利用率桌台 → 建议拼桌或关闭
2. 发现翻台率异常 → 建议调整用餐时限
3. 分析座位利用率 → 建议调整桌型配置

Revision ID: v287
Revises: v286
Create Date: 2026-04-24
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "v287"
down_revision: Union[str, None] = "v286"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 物化视图：桌台利用率聚合 ──────────────────────────────────────────
    op.execute("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS mv_table_utilization AS
        SELECT
            ds.tenant_id,
            ds.store_id,
            ds.table_id,
            t.zone_id,
            tz.zone_type,
            tz.zone_name,
            ds.market_session_id,
            DATE(ds.opened_at AT TIME ZONE 'Asia/Shanghai') AS biz_date,
            ds.service_mode,

            -- 翻台指标
            COUNT(*)                     AS session_count,
            AVG(ds.guest_count)          AS avg_guest_count,

            -- 消费指标（分）
            AVG(ds.total_amount_fen)     AS avg_total_fen,
            AVG(ds.final_amount_fen)     AS avg_final_fen,
            AVG(ds.per_capita_fen)       AS avg_per_capita_fen,
            SUM(ds.final_amount_fen)     AS sum_final_fen,

            -- 时长指标（分钟）
            AVG(
                EXTRACT(EPOCH FROM (
                    COALESCE(ds.paid_at, ds.cleared_at, ds.updated_at) - ds.opened_at
                )) / 60
            ) AS avg_duration_min,

            -- 座位利用率
            AVG(ds.guest_count::NUMERIC / GREATEST(t.seats, 1))
                AS avg_seat_utilization,

            -- 服务质量
            AVG(ds.service_call_count)   AS avg_service_calls,
            AVG(ds.discount_amount_fen)  AS avg_discount_fen

        FROM dining_sessions ds
            JOIN tables t
                ON ds.table_id = t.id AND ds.tenant_id = t.tenant_id
            LEFT JOIN table_zones tz
                ON t.zone_id = tz.id AND t.tenant_id = tz.tenant_id
        WHERE ds.is_deleted = FALSE
          AND ds.status IN ('paid', 'clearing')
        GROUP BY
            ds.tenant_id, ds.store_id, ds.table_id,
            t.zone_id, tz.zone_type, tz.zone_name,
            ds.market_session_id,
            DATE(ds.opened_at AT TIME ZONE 'Asia/Shanghai'),
            ds.service_mode
    """)

    # ── 唯一索引（支持 REFRESH CONCURRENTLY）──────────────────────────────
    op.execute("""
        CREATE UNIQUE INDEX idx_mv_tu_pk
        ON mv_table_utilization (
            tenant_id, store_id, table_id, market_session_id, biz_date
        )
    """)

    # 注意：物化视图不需要 RLS（通过查询时 WHERE tenant_id 过滤）


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_table_utilization")
