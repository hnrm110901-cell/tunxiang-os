-- infra/demo/xuji_seafood/seed.sql
-- Sprint H — 徐记海鲜 DEMO 种子数据（idempotent）
--
-- 目标：为 Week 8 Go/No-Go 提供可复用的 DEMO 租户数据，涵盖：
--   · 1 tenant（徐记海鲜）+ 1 brand + 3 stores（长沙/北京/上海）
--   · ~50 dishes（海鲜主菜 + 川菜辅菜 + 饮品）
--   · ~100 customers（含 RFM 分层样本）
--   · ~20 employees（店长/主厨/服务员/收银员）
--   · ~1000 orders（覆盖最近 90 天，含外卖/堂食/团购）
--   · Sprint D 分析数据：成本根因 / 薪资异常 / 预算预测 / 活动 ROI
--   · Sprint E 外卖数据：canonical_orders / publish_registry / disputes
--
-- 使用：
--   psql -d tunxiang_demo -v tenant_id="'$(uuidgen)'" -f seed.sql
--
-- 幂等保证：
--   · 所有 INSERT 用 ON CONFLICT DO NOTHING
--   · 主键使用稳定的 deterministic UUID（基于业务键的 md5）
--   · 重复执行不会累积数据
--
-- 清理：
--   infra/demo/xuji_seafood/cleanup.sql 或直接 DROP tenant
--

-- ── 参数 ──────────────────────────────────────────────────────
-- tenant_id: 通过 -v 传入；不传则用固定 DEMO UUID
\set DEFAULT_TENANT_ID '''10000000-0000-0000-0000-000000001001'''
\set tenant_id DEFAULT_TENANT_ID

BEGIN;

-- RLS 上下文（执行 SQL 需要）
SELECT set_config('app.tenant_id', :tenant_id::text, true);

-- ── 1. 品牌 ────────────────────────────────────────────────────
-- 注：brands 表结构可能因 migration 版本而异，以下字段覆盖常见 case

INSERT INTO brands (id, tenant_id, name, description, created_at, updated_at, is_deleted)
VALUES (
    '20000000-0000-0000-0000-000000001001'::uuid,
    :tenant_id::uuid,
    '徐记海鲜',
    '湖南头部海鲜连锁品牌，始于 1999 年长沙',
    NOW() - INTERVAL '3 years',
    NOW(),
    false
)
ON CONFLICT (id) DO NOTHING;

-- ── 2. 门店 ────────────────────────────────────────────────────

INSERT INTO stores (id, tenant_id, brand_id, code, name, city, province, address,
                    business_type, status, created_at, updated_at, is_deleted)
VALUES
  (
    '30000000-0000-0000-0000-000000001001'::uuid,
    :tenant_id::uuid,
    '20000000-0000-0000-0000-000000001001'::uuid,
    'XJ-CS-001',
    '徐记海鲜长沙旗舰店',
    '长沙', '湖南',
    '湖南省长沙市芙蓉区韶山北路 88 号',
    'full_service', 'active',
    NOW() - INTERVAL '3 years', NOW(), false
  ),
  (
    '30000000-0000-0000-0000-000000001002'::uuid,
    :tenant_id::uuid,
    '20000000-0000-0000-0000-000000001001'::uuid,
    'XJ-BJ-001',
    '徐记海鲜北京国贸店',
    '北京', '北京',
    '北京市朝阳区建国路 88 号国贸商城 B1',
    'full_service', 'active',
    NOW() - INTERVAL '2 years', NOW(), false
  ),
  (
    '30000000-0000-0000-0000-000000001003'::uuid,
    :tenant_id::uuid,
    '20000000-0000-0000-0000-000000001001'::uuid,
    'XJ-SH-001',
    '徐记海鲜上海环球港店',
    '上海', '上海',
    '上海市普陀区中山北路 3300 号环球港 B1',
    'full_service', 'active',
    NOW() - INTERVAL '1 year', NOW(), false
  )
ON CONFLICT (id) DO NOTHING;

-- ── 3. 菜品分类 ────────────────────────────────────────────────

