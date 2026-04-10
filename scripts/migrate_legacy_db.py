"""旧 DB → 新 RLS DB 数据迁移脚本

从 tunxiang V2.x 的 PostgreSQL 迁移到 tunxiang-os V3.0 的 RLS-enabled DB。

核心变更：
1. 所有表增加 tenant_id 列
2. store_id 从 String(50) 转为 UUID
3. 金额字段统一为分（fen）
4. 启用 RLS Policy

使用方式：
  python scripts/migrate_legacy_db.py --source=旧库URL --target=新库URL --tenant-id=xxx
"""
import argparse
import asyncio
import uuid
from datetime import datetime

import asyncpg
import structlog

logger = structlog.get_logger()


async def migrate(source_url: str, target_url: str, tenant_id: str):
    """执行迁移"""
    src = await asyncpg.connect(source_url)
    tgt = await asyncpg.connect(target_url)
    tid = uuid.UUID(tenant_id)

    logger.info("migration_started", source=source_url.split("@")[-1], tenant_id=tenant_id)

    # 设置目标库的 tenant context
    await tgt.execute("SELECT set_tenant_id($1)", tid)

    # ─── 1. 迁移门店 ───
    stores = await src.fetch("SELECT * FROM stores WHERE is_active = true")
    for s in stores:
        store_uuid = uuid.uuid5(uuid.NAMESPACE_URL, f"store:{s['id']}")
        await tgt.execute("""
            INSERT INTO stores (id, tenant_id, store_name, store_code, address, city, phone, brand_id, status,
                                area, seats, floors, monthly_revenue_target_fen, cost_ratio_target)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
            ON CONFLICT (store_code) DO NOTHING
        """, store_uuid, tid, s['name'], s['code'], s.get('address'), s.get('city'),
           s.get('phone'), s.get('brand_id'), s.get('status', 'active'),
           s.get('area'), s.get('seats'), s.get('floors', 1),
           int((s.get('monthly_revenue_target') or 0) * 100),  # 元→分
           s.get('cost_ratio_target'))

    logger.info("stores_migrated", count=len(stores))

    # ─── 2. 迁移员工 ───
    employees = await src.fetch("SELECT * FROM employees WHERE is_active = true")
    for e in employees:
        emp_uuid = uuid.uuid5(uuid.NAMESPACE_URL, f"emp:{e['id']}")
        store_uuid = uuid.uuid5(uuid.NAMESPACE_URL, f"store:{e['store_id']}")
        await tgt.execute("""
            INSERT INTO employees (id, tenant_id, store_id, emp_name, phone, role, employment_status, is_active,
                                   wechat_userid, gender, hire_date)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            ON CONFLICT DO NOTHING
        """, emp_uuid, tid, store_uuid, e['name'], e.get('phone'), e.get('position', 'waiter'),
           e.get('employment_status', 'regular'), True,
           e.get('wechat_userid'), e.get('gender'), e.get('hire_date'))

    logger.info("employees_migrated", count=len(employees))

    # ─── 3. 迁移菜品 ───
    dishes = await src.fetch("SELECT * FROM dishes WHERE is_deleted = false")
    for d in dishes:
        dish_uuid = uuid.uuid5(uuid.NAMESPACE_URL, f"dish:{d['id']}")
        price_fen = int((d.get('price') or 0) * 100)  # 元→分
        cost_fen = int((d.get('cost') or 0) * 100)
        await tgt.execute("""
            INSERT INTO dishes (id, tenant_id, dish_name, dish_code, price_fen, cost_fen, unit,
                                is_available, kitchen_station, preparation_time, total_sales)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            ON CONFLICT (dish_code) DO NOTHING
        """, dish_uuid, tid, d['name'], d['code'], price_fen, cost_fen,
           d.get('unit', '份'), d.get('is_available', True),
           d.get('kitchen_station'), d.get('preparation_time'), d.get('total_sales', 0))

    logger.info("dishes_migrated", count=len(dishes))

    # ─── 4. 迁移顾客 ───
    consumers = await src.fetch("""
        SELECT * FROM consumer_identities WHERE is_merged = false
        LIMIT 10000
    """)
    for c in consumers:
        await tgt.execute("""
            INSERT INTO customers (id, tenant_id, primary_phone, display_name, gender, birth_date,
                                   wechat_openid, wechat_unionid, total_order_count, total_order_amount_fen,
                                   rfm_recency_days, rfm_frequency, rfm_monetary_fen, source)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
            ON CONFLICT (primary_phone) DO NOTHING
        """, c['id'], tid, c['primary_phone'], c.get('display_name'), c.get('gender'),
           c.get('birth_date'), c.get('wechat_openid'), c.get('wechat_unionid'),
           c.get('total_order_count', 0), c.get('total_order_amount_fen', 0),
           c.get('rfm_recency_days'), c.get('rfm_frequency'), c.get('rfm_monetary_fen'),
           c.get('source'))

    logger.info("customers_migrated", count=len(consumers))

    # ─── 完成 ───
    await src.close()
    await tgt.close()
    logger.info("migration_completed",
                stores=len(stores), employees=len(employees),
                dishes=len(dishes), customers=len(consumers))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate legacy tunxiang DB to tunxiang-os RLS DB")
    parser.add_argument("--source", required=True, help="Source DB URL (tunxiang V2.x)")
    parser.add_argument("--target", required=True, help="Target DB URL (tunxiang-os V3.0)")
    parser.add_argument("--tenant-id", required=True, help="Tenant UUID for RLS")
    args = parser.parse_args()

    asyncio.run(migrate(args.source, args.target, args.tenant_id))
