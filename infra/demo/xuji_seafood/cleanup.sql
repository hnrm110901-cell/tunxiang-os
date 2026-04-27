-- infra/demo/xuji_seafood/cleanup.sql
-- Sprint H — 徐记海鲜 DEMO 数据清理
--
-- 使用：
--   psql -d tunxiang_demo -v tenant_id="'10000000-0000-0000-0000-000000001001'" -f cleanup.sql
--
-- 注：清理只软删 (is_deleted=true)；硬删需要 DROP tenant 或手动 DELETE

\set DEFAULT_TENANT_ID '''10000000-0000-0000-0000-000000001001'''
\set tenant_id DEFAULT_TENANT_ID

BEGIN;
SELECT set_config('app.tenant_id', :tenant_id::text, true);

-- 软删所有 demo 数据
UPDATE customers SET is_deleted = true WHERE tenant_id = :tenant_id::uuid;
UPDATE employees SET is_deleted = true WHERE tenant_id = :tenant_id::uuid;
UPDATE stores SET is_deleted = true WHERE tenant_id = :tenant_id::uuid;
UPDATE brands SET is_deleted = true WHERE tenant_id = :tenant_id::uuid;

DO $$ BEGIN
  IF to_regclass('dishes') IS NOT NULL THEN
    EXECUTE 'UPDATE dishes SET is_deleted = true WHERE tenant_id = $1'
      USING :tenant_id::uuid;
  END IF;
  IF to_regclass('canonical_delivery_orders') IS NOT NULL THEN
    EXECUTE 'UPDATE canonical_delivery_orders SET is_deleted = true WHERE tenant_id = $1'
      USING :tenant_id::uuid;
  END IF;
  IF to_regclass('dish_publish_registry') IS NOT NULL THEN
    EXECUTE 'UPDATE dish_publish_registry SET is_deleted = true WHERE tenant_id = $1'
      USING :tenant_id::uuid;
  END IF;
  IF to_regclass('delivery_disputes') IS NOT NULL THEN
    EXECUTE 'UPDATE delivery_disputes SET is_deleted = true WHERE tenant_id = $1'
      USING :tenant_id::uuid;
  END IF;
END $$;

COMMIT;

SELECT 'DEMO 数据已软删（tenant ' || :tenant_id || '）' AS message;