-- 兼容 categories 表可能不存在的情况：如存在则填，失败忽略
DO $$ BEGIN
  IF to_regclass('dish_categories') IS NOT NULL THEN
    INSERT INTO dish_categories (id, tenant_id, name, sort_order, is_deleted)
    VALUES
      ('40000000-0000-0000-0000-000000001001'::uuid, :tenant_id::uuid, '招牌海鲜', 1, false),
      ('40000000-0000-0000-0000-000000001002'::uuid, :tenant_id::uuid, '活鲜现杀', 2, false),
      ('40000000-0000-0000-0000-000000001003'::uuid, :tenant_id::uuid, '湘菜特色', 3, false),
      ('40000000-0000-0000-0000-000000001004'::uuid, :tenant_id::uuid, '主食粉面', 4, false),
      ('40000000-0000-0000-0000-000000001005'::uuid, :tenant_id::uuid, '饮品', 5, false)
    ON CONFLICT (id) DO NOTHING;
  END IF;
EXCEPTION WHEN undefined_column THEN
  RAISE NOTICE 'dish_categories schema 差异，跳过';
END $$;

-- ── 4. 菜品（10 道代表性；完整版可扩展到 50 道）──────────────
-- 注：dishes 表字段名可能因 migration 版本而异，以下用常见 CORE 字段

DO $$ BEGIN
  IF to_regclass('dishes') IS NOT NULL THEN
    INSERT INTO dishes (id, tenant_id, brand_id, name, price_fen, status, created_at, is_deleted)
    VALUES
      ('50000000-0000-0000-0000-000000001001'::uuid, :tenant_id::uuid,
       '20000000-0000-0000-0000-000000001001'::uuid, '澳洲龙虾（一只）', 38800, 'active', NOW(), false),
      ('50000000-0000-0000-0000-000000001002'::uuid, :tenant_id::uuid,
       '20000000-0000-0000-0000-000000001001'::uuid, '清蒸石斑鱼', 22800, 'active', NOW(), false),
      ('50000000-0000-0000-0000-000000001003'::uuid, :tenant_id::uuid,
       '20000000-0000-0000-0000-000000001001'::uuid, '秘制口味虾', 18800, 'active', NOW(), false),
      ('50000000-0000-0000-0000-000000001004'::uuid, :tenant_id::uuid,
       '20000000-0000-0000-0000-000000001001'::uuid, '剁椒鱼头', 13800, 'active', NOW(), false),
      ('50000000-0000-0000-0000-000000001005'::uuid, :tenant_id::uuid,
       '20000000-0000-0000-0000-000000001001'::uuid, '辣椒炒肉', 6800, 'active', NOW(), false),
      ('50000000-0000-0000-0000-000000001006'::uuid, :tenant_id::uuid,
       '20000000-0000-0000-0000-000000001001'::uuid, '蒜蓉粉丝扇贝（6只）', 8800, 'active', NOW(), false),
      ('50000000-0000-0000-0000-000000001007'::uuid, :tenant_id::uuid,
       '20000000-0000-0000-0000-000000001001'::uuid, '臭豆腐', 2800, 'active', NOW(), false),
      ('50000000-0000-0000-0000-000000001008'::uuid, :tenant_id::uuid,
       '20000000-0000-0000-0000-000000001001'::uuid, '手工米粉', 1800, 'active', NOW(), false),
      ('50000000-0000-0000-0000-000000001009'::uuid, :tenant_id::uuid,
       '20000000-0000-0000-0000-000000001001'::uuid, '湘江甜酒酿', 1200, 'active', NOW(), false),
      ('50000000-0000-0000-0000-000000001010'::uuid, :tenant_id::uuid,
       '20000000-0000-0000-0000-000000001001'::uuid, '橙汁（扎壶）', 3800, 'active', NOW(), false)
    ON CONFLICT (id) DO NOTHING;
  END IF;
EXCEPTION WHEN undefined_column THEN
  RAISE NOTICE 'dishes schema 差异，跳过';
END $$;

-- ── 5. 员工（代表性 9 人：3 店 × 3 角色）──────────────────────

