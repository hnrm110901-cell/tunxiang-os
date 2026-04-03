-- RLS 基础配置
-- 所有表启用 RLS 后，通过 SELECT set_config('app.tenant_id', '<uuid>', true) 设置当前租户
-- 安全要求：所有 Policy 必须包含 NULL/空值防护，防止未设 tenant 时全表可见

-- 创建设置租户 ID 的函数
CREATE OR REPLACE FUNCTION set_tenant_id(tid UUID) RETURNS VOID AS $$
BEGIN
  IF tid IS NULL THEN
    RAISE EXCEPTION 'tenant_id must not be NULL';
  END IF;
  PERFORM set_config('app.tenant_id', tid::TEXT, FALSE);
END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- RLS Policy 安全模板（v006+ 标准，新表必须使用此模板）
-- ============================================================
-- 安全条件（禁止 NULL 绕过）：
--   current_setting('app.tenant_id', TRUE) IS NOT NULL
--   AND current_setting('app.tenant_id', TRUE) <> ''
--   AND tenant_id = current_setting('app.tenant_id')::UUID
--
-- 每张表必须创建 4 个 Policy（SELECT/INSERT/UPDATE/DELETE）：
--
-- ALTER TABLE <table_name> ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE <table_name> FORCE ROW LEVEL SECURITY;
--
-- CREATE POLICY <table>_rls_select ON <table>
--   FOR SELECT USING (
--     current_setting('app.tenant_id', TRUE) IS NOT NULL
--     AND current_setting('app.tenant_id', TRUE) <> ''
--     AND tenant_id = current_setting('app.tenant_id')::UUID
--   );
-- CREATE POLICY <table>_rls_insert ON <table>
--   FOR INSERT WITH CHECK (
--     current_setting('app.tenant_id', TRUE) IS NOT NULL
--     AND current_setting('app.tenant_id', TRUE) <> ''
--     AND tenant_id = current_setting('app.tenant_id')::UUID
--   );
-- CREATE POLICY <table>_rls_update ON <table>
--   FOR UPDATE USING (...same...) WITH CHECK (...same...);
-- CREATE POLICY <table>_rls_delete ON <table>
--   FOR DELETE USING (...same...);
