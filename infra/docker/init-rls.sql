-- RLS 基础配置
-- 所有表启用 RLS 后，通过 SET app.tenant_id = '<uuid>' 设置当前租户

-- 创建设置租户 ID 的函数
CREATE OR REPLACE FUNCTION set_tenant_id(tid UUID) RETURNS VOID AS $$
BEGIN
  PERFORM set_config('app.tenant_id', tid::TEXT, FALSE);
END;
$$ LANGUAGE plpgsql;

-- RLS Policy 模板（在每个表创建后调用）
-- ALTER TABLE <table_name> ENABLE ROW LEVEL SECURITY;
-- CREATE POLICY tenant_isolation ON <table_name>
--   USING (tenant_id = current_setting('app.tenant_id')::UUID);
-- CREATE POLICY tenant_insert ON <table_name>
--   FOR INSERT WITH CHECK (tenant_id = current_setting('app.tenant_id')::UUID);
