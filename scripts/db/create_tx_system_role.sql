-- ============================================================
-- tx_system_role — 专用 BYPASSRLS 系统角色
-- ============================================================
-- 审计 S-05 阶段 4：把 BYPASSRLS 权限从主 app role (tunxiang) 转移到
-- 一个独立、NOLOGIN 的专用角色。app 代码通过 SET LOCAL ROLE 临时切换，
-- scope 严格限制在 get_db_no_rls() 上下文内。
--
-- 不通过 alembic 跑（DBA 操作，需要 PG superuser 权限）。
--
-- 部署顺序（详见 docs/security/rls-force-rollout.md 阶段 4-5）：
--   1. 部署应用代码（含本 PR 的 get_db_no_rls 双模式 + RLS_USE_TX_SYSTEM_ROLE env）
--   2. ⏳ 跑本脚本（CREATE ROLE + GRANT BYPASSRLS + GRANT tx_system_role TO tunxiang）
--   3. 在测试 pod 设 RLS_USE_TX_SYSTEM_ROLE=true，验证 5 处合法调用方仍可工作
--   4. 全量 pod 切 RLS_USE_TX_SYSTEM_ROLE=true
--   5. 24h 观察后跑 scripts/db/revoke_tunxiang_bypassrls.sql 真撤主角色 BYPASSRLS
--
-- 5 处合法调用方（grep "get_db_no_rls" services/）：
--   - gateway/src/.../hub_api.py
--   - services/tx-trade/src/api/banquet_payment_routes.py
--   - services/tx-trade/src/services/wechat_pay_notify_service.py
--   - services/tx-analytics/src/etl/seed_loader.py
--   - services/tx-brain/src/api/brain_routes.py
-- ============================================================

BEGIN;

-- 幂等：先检查角色是否已存在
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tx_system_role') THEN
    -- NOINHERIT：不继承被授予的角色权限，必须显式 SET ROLE
    -- NOLOGIN：不能直接登录（防止有人用此角色作为登录帐号）
    CREATE ROLE tx_system_role NOINHERIT NOLOGIN;
    RAISE NOTICE 'Created role tx_system_role';
  ELSE
    RAISE NOTICE 'Role tx_system_role already exists';
  END IF;
END
$$;

-- 给 tx_system_role 赋 BYPASSRLS（让 SET ROLE 后能绕 RLS）
ALTER ROLE tx_system_role BYPASSRLS;

-- 让主 app role tunxiang 可以 SET ROLE 到 tx_system_role
-- 注意：GRANT role 不会让 tunxiang 自动获得 BYPASSRLS（因为 NOINHERIT），
-- 必须显式 SET LOCAL ROLE tx_system_role 才生效
GRANT tx_system_role TO tunxiang;

-- 给 tx_system_role 必要的表/schema 权限（继承自 PUBLIC + 同 tunxiang）
-- 业务表的 SELECT/INSERT/UPDATE/DELETE 需保证 tx_system_role 也能用
GRANT USAGE ON SCHEMA public TO tx_system_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO tx_system_role;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO tx_system_role;

-- 让未来新表自动给 tx_system_role 这些权限
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO tx_system_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO tx_system_role;

COMMIT;

-- 验证：
-- SELECT rolname, rolbypassrls, rolcanlogin FROM pg_roles
--   WHERE rolname IN ('tunxiang', 'tx_system_role') ORDER BY rolname;
-- 期望：
--   tunxiang        | t (cutover 前) → f (cutover 后) | t
--   tx_system_role  | t                                | f

-- 测试 SET ROLE：
-- SET LOCAL ROLE tx_system_role;
-- SELECT current_user, current_setting('row_security');  -- 应该是 tx_system_role + on
-- RESET ROLE;