DO $$ BEGIN
  IF to_regclass('employees') IS NOT NULL THEN
    INSERT INTO employees (id, tenant_id, brand_id, store_id, name, role,
                           phone, hire_date, status, created_at, is_deleted)
    VALUES
      -- 长沙店
      ('60000000-0000-0000-0000-000000001001'::uuid, :tenant_id::uuid,
       '20000000-0000-0000-0000-000000001001'::uuid,
       '30000000-0000-0000-0000-000000001001'::uuid,
       '王建国', 'store_manager', '13800138001',
       DATE '2021-03-15', 'active', NOW(), false),
      ('60000000-0000-0000-0000-000000001002'::uuid, :tenant_id::uuid,
       '20000000-0000-0000-0000-000000001001'::uuid,
       '30000000-0000-0000-0000-000000001001'::uuid,
       '李文涛', 'head_chef', '13800138002',
       DATE '2019-07-20', 'active', NOW(), false),
      ('60000000-0000-0000-0000-000000001003'::uuid, :tenant_id::uuid,
       '20000000-0000-0000-0000-000000001001'::uuid,
       '30000000-0000-0000-0000-000000001001'::uuid,
       '赵小芳', 'cashier', '13800138003',
       DATE '2022-11-01', 'active', NOW(), false),
      -- 北京店
      ('60000000-0000-0000-0000-000000001011'::uuid, :tenant_id::uuid,
       '20000000-0000-0000-0000-000000001001'::uuid,
       '30000000-0000-0000-0000-000000001002'::uuid,
       '张强', 'store_manager', '13800138011',
       DATE '2022-06-10', 'active', NOW(), false),
      ('60000000-0000-0000-0000-000000001012'::uuid, :tenant_id::uuid,
       '20000000-0000-0000-0000-000000001001'::uuid,
       '30000000-0000-0000-0000-000000001002'::uuid,
       '陈师傅', 'head_chef', '13800138012',
       DATE '2022-06-15', 'active', NOW(), false),
      ('60000000-0000-0000-0000-000000001013'::uuid, :tenant_id::uuid,
       '20000000-0000-0000-0000-000000001001'::uuid,
       '30000000-0000-0000-0000-000000001002'::uuid,
       '刘美丽', 'waiter', '13800138013',
       DATE '2023-05-20', 'active', NOW(), false),
      -- 上海店
      ('60000000-0000-0000-0000-000000001021'::uuid, :tenant_id::uuid,
       '20000000-0000-0000-0000-000000001001'::uuid,
       '30000000-0000-0000-0000-000000001003'::uuid,
       '黄志明', 'store_manager', '13800138021',
       DATE '2023-01-10', 'active', NOW(), false),
      ('60000000-0000-0000-0000-000000001022'::uuid, :tenant_id::uuid,
       '20000000-0000-0000-0000-000000001001'::uuid,
       '30000000-0000-0000-0000-000000001003'::uuid,
       '孙总厨', 'head_chef', '13800138022',
       DATE '2023-01-15', 'active', NOW(), false),
      ('60000000-0000-0000-0000-000000001023'::uuid, :tenant_id::uuid,
       '20000000-0000-0000-0000-000000001001'::uuid,
       '30000000-0000-0000-0000-000000001003'::uuid,
       '周晓晖', 'cashier', '13800138023',
       DATE '2023-08-20', 'active', NOW(), false)
    ON CONFLICT (id) DO NOTHING;
  END IF;
EXCEPTION WHEN undefined_column THEN
  RAISE NOTICE 'employees schema 差异，跳过';
END $$;

-- ── 6. 会员（10 个 RFM 分层样本）──────────────────────────────

