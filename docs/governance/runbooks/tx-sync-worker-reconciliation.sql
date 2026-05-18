-- =============================================================================
-- tx-sync-worker sync_logs 7d 对账 SQL Runbook (W3 D3 Prep-3)
-- =============================================================================
-- 用于 W4 cutover (5/25-6/1) Phase 1 dry_run 一周观察期对账验收.
--
-- 数据模型: PR #819 (hotfix #805 P0-2) 重设计后, sync-worker dry_run 路径
--   `pinzhi_sync._record_dry_run` 写 sync_logs 表 status='dry_run' (与
--   gateway 真路径 status='success' 区分). 同 (day, merchant_code, sync_type)
--   两侧 count 差异 ≤ 10% 即通过.
--
-- 范围:
--   - pinzhi 4 jobs × 3 merchants (czyz/zqx/sgc) × 5+ sync_types × 7d
--     ≈ 30 (merchant, sync_type) 组 → SQL 双边对账主轨
--   - wecom_sop 1 job 无 merchant_code → Prometheus 监控例外
--     (`tx_sync_worker_executions_total{job=wecom_group_daily_sop}`)
--
-- 引用:
--   - 父 issue: #806 (Phase 2 follow-up DOD § "W4 对账验收")
--   - hotfix PR: #819 (P0-2 对账机制重设计)
--   - 父 PR: #805 (Phase 1 ship)
--   - rollback runbook: docs/governance/runbooks/tx-sync-worker-cutover-rollback.sh (W3 D3 Prep-1)
--   - dashboard: infra/monitoring/grafana/dashboards/tx-sync-worker-reconciliation.json
--
-- RLS 约束 (CLAUDE.md §10 + memory `feedback_async_session_select_pollution.md`):
--   所有 query 必含 `tenant_id = current_setting('app.tenant_id', true)::uuid`,
--   ops 跑前需 `SET LOCAL app.tenant_id = '<uuid>';` per merchant.
--   多租户汇总 query 标 [BYPASSRLS] 由 prod DB role 持 BYPASSRLS 跑 (与
--   wecom_sop.py:79-82 同语义, FU-7 prod role verify 前置).
-- =============================================================================


-- -----------------------------------------------------------------------------
-- Query 1 (主对账): 同 (day, merchant_code, sync_type) success vs dry_run delta
-- -----------------------------------------------------------------------------
-- 用途: W4 Day-7 (6/1) 对账主入口, 4 pinzhi jobs × 3 merchants × ~5 sync_types
--       × 7 days ≈ 30 组合, 任一 delta > 10% → 调查阻塞 Phase 2 cutover.
-- 输入: 单租户 (设 `SET LOCAL app.tenant_id`); 时间窗 NOW() - 7d
-- 输出: day, merchant_code, sync_type, success_count, dry_run_count, delta_pct
--       (NULL 当 dry_run_count=0, ORDER BY delta_pct DESC NULLS LAST 突出异常)
-- 用法: ops 在 W4 Day-7 跑 3 次 (每租户一次 `SET LOCAL` 切换 tenant_id),
--       结果写 `docs/governance/decisions/2026-W4-tx-sync-worker-cutover-reconciliation.md`
--       SQL snapshot 双边对账段.

SELECT
    DATE(started_at AT TIME ZONE 'Asia/Shanghai') AS day,
    merchant_code,
    sync_type,
    COUNT(*) FILTER (WHERE status = 'success') AS success_count,
    COUNT(*) FILTER (WHERE status = 'dry_run') AS dry_run_count,
    ABS(
        COUNT(*) FILTER (WHERE status = 'success')::float
        - COUNT(*) FILTER (WHERE status = 'dry_run')::float
    ) / NULLIF(COUNT(*) FILTER (WHERE status = 'dry_run'), 0) * 100 AS delta_pct
FROM sync_logs
WHERE started_at >= NOW() - INTERVAL '7 days'
  AND tenant_id = current_setting('app.tenant_id', true)::uuid
GROUP BY 1, 2, 3
ORDER BY 1 DESC, delta_pct DESC NULLS LAST;


-- -----------------------------------------------------------------------------
-- Query 2 (per-merchant 7d 趋势): 单 merchant 维度日级 success vs dry_run 走势
-- -----------------------------------------------------------------------------
-- 用途: Q1 主对账发现某 merchant delta 异常时, 钻入看日级 ramp-up / dip
--       (例: cron 5min drift 累积 / pinzhi API 单日 429 限流).
-- 输入: 单租户 + 单 merchant_code (替换 :merchant_code)
-- 输出: day, sync_type, success_count, dry_run_count, success_ratio
-- 用法: psql 单 query 跑, 看连续 7d 是否有"突变日"(某日突然 0 success
--       或 0 dry_run); Grafana dashboard panel #3 同等可视化.

SELECT
    DATE(started_at AT TIME ZONE 'Asia/Shanghai') AS day,
    sync_type,
    COUNT(*) FILTER (WHERE status = 'success') AS success_count,
    COUNT(*) FILTER (WHERE status = 'dry_run') AS dry_run_count,
    ROUND(
        COUNT(*) FILTER (WHERE status = 'success')::numeric
        / NULLIF(COUNT(*), 0),
        4
    ) AS success_ratio
FROM sync_logs
WHERE started_at >= NOW() - INTERVAL '7 days'
  AND tenant_id = current_setting('app.tenant_id', true)::uuid
  AND merchant_code = :'merchant_code'  -- 'czyz' | 'zqx' | 'sgc'
GROUP BY 1, 2
ORDER BY 1 DESC, 2;


