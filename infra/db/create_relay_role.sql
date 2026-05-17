-- tx-event-relay 专用 DB 角色 (W3 issue #757)
-- 用途: relay worker polling 跨租户 outbox 需绕 RLS (per outbox_repo.py:68 注释).
-- 部署: DBA 执行此 SQL 创建角色 + 设置密码; values.yaml secretRef.DATABASE_URL 必须指向此角色.
--
-- 与 infra/db/create_db_roles.sql 三权分立的关系:
--   tx_event_relay 是第 4 个 DB 角色, 专为 relay worker 跨租户 polling 设计.
--   不复用 txos_service (受 RLS 约束, 只能看单租户), 因为 relay 需要扫所有租户 outbox.
--   不复用 txos_dba (DDL 权限过大, 违反最小权限).
--   shadow 期间仅 SELECT 用于 polling + UPDATE last_attempt_at 用于监控;
--   W11 真投递路径 (#767 follow-up) 切真路径时再 GRANT INSERT events 写入权限.

-- ──────────────────────────────────────────────────────────────────
-- tx_event_relay — 真 Outbox relay 专用角色 (BYPASSRLS)
-- ──────────────────────────────────────────────────────────────────
CREATE ROLE tx_event_relay LOGIN PASSWORD 'CHANGE_ME_BEFORE_DEPLOY';
ALTER ROLE tx_event_relay BYPASSRLS;

-- shadow 期间权限 (本 PR scope):
--   SELECT — fetch_pending_batch / count_pending
--   UPDATE — bump_last_attempt_at (P1-4 监控用)
GRANT SELECT, UPDATE ON trade_event_outbox TO tx_event_relay;

-- W11 真投递路径 (#767 follow-up) 切真路径时追加:
--   GRANT INSERT ON events TO tx_event_relay;
--   GRANT SELECT ON projector_checkpoints TO tx_event_relay;
--
-- 密码要求:
--   1. 替换 CHANGE_ME_BEFORE_DEPLOY 为高强度随机密码
--   2. 通过 K8s Secret 注入 DATABASE_URL (tx-event-relay-secret)
--   3. 不得出现在任何代码仓库中
--   4. shadow 期间表预期 0 行, 操作量极低, 但密钥仍需独立保管