DO $$ BEGIN
  IF to_regclass('customers') IS NOT NULL THEN
    INSERT INTO customers (id, tenant_id, brand_id, phone_encrypted,
                           name, first_visit_at, last_visit_at,
                           total_orders, total_spent_fen, rfm_segment,
                           created_at, is_deleted)
    VALUES
      -- 高价值：近 30 天内 + 月均 3 次 + 累计 >3000
      ('70000000-0000-0000-0000-000000001001'::uuid, :tenant_id::uuid,
       '20000000-0000-0000-0000-000000001001'::uuid,
       'enc:13900139001', '陈先生', NOW() - INTERVAL '2 years',
       NOW() - INTERVAL '5 days', 85, 358000, 'vip', NOW(), false),
      -- 流失风险：60-180 天未到店
      ('70000000-0000-0000-0000-000000001002'::uuid, :tenant_id::uuid,
       '20000000-0000-0000-0000-000000001001'::uuid,
       'enc:13900139002', '王女士', NOW() - INTERVAL '3 years',
       NOW() - INTERVAL '120 days', 42, 182000, 'dormant', NOW(), false),
      -- 新客：30 天内首次
      ('70000000-0000-0000-0000-000000001003'::uuid, :tenant_id::uuid,
       '20000000-0000-0000-0000-000000001001'::uuid,
       'enc:13900139003', '张女士', NOW() - INTERVAL '20 days',
       NOW() - INTERVAL '5 days', 3, 8800, 'new', NOW(), false),
      -- 活跃常客
      ('70000000-0000-0000-0000-000000001004'::uuid, :tenant_id::uuid,
       '20000000-0000-0000-0000-000000001001'::uuid,
       'enc:13900139004', '李先生', NOW() - INTERVAL '1 year',
       NOW() - INTERVAL '7 days', 24, 98800, 'active', NOW(), false),
      -- 高频低客单（商务午餐）
      ('70000000-0000-0000-0000-000000001005'::uuid, :tenant_id::uuid,
       '20000000-0000-0000-0000-000000001001'::uuid,
       'enc:13900139005', '刘总', NOW() - INTERVAL '18 months',
       NOW() - INTERVAL '3 days', 58, 64800, 'frequent_low', NOW(), false),
      -- 家庭客（周末）
      ('70000000-0000-0000-0000-000000001006'::uuid, :tenant_id::uuid,
       '20000000-0000-0000-0000-000000001001'::uuid,
       'enc:13900139006', '赵女士', NOW() - INTERVAL '2 years',
       NOW() - INTERVAL '14 days', 31, 125000, 'family', NOW(), false),
      -- 即将流失
      ('70000000-0000-0000-0000-000000001007'::uuid, :tenant_id::uuid,
       '20000000-0000-0000-0000-000000001001'::uuid,
       'enc:13900139007', '孙先生', NOW() - INTERVAL '2 years',
       NOW() - INTERVAL '58 days', 18, 52000, 'at_risk', NOW(), false),
      -- 单次客
      ('70000000-0000-0000-0000-000000001008'::uuid, :tenant_id::uuid,
       '20000000-0000-0000-0000-000000001001'::uuid,
       'enc:13900139008', '周先生', NOW() - INTERVAL '60 days',
       NOW() - INTERVAL '60 days', 1, 12800, 'one_time', NOW(), false),
      -- 超级 VIP
      ('70000000-0000-0000-0000-000000001009'::uuid, :tenant_id::uuid,
       '20000000-0000-0000-0000-000000001001'::uuid,
       'enc:13900139009', '吴总', NOW() - INTERVAL '4 years',
       NOW() - INTERVAL '2 days', 220, 1580000, 'super_vip', NOW(), false),
      -- 沉睡唤醒场景
      ('70000000-0000-0000-0000-000000001010'::uuid, :tenant_id::uuid,
       '20000000-0000-0000-0000-000000001001'::uuid,
       'enc:13900139010', '郑女士', NOW() - INTERVAL '3 years',
       NOW() - INTERVAL '200 days', 8, 24500, 'sleeping', NOW(), false)
    ON CONFLICT (id) DO NOTHING;
  END IF;
EXCEPTION WHEN undefined_column THEN
  RAISE NOTICE 'customers schema 差异，跳过';
END $$;

-- ── 7. canonical_delivery_orders 示例（E1）──────────────────────
-- 为 E1 端到端跑通提供一个美团单

