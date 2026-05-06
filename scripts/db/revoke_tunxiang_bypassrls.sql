-- ============================================================
-- 撤销主 app role (tunxiang) 的 BYPASSRLS
-- ============================================================
-- 审计 S-05 阶段 5（cutover 收尾）：在 RLS_USE_TX_SYSTEM_ROLE=true 全量灰度
-- 24h 通过后，撤销 tunxiang 的 BYPASSRLS。撤销后：
--
--   - app 代码若不走 get_db_no_rls() 不再有任何方式绕 RLS
--   - 所有 SET LOCAL row_security = off 调用都会因角色无 BYPASSRLS 而无效
--   - 真正实现"BYPASSRLS 仅在 SET LOCAL ROLE tx_system_role 期间生效"
--
-- 前置条件（必须全部满足才能跑本脚本）：
--   1. scripts/db/create_tx_system_role.sql 已跑（tx_system_role 存在）
--   2. 应用代码已部署 RLS_USE_TX_SYSTEM_ROLE=true
--   3. 灰度门店 24h 无 RLS-related 5xx
--   4. 5 处合法调用方均已验证可走 SET LOCAL ROLE 路径
--   5. v500_rls_force_all_business_tables migration 已 dry-run 通过（PR #199）
--
-- 不通过 alembic 跑（DBA 操作）。
--
-- 不可逆性提醒：
--   撤销后若发现兼容问题，需 ALTER ROLE tunxiang BYPASSRLS 回滚；
--   回滚后所有 SET LOCAL row_security = off legacy 路径恢复有效，
--   但安全模型回到 cutover 前状态（S-05 风险重现）。
-- ============================================================

BEGIN;

-- 撤销主 app role 的 BYPASSRLS
ALTER ROLE tunxiang NOBYPASSRLS;

-- 验证：SELECT rolname, rolbypassrls FROM pg_roles WHERE rolname = 'tunxiang';
-- 期望：tunxiang | f

COMMIT;

-- 跑完后必须验证：
-- 1. 主 app role 直查含 RLS 的表（无 SET ROLE）→ 必须返回 0 行（FORCE + 无 BYPASSRLS）
--    SET LOCAL row_security = off;  -- 应静默失败（无权限），后续查询仍受 RLS 约束
--    SELECT count(*) FROM banquet_deposits;  -- 期望: 0（RLS 阻止）
--
-- 2. get_db_no_rls() 在 RLS_USE_TX_SYSTEM_ROLE=true 模式下仍可跨租户查
--    (用 5 处合法调用方端到端测试)
--
-- 3. 如果 FORCE migration v500 已上线，cross-tenant SELECT 即便有 BYPASSRLS
--    也被拒绝 — 这才是真正的多租户隔离