-- -----------------------------------------------------------------------------
-- Query 3 (records_synced 差异): 真路径 vs dry_run 同维度 records 数比较
-- -----------------------------------------------------------------------------
-- 用途: dry_run 路径 records_synced 写 0 (per pinzhi_sync.py:_record_dry_run),
--       真路径写实际同步条数. 该 query 暴露真路径 records_synced 数量级
--       (FU-6 sync_health_scores view 受 dry_run 0 行污染配套观察).
-- 输入: 单租户; 时间窗 7d
-- 输出: day, merchant_code, sync_type, success_avg_records, success_max_records,
--       dry_run_rows (期望全 0, 任何非 0 行 → P0-2 写入 bug)
-- 用法: W4 Day-7 跑, 验证 dry_run_rows 全 0 (反向 sanity check 对账实现正确).

SELECT
    DATE(started_at AT TIME ZONE 'Asia/Shanghai') AS day,
    merchant_code,
    sync_type,
    ROUND(AVG(records_synced) FILTER (WHERE status = 'success'), 1) AS success_avg_records,
    MAX(records_synced) FILTER (WHERE status = 'success') AS success_max_records,
    SUM(records_synced) FILTER (WHERE status = 'dry_run') AS dry_run_rows
FROM sync_logs
WHERE started_at >= NOW() - INTERVAL '7 days'
  AND tenant_id = current_setting('app.tenant_id', true)::uuid
GROUP BY 1, 2, 3
ORDER BY 1 DESC, 2, 3;


-- -----------------------------------------------------------------------------
-- Query 4 (wecom_sop 例外行): 仅 metric 监控, 无 SQL 对账
-- -----------------------------------------------------------------------------
-- 用途: 文档化 wecom_sop 单 job 不入 sync_logs 的 SQL 边界 (per #806 DOD
--       FU-8 + governance §5:143). 仅返回 0 行预期; 若返回非 0 行 → wecom
--       误写 sync_logs (回归 bug).
-- 输入: 单租户; 时间窗 7d
-- 输出: 期望 0 行 (sync_type LIKE 'wecom%' 任何 record 都是回归)
-- 用法: W4 Day-7 跑 1 次 verify 0 行; 否则查 wecom_sop.py 是否误调
--       `_write_sync_log`. wecom 真对账走 Prometheus:
--       `tx_sync_worker_executions_total{job="wecom_group_daily_sop"}` 7d sum.

SELECT
    DATE(started_at AT TIME ZONE 'Asia/Shanghai') AS day,
    sync_type,
    status,
    COUNT(*) AS row_count
FROM sync_logs
WHERE started_at >= NOW() - INTERVAL '7 days'
  AND tenant_id = current_setting('app.tenant_id', true)::uuid
  AND (sync_type LIKE 'wecom%' OR sync_type LIKE '%sop%')
GROUP BY 1, 2, 3
ORDER BY 1 DESC, 2, 3;


-- -----------------------------------------------------------------------------
-- Query 5 (告警阈值 check): delta_pct > 10% 持续 ≥ N 天的异常组合
-- -----------------------------------------------------------------------------
-- 用途: W4 Day-3/5/7 巡检直接列异常组合 (delta > 10% 且持续 ≥ 2 天
--       = 真问题非偶发 drift). Phase 2 cutover gate 前必须 0 行才放行.
-- 输入: 单租户; 时间窗 7d; 阈值默认 10.0% 可调
-- 输出: merchant_code, sync_type, anomaly_days (delta > 10% 的天数), max_delta_pct
-- 用法: W4 Day-7 跑 1 次, 0 行 = 通过 cutover gate; ≥ 1 行 = 阻塞 cutover
--       并 follow-up 调查 (cron drift / pinzhi 429 / network).

WITH daily_delta AS (
    SELECT
        DATE(started_at AT TIME ZONE 'Asia/Shanghai') AS day,
        merchant_code,
        sync_type,
        ABS(
            COUNT(*) FILTER (WHERE status = 'success')::float
            - COUNT(*) FILTER (WHERE status = 'dry_run')::float
        ) / NULLIF(COUNT(*) FILTER (WHERE status = 'dry_run'), 0) * 100 AS delta_pct
    FROM sync_logs
    WHERE started_at >= NOW() - INTERVAL '7 days'
      AND tenant_id = current_setting('app.tenant_id', true)::uuid
    GROUP BY 1, 2, 3
)
SELECT
    merchant_code,
    sync_type,
    COUNT(*) FILTER (WHERE delta_pct > 10.0) AS anomaly_days,
    ROUND(MAX(delta_pct)::numeric, 2) AS max_delta_pct
FROM daily_delta
WHERE delta_pct IS NOT NULL
GROUP BY merchant_code, sync_type
HAVING COUNT(*) FILTER (WHERE delta_pct > 10.0) >= 2  -- 持续 ≥ 2 天才告警
ORDER BY anomaly_days DESC, max_delta_pct DESC;


-- =============================================================================
-- 通过标准 (W4 cutover gate)
-- =============================================================================
-- 1. Query 1 全行 delta_pct ≤ 10% (NULL 行 = 0 dry_run, 视真路径正常即过)
-- 2. Query 3 全行 dry_run_rows = 0 (反向 sanity)
-- 3. Query 4 返回 0 行 (wecom 不入 sync_logs)
-- 4. Query 5 返回 0 行 (无 ≥ 2 天异常组合)
-- 满足 1+2+3+4 → 创始人 sign-off PR #806 Phase 2 PR-A (关 gateway scheduler).
--
-- 不通过 → 立 follow-up issue 调查; 不阻塞 dry_run 继续观察, 但 cutover
--          时间延后 (与 #821 rollback procedure 配套, gateway scheduler 继续跑).
-- =============================================================================
