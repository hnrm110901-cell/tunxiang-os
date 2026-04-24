#!/usr/bin/env bash
# Sprint D2（v264）: 刷新 mv_agent_roi_monthly 物化视图
#
# 用法:
#   DATABASE_URL=postgresql://... ./scripts/refresh_mv_agent_roi.sh
#
# 策略:
#   1) 若视图从未 refresh 过（首次填充）→ 普通 REFRESH（必须锁表，无 CONCURRENTLY）
#   2) 后续 refresh → 使用 CONCURRENTLY（依赖 idx_mv_agent_roi_monthly_pk 唯一索引，
#      不阻塞读，兼容大数据量场景）
#   3) 出错时打印日志但不静默失败，方便 cron 告警
#
# cron 编排：建议每日 05:00 执行一次（留后续 PR 接入 infra/cron）。

set -euo pipefail

: "${DATABASE_URL:?DATABASE_URL must be set, e.g. postgresql://tunxiang:changeme_dev@localhost/tunxiang_os}"

echo "[refresh_mv_agent_roi] $(date -Iseconds) starting refresh…"

# populated 字段判断视图是否已首次填充
POPULATED=$(psql "$DATABASE_URL" -At -c \
    "SELECT ispopulated FROM pg_matviews WHERE matviewname = 'mv_agent_roi_monthly';" || echo "")

if [[ "$POPULATED" == "f" ]]; then
    echo "[refresh_mv_agent_roi] first-time populate, using plain REFRESH…"
    psql "$DATABASE_URL" -c "REFRESH MATERIALIZED VIEW mv_agent_roi_monthly;"
elif [[ "$POPULATED" == "t" ]]; then
    echo "[refresh_mv_agent_roi] incremental refresh, using CONCURRENTLY…"
    psql "$DATABASE_URL" -c "REFRESH MATERIALIZED VIEW CONCURRENTLY mv_agent_roi_monthly;"
else
    echo "[refresh_mv_agent_roi] ERROR: mv_agent_roi_monthly not found (migration v264 not applied?)"
    exit 2
fi

echo "[refresh_mv_agent_roi] $(date -Iseconds) done."