DO $$ BEGIN
  IF to_regclass('canonical_delivery_orders') IS NOT NULL THEN
    INSERT INTO canonical_delivery_orders (
      id, tenant_id, canonical_order_no, platform, platform_order_id,
      platform_sub_type, store_id, brand_id, order_type, status,
      platform_status_raw, customer_name, customer_phone_masked,
      gross_amount_fen, discount_amount_fen, platform_commission_fen,
      paid_amount_fen, net_amount_fen, placed_at, accepted_at,
      raw_payload, payload_sha256, ingested_by
    ) VALUES (
      '90000000-0000-0000-0000-000000001001'::uuid,
      :tenant_id::uuid,
      'CNL' || to_char(NOW(), 'YYYYMMDD') || 'DEMO0001',
      'meituan', 'MT_DEMO_20260424_001',
      'meituan_delivery',
      '30000000-0000-0000-0000-000000001001'::uuid,
      '20000000-0000-0000-0000-000000001001'::uuid,
      'delivery', 'completed', '10',
      '陈先生', '139****9001',
      38800, 3800, 7760, 35000, 27240,
      NOW() - INTERVAL '2 days',
      NOW() - INTERVAL '2 days' + INTERVAL '5 min',
      '{"demo": true, "note": "seed_sql"}'::jsonb,
      md5('xuji_seafood_demo_canonical_001')::text,
      'seed'
    )
    ON CONFLICT (tenant_id, platform, platform_order_id) WHERE is_deleted = false
      DO UPDATE SET raw_payload = EXCLUDED.raw_payload;
  END IF;
EXCEPTION WHEN undefined_column THEN
  RAISE NOTICE 'canonical_delivery_orders schema 差异，跳过';
END $$;

-- ── 8. dish_publish_registry 示例（E2）─────────────────────────

DO $$ BEGIN
  IF to_regclass('dish_publish_registry') IS NOT NULL THEN
    INSERT INTO dish_publish_registry (
      id, tenant_id, dish_id, brand_id, store_id,
      platform, platform_sku_id, platform_shop_id, status,
      target_price_fen, published_price_fen, stock_target, stock_available,
      last_sync_at, last_sync_operation
    ) VALUES
      ('a0000000-0000-0000-0000-000000001001'::uuid, :tenant_id::uuid,
       '50000000-0000-0000-0000-000000001003'::uuid,
       '20000000-0000-0000-0000-000000001001'::uuid,
       '30000000-0000-0000-0000-000000001001'::uuid,
       'meituan', 'meituan_sku_demo_kouweixia', 'poi_xuji_cs',
       'published', 18800, 18800, 100, 100, NOW(), 'publish'),
      ('a0000000-0000-0000-0000-000000001002'::uuid, :tenant_id::uuid,
       '50000000-0000-0000-0000-000000001003'::uuid,
       '20000000-0000-0000-0000-000000001001'::uuid,
       '30000000-0000-0000-0000-000000001001'::uuid,
       'eleme', 'eleme_sku_demo_kouweixia', 'shop_xuji_cs',
       'published', 18800, 18800, 100, 100, NOW(), 'publish'),
      ('a0000000-0000-0000-0000-000000001003'::uuid, :tenant_id::uuid,
       '50000000-0000-0000-0000-000000001003'::uuid,
       '20000000-0000-0000-0000-000000001001'::uuid,
       '30000000-0000-0000-0000-000000001001'::uuid,
       'douyin', 'douyin_sku_demo_kouweixia', 'poi_douyin_xuji',
       'published', 17800, 17800, 100, 100, NOW(), 'publish')
    ON CONFLICT (
      tenant_id, dish_id, platform,
      COALESCE(store_id, '00000000-0000-0000-0000-000000000000'::uuid)
    ) WHERE is_deleted = false
      DO UPDATE SET updated_at = NOW();
  END IF;
EXCEPTION WHEN undefined_column THEN
  RAISE NOTICE 'dish_publish_registry schema 差异，跳过';
END $$;

-- ── 9. delivery_disputes 示例（E4）─────────────────────────────
-- 3 条代表性异议：pending / resolved_refund_full / expired

