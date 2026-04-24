"""v161 — sync_logs 增强 + sync_health_scores 视图

在 v141 创建的 sync_logs 表上增加三个字段：
  error_detail   TEXT          — 失败原因详情（完整堆栈 / API 响应体，比 error_msg 更丰富）
  retry_count    INT DEFAULT 0 — 本次任务已重试次数（0 = 首次成功或首次失败）
  next_retry_at  TIMESTAMPTZ   — 计划的下次重试时间（NULL 表示不再重试 / 已成功）

同时创建 sync_health_scores 视图，汇总各商户最近 7 天每类同步的成功率，
供运营大屏和 GET /api/v1/sync/health 端点直接查询。

视图字段：
  tenant_id        — 租户 ID
  merchant_code    — 商户代码（czyz / zqx / sgc）
  sync_type        — 同步类型
  total_runs       — 7 天内执行次数
  success_runs     — 其中成功次数
  failed_runs      — 其中失败次数
  success_rate     — 成功率（0.00–1.00，保留 4 位小数）
  avg_records      — 平均同步记录数
  last_run_at      — 最近一次执行时间
  last_status      — 最近一次状态
  window_start     — 统计窗口起点（NOW() - INTERVAL '7 days'）

Revision ID: v161
Revises: v160
Create Date: 2026-04-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "v161"
down_revision = "v160"
branch_labels = None
depends_on = None

_TABLE = "sync_logs"
_VIEW = "sync_health_scores"


def upgrade() -> None:
    # ── 1. 向 sync_logs 追加三个新字段 ─────────────────────────────────────

    # error_detail：完整失败详情（堆栈 / 上游 API 响应体），比 error_msg 更丰富
    op.add_column(
        _TABLE,
        sa.Column("error_detail", sa.Text, nullable=True, comment="失败原因详情（完整堆栈或上游响应体）"),
    )

    # retry_count：本次任务已重试次数（_with_retry 最多重试 3 次）
    op.add_column(
        _TABLE,
        sa.Column(
            "retry_count",
            sa.Integer,
            nullable=False,
            server_default="0",
            comment="已重试次数（0 = 首次尝试，最大值 = RETRY_TIMES - 1）",
        ),
    )

    # next_retry_at：下次计划重试时间（NULL 表示无需再重试）
    op.add_column(
        _TABLE,
        sa.Column(
            "next_retry_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="下次计划重试时间（NULL 表示已成功或已放弃）",
        ),
    )

    # 为常见查询场景追加索引
    op.create_index("idx_sync_logs_retry_count", _TABLE, ["retry_count"])
    op.create_index("idx_sync_logs_next_retry_at", _TABLE, ["next_retry_at"])

    # ── 2. 创建 sync_health_scores 视图 ─────────────────────────────────────
    op.execute(
        f"""
        CREATE OR REPLACE VIEW {_VIEW} AS
        SELECT
            tenant_id,
            merchant_code,
            sync_type,
            COUNT(*)                                                    AS total_runs,
            COUNT(*) FILTER (WHERE status = 'success')                  AS success_runs,
            COUNT(*) FILTER (WHERE status IN ('failed', 'partial'))     AS failed_runs,
            ROUND(
                COUNT(*) FILTER (WHERE status = 'success')::NUMERIC
                / NULLIF(COUNT(*), 0),
                4
            )                                                           AS success_rate,
            ROUND(AVG(records_synced), 0)::INT                         AS avg_records,
            MAX(started_at)                                             AS last_run_at,
            (
                SELECT sl2.status
                FROM sync_logs sl2
                WHERE sl2.tenant_id      = sl.tenant_id
                  AND sl2.merchant_code  = sl.merchant_code
                  AND sl2.sync_type      = sl.sync_type
                ORDER BY sl2.started_at DESC
                LIMIT 1
            )                                                           AS last_status,
            (NOW() - INTERVAL '7 days')::TIMESTAMPTZ                   AS window_start
        FROM sync_logs sl
        WHERE started_at >= NOW() - INTERVAL '7 days'
        GROUP BY tenant_id, merchant_code, sync_type
        """
    )


def downgrade() -> None:
    # 删除视图
    op.execute(f"DROP VIEW IF EXISTS {_VIEW}")

    # 删除新增索引
    op.drop_index("idx_sync_logs_next_retry_at", _TABLE)
    op.drop_index("idx_sync_logs_retry_count", _TABLE)

    # 删除新增字段
    op.drop_column(_TABLE, "next_retry_at")
    op.drop_column(_TABLE, "retry_count")
    op.drop_column(_TABLE, "error_detail")
