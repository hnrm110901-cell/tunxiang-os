#!/usr/bin/env python3
"""
尝在一起 (czyz) 演示种子数据
策略：翻台率优先，快餐/中式正餐
Run: python3 scripts/seed_czyz.py
"""
import os
import uuid
import random
from datetime import datetime, timedelta, timezone

import psycopg2
import psycopg2.extras

DB_URL = os.environ.get("DATABASE_URL")
if not DB_URL:
    raise RuntimeError("DATABASE_URL 环境变量未设置。示例：export DATABASE_URL=postgresql://user:pass@host:5432/dbname")

NAMESPACE = uuid.UUID("00000000-0000-0000-0000-000000000000")
MERCHANT_CODE = "czyz"
TENANT_ID_STR = "czyz-demo-tenant"

# 确定性租户 UUID（用于 DB 字段）
TENANT_UUID = str(uuid.uuid5(NAMESPACE, TENANT_ID_STR))
STORE_UUID  = str(uuid.uuid5(NAMESPACE, f"{MERCHANT_CODE}-store-001"))


def sid(name: str) -> str:
    return str(uuid.uuid5(NAMESPACE, name))


def run():
    try:
        conn = psycopg2.connect(DB_URL)
    except psycopg2.OperationalError as exc:
        print(f"❌ 数据库连接失败: {exc}")
        print(f"   DB_URL: {DB_URL}")
        return

    conn.autocommit = False
    cur = conn.cursor()
    cur.execute(f"SET app.tenant_id = '{TENANT_UUID}'")

    record_count = 0

    try:
        # ── 1. 租户 ──────────────────────────────────────────────────────────
        print("1. 创建租户...")
        cur.execute("""
            INSERT INTO platform_tenants (tenant_id, merchant_code, name, plan_template, status, subscription_expires_at)
            VALUES (%s, %s, '尝在一起', 'standard', 'active', '2027-12-31')
            ON CONFLICT (tenant_id) DO UPDATE SET name=EXCLUDED.name, status='active'
        """, (TENANT_UUID, MERCHANT_CODE))
        record_count += 1

        # ── 2. 门店 ──────────────────────────────────────────────────────────
        print("2. 创建门店...")
        cur.execute("""
            INSERT INTO stores (id, tenant_id, store_name, store_code, store_type, store_category,
                               address, seats, monthly_rent_fen)
            VALUES (%s,%s,'尝在一起·长沙五一店','czyz-001','dine_in','chinese',
                   '湖南省长沙市天心区五一广场',80,6000000)
            ON CONFLICT (id) DO UPDATE SET
                store_name=EXCLUDED.store_name,
                monthly_rent_fen=EXCLUDED.monthly_rent_fen
        """, (STORE_UUID, TENANT_UUID))
        record_count += 1

        # ── 3. 桌台 ──────────────────────────────────────────────────────────
        print("3. 创建桌台 (12张)...")
        tables_data = [
            ("A01", "大厅A区", 4), ("A02", "大厅A区", 4), ("A03", "大厅A区", 4),
            ("A04", "大厅A区", 4), ("A05", "大厅A区", 4), ("A06", "大厅A区", 4),
            ("B01", "大厅B区", 6), ("B02", "大厅B区", 6), ("B03", "大厅B区", 6),
            ("B04", "大厅B区", 6),
            ("VIP01", "VIP包间", 10), ("VIP02", "VIP包间", 10),
        ]
        for table_no, area, seats in tables_data:
            cur.execute("""
                INSERT INTO tables (id, tenant_id, store_id, table_no, area, seats, status)
                VALUES (%s,%s,%s,%s,%s,%s,'free')
                ON CONFLICT (id) DO UPDATE SET area=EXCLUDED.area, seats=EXCLUDED.seats
            """, (sid(f"czyz-table-{table_no}"), TENANT_UUID, STORE_UUID, table_no, area, seats))
        record_count += len(tables_data)

        # ── 4. 菜品 ──────────────────────────────────────────────────────────
        print("4. 创建菜品 (15道)...")
        dishes_data = [
            ("招牌红烧肉",   "湘菜", 3800),
            ("剁椒鱼头",     "湘菜", 5800),
            ("农家小炒肉",   "湘菜", 2800),
            ("清炒时蔬",     "素菜", 1500),
            ("白米饭",       "主食",  300),
            ("例汤",         "汤品",  800),
            ("酸菜鱼",       "湘菜", 4800),
            ("外婆菜炒鸡蛋", "湘菜", 2200),
            ("腊味合蒸",     "湘菜", 3200),
            ("辣椒炒肉",     "湘菜", 2800),
            ("红烧豆腐",     "素菜", 1800),
            ("毛氏红烧肉",   "湘菜", 4200),
            ("荷叶粉蒸肉",   "湘菜", 3500),
            ("东安鸡",       "湘菜", 4500),
            ("糖醋里脊",     "湘菜", 3200),
        ]
        for i, (name, category, price_fen) in enumerate(dishes_data):
            did = sid(f"czyz-dish-{name}")
            cur.execute("""
                INSERT INTO dishes (id, tenant_id, store_id, dish_name, dish_code,
                                   price_fen, original_price_fen, is_available)
                VALUES (%s,%s,%s,%s,%s,%s,%s,TRUE)
                ON CONFLICT (id) DO UPDATE SET
                    dish_name=EXCLUDED.dish_name,
                    price_fen=EXCLUDED.price_fen
            """, (did, TENANT_UUID, STORE_UUID, name, f"CZYZ{i+1:03d}", price_fen, price_fen))
        record_count += len(dishes_data)

        # ── 5. 会员 ──────────────────────────────────────────────────────────
        print("5. 创建会员 (10位)...")
        members_data = [
            ("张伟", "18700000001"),
            ("李娜", "18700000002"),
            ("王芳", "18700000003"),
            ("赵磊", "18700000004"),
            ("陈静", "18700000005"),
            ("刘洋", "18700000006"),
            ("周敏", "18700000007"),
            ("吴军", "18700000008"),
            ("郑红", "18700000009"),
            ("孙浩", "18700000010"),
        ]
        for name, phone in members_data:
            mid = sid(f"czyz-member-{phone}")
            cur.execute("""
                INSERT INTO members (id, tenant_id, name, phone, status)
                VALUES (%s,%s,%s,%s,'active')
                ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name
            """, (mid, TENANT_UUID, name, phone))
        record_count += len(members_data)

        # ── 6. 历史订单 ──────────────────────────────────────────────────────
        print("6. 创建历史订单 (30条，近60天)...")
        rng = random.Random(42)  # 确定性随机
        now = datetime.now(timezone.utc)
        table_ids = [sid(f"czyz-table-{t[0]}") for t in tables_data]

        for i in range(30):
            oid = sid(f"czyz-order-{i:03d}")
            days_ago = rng.randint(0, 59)
            order_time = now - timedelta(days=days_ago, hours=rng.randint(10, 20))
            total_fen = rng.randint(8000, 25000)
            table_id = rng.choice(table_ids)

            cur.execute("""
                INSERT INTO orders (id, tenant_id, store_id, table_id,
                                   total_fen, status, created_at)
                VALUES (%s,%s,%s,%s,%s,'paid',%s)
                ON CONFLICT (id) DO UPDATE SET
                    total_fen=EXCLUDED.total_fen,
                    status=EXCLUDED.status
            """, (oid, TENANT_UUID, STORE_UUID, table_id, total_fen, order_time))
        record_count += 30

        # ── 7. KPI 权重配置 ───────────────────────────────────────────────────
        print("7. 配置 KPI 权重...")
        kpi_weights = {
            "table_turnover":    0.25,
            "dish_time":         0.20,
            "seat_utilization":  0.20,
            "avg_ticket":        0.15,
            "member_repurchase": 0.10,
            "revenue_growth":    0.10,
        }
        config_id = sid(f"czyz-kpi-config")
        cur.execute("""
            INSERT INTO merchant_kpi_weight_configs (id, tenant_id, merchant_code, weights)
            VALUES (%s,%s,%s,%s)
            ON CONFLICT (id) DO UPDATE SET weights=EXCLUDED.weights
        """, (config_id, TENANT_UUID, MERCHANT_CODE, psycopg2.extras.Json(kpi_weights)))
        record_count += 1

        conn.commit()
        print(f"\n✅ 种子数据加载完成: czyz — {record_count} records")
        print(f"   租户 UUID: {TENANT_UUID}")
        print(f"   门店 UUID: {STORE_UUID}")

    except psycopg2.Error as exc:
        conn.rollback()
        print(f"❌ 数据库操作失败: {exc}")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    run()