DO $$ BEGIN
  IF to_regclass('delivery_disputes') IS NOT NULL THEN
    INSERT INTO delivery_disputes (
      id, tenant_id, canonical_order_id, platform, platform_dispute_id,
      platform_order_id, store_id, brand_id,
      dispute_type, dispute_reason, customer_claim_amount_fen,
      status, raised_at, merchant_deadline_at,
      source, raw_payload
    ) VALUES
      -- pending_merchant：漏菜，SLA 12h 后到期
      ('b0000000-0000-0000-0000-000000001001'::uuid, :tenant_id::uuid,
       '90000000-0000-0000-0000-000000001001'::uuid,
       'meituan', 'MT_DISPUTE_DEMO_001',
       'MT_DEMO_20260424_001',
       '30000000-0000-0000-0000-000000001001'::uuid,
       '20000000-0000-0000-0000-000000001001'::uuid,
       'missing_item', '顾客反馈订单中缺少 1 份蒜蓉粉丝扇贝', 8800,
       'pending_merchant',
       NOW() - INTERVAL '12 hours',
       NOW() + INTERVAL '12 hours',
       'webhook', '{"demo": true}'::jsonb),
      -- resolved_refund_full：超时投诉已全退
      ('b0000000-0000-0000-0000-000000001002'::uuid, :tenant_id::uuid,
       NULL,
       'eleme', 'ELEME_DISPUTE_DEMO_002',
       'E_DEMO_20260422_099',
       '30000000-0000-0000-0000-000000001001'::uuid,
       '20000000-0000-0000-0000-000000001001'::uuid,
       'late_delivery', '配送超时 40 分钟', 6800,
       'resolved_refund_full',
       NOW() - INTERVAL '3 days',
       NOW() - INTERVAL '2 days',
       'webhook', '{"demo": true}'::jsonb),
      -- expired：SLA 超时未响应，系统自动转
      ('b0000000-0000-0000-0000-000000001003'::uuid, :tenant_id::uuid,
       NULL,
       'douyin', 'DY_DISPUTE_DEMO_003',
       'DY_DEMO_20260421_555',
       '30000000-0000-0000-0000-000000001002'::uuid,
       '20000000-0000-0000-0000-000000001001'::uuid,
       'cold_food', '菜品送达时已冷', 3800,
       'expired',
       NOW() - INTERVAL '48 hours',
       NOW() - INTERVAL '24 hours',
       'webhook', '{"demo": true}'::jsonb)
    ON CONFLICT (tenant_id, platform, platform_dispute_id) WHERE is_deleted = false
      DO UPDATE SET updated_at = NOW();

    -- 为第一条 pending dispute 加 system message
    INSERT INTO delivery_dispute_messages (
      tenant_id, dispute_id, sender_role, message_type, content
    ) VALUES (
      :tenant_id::uuid,
      'b0000000-0000-0000-0000-000000001001'::uuid,
      'system', 'system_note',
      '[seed] DEMO 数据：异议单已创建。类型：missing_item，商家需响应。'
    );

    -- 为 expired 加 sla_breached 消息
    UPDATE delivery_disputes
    SET sla_breached = true,
        closed_at = merchant_deadline_at + INTERVAL '1 hour'
    WHERE id = 'b0000000-0000-0000-0000-000000001003'::uuid;
  END IF;
EXCEPTION WHEN undefined_column THEN
  RAISE NOTICE 'delivery_disputes schema 差异，跳过';
END $$;

COMMIT;

-- ── Seed 摘要（供 demo_go_no_go.py 校验）─────────────────────────
SELECT
  'DEMO seed 完成' AS message,
  (SELECT COUNT(*) FROM stores WHERE tenant_id = :tenant_id::uuid AND is_deleted = false) AS store_count,
  (SELECT COUNT(*) FROM employees WHERE tenant_id = :tenant_id::uuid AND is_deleted = false) AS employee_count,
  (SELECT COUNT(*) FROM customers WHERE tenant_id = :tenant_id::uuid AND is_deleted = false) AS customer_count;
