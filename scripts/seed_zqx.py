#!/usr/bin/env python3
"""
最黔线 (zqx) 演示种子数据
策略：客单+复购优先，贵州菜
Run: python3 scripts/seed_zqx.py
"""
import os
import uuid
import random
from datetime import datetime, timedelta, timezone

import psycopg2
import psycopg2.extras

DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://tunxiang:tunxiang_zqx_2024@localhost:5432/tunxiang_zqx",
)

NAMESPACE = uuid.UUID("00000000-0000-0000-0000-000000000000")
MERCHANT_CODE = "zqx"
TENANT_ID_STR = "zqx-demo-tenant"

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
            VALUES (%s, %s, '最黔线', 'standard', 'active', '2027-12-31')
            ON CONFLICT (tenant_id) DO UPDATE SET name=EXCLUDED.name, status='active'
        """, (TENANT_UUID, MERCHANT_CODE))
        record_count += 1

        # ── 2. 门店 ──────────────────────────────────────────────────────────
        print("2. 创建门店...")
        cur.execute("""
            INSERT INTO stores (id, tenant_id, store_name, store_code, store_type, store_category,
                               address, seats, monthly_rent_fen)
            VALUES (%s,%s,'最黔线·长沙解放西店','zqx-001','dine_in','guizhou',
                   '湖南省长沙市芙蓉区解放西路',60,5000000)
            ON CONFLICT (id) DO UPDATE SET
                store_name=EXCLUDED.store_name,
                monthly_rent_fen=EXCLUDED.monthly_rent_fen
        """, (STORE_UUID, TENANT_UUID))
        record_count += 1

        # ── 3. 桌台 ──────────────────────────────────────────────────────────
        print("3. 创建桌台 (10张)...")
        tables_data = [
            ("Z01", "大厅", 4), ("Z02", "大厅", 4), ("Z03", "大厅", 4),
            ("Z04", "大厅", 4), ("Z05", "大厅", 4), ("Z06", "大厅", 4),
            ("VIP01", "VIP包间", 8), ("VIP02", "VIP包间", 8),
            ("VIP03", "VIP包间", 8), ("VIP04", "VIP包间", 8),
        ]
        for table_no, area, seats in tables_data:
            cur.execute("""
                INSERT INTO tables (id, tenant_id, store_id, table_no, area, seats, status)
                VALUES (%s,%s,%s,%s,%s,%s,'free')
                ON CONFLICT (id) DO UPDATE SET area=EXCLUDED.area, seats=EXCLUDED.seats
            """, (sid(f"zqx-table-{table_no}"), TENANT_UUID, STORE_UUID, table_no, area, seats))
        record_count += len(tables_data)

        # ── 4. 菜品 ──────────────────────────────────────────────────────────
        print("4. 创建菜品 (15道)...")
        dishes_data = [
            ("贵州酸汤鱼",     "黔菜", 6800),
            ("折耳根炒腊肉",   "黔菜", 3200),
            ("糟辣脆皮鱼",     "黔菜", 5500),
            ("凯里红酸汤",     "汤品", 4200),
            ("贵阳肠旺面",     "主食", 1800),
            ("丝娃娃",         "小吃", 2500),
            ("老干妈拌豆腐",   "凉菜", 1500),
            ("青椒童子鸡",     "黔菜", 4800),
            ("贵州烤鱼",       "黔菜", 5800),
            ("黄粑",           "小吃", 1200),
            ("水城羊肉粉",     "主食", 2200),
            ("花溪牛肉粉",     "主食", 2200),
            ("遵义辣子鸡",     "黔菜", 4500),
            ("布依米豆腐",     "黔菜", 1800),
            ("贵州苗家酸肉",   "黔菜", 3800),
        ]
        for i, (name, category, price_fen) in enumerate(dishes_data):
            did = sid(f"zqx-dish-{name}")
            cur.execute("""
                INSERT INTO dishes (id, tenant_id, store_id, dish_name, dish_code,
                                   price_fen, original_price_fen, is_available)
                VALUES (%s,%s,%s,%s,%s,%s,%s,TRUE)
                ON CONFLICT (id) DO UPDATE SET
                    dish_name=EXCLUDED.dish_name,
                    price_fen=EXCLUDED.price_fen
            """, (did, TENANT_UUID, STORE_UUID, name, f"ZQX{i+1:03d}", price_fen, price_fen))
        record_count += len(dishes_data)

        # ── 5. 会员 ──────────────────────────────────────────────────────────
        print("5. 创建会员 (15位，强调复购)...")
        members_data = [
            ("张鹏", "18800000001"),
            ("李梅", "18800000002"),
            ("王涛", "18800000003"),
            ("赵霞", "18800000004"),
            ("陈刚", "18800000005"),
            ("刘芳", "18800000006"),
            ("周勇", "18800000007"),
            ("吴丽", "18800000008"),
            ("郑宇", "18800000009"),
            ("孙燕", "18800000010"),
            ("徐波", "18800000011"),
            ("朱雪", "18800000012"),
            ("胡峰", "18800000013"),
            ("林娟", "18800000014"),
            ("何亮", "18800000015"),
        ]
        for name, phone in members_data:
            mid = sid(f"zqx-member-{phone}")
            cur.execute("""
                INSERT INTO members (id, tenant_id, name, phone, status)
                VALUES (%s,%s,%s,%s,'active')
                ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name
            """, (mid, TENANT_UUID, name, phone))
        record_count += len(members_data)

        # ── 6. 历史订单 ──────────────────────────────────────────────────────
        print("6. 创建历史订单 (25条，高客单价，近60天)...")
        rng = random.Random(43)
        now = datetime.now(timezone.utc)
        table_ids = [sid(f"zqx-table-{t[0]}") for t in tables_data]
        member_ids = [sid(f"zqx-member-{m[1]}") for m in members_data]

        for i in range(25):
            oid = sid(f"zqx-order-{i:03d}")
            days_ago = rng.randint(0, 59)
            order_time = now - timedelta(days=days_ago, hours=rng.randint(11, 21))
            total_fen = rng.randint(15000, 40000)
            table_id = rng.choice(table_ids)
            member_id = rng.choice(member_ids) if rng.random() > 0.3 else None

            cur.execute("""
                INSERT INTO orders (id, tenant_id, store_id, table_id, member_id,
                                   total_fen, status, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,'paid',%s)
                ON CONFLICT (id) DO UPDATE SET
                    total_fen=EXCLUDED.total_fen,
                    status=EXCLUDED.status
            """, (oid, TENANT_UUID, STORE_UUID, table_id, member_id, total_fen, order_time))
        record_count += 25

        # ── 7. KPI 权重配置 ───────────────────────────────────────────────────
        print("7. 配置 KPI 权重...")
        kpi_weights = {
            "avg_ticket":        0.25,
            "member_repurchase": 0.25,
            "revenue_growth":    0.15,
            "dish_time":         0.10,
            "seat_utilization":  0.10,
            "channel_mix":       0.15,
        }
        config_id = sid(f"zqx-kpi-config")
        cur.execute("""
            INSERT INTO merchant_kpi_weight_configs (id, tenant_id, merchant_code, weights)
            VALUES (%s,%s,%s,%s)
            ON CONFLICT (id) DO UPDATE SET weights=EXCLUDED.weights
        """, (config_id, TENANT_UUID, MERCHANT_CODE, psycopg2.extras.Json(kpi_weights)))
        record_count += 1

        conn.commit()
        print(f"\n✅ 种子数据加载完成: zqx — {record_count} records")
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
