#!/usr/bin/env python3
"""
尚宫厨 (sgc) 演示种子数据
策略：宴会+客单优先，湘菜宴席
Run: python3 scripts/seed_sgc.py
"""
import os
import uuid
import random
from datetime import datetime, timedelta, timezone

import psycopg2
import psycopg2.extras

DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://tunxiang:tunxiang_sgc_2024@localhost:5432/tunxiang_sgc",
)

NAMESPACE = uuid.UUID("00000000-0000-0000-0000-000000000000")
MERCHANT_CODE = "sgc"
TENANT_ID_STR = "sgc-demo-tenant"

TENANT_UUID = str(uuid.uuid5(NAMESPACE, TENANT_ID_STR))
STORE_UUID  = str(uuid.uuid5(NAMESPACE, f"{MERCHANT_CODE}-store-001"))


def sid(name: str) -> str:
    return str(uuid.uuid5(NAMESPACE, name))


def _table_exists(cur, table_name: str) -> bool:
    cur.execute("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = %s
        )
    """, (table_name,))
    return bool(cur.fetchone()[0])


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
            VALUES (%s, %s, '尚宫厨', 'enterprise', 'active', '2027-12-31')
            ON CONFLICT (tenant_id) DO UPDATE SET name=EXCLUDED.name, status='active'
        """, (TENANT_UUID, MERCHANT_CODE))
        record_count += 1

        # ── 2. 门店 ──────────────────────────────────────────────────────────
        print("2. 创建门店...")
        cur.execute("""
            INSERT INTO stores (id, tenant_id, store_name, store_code, store_type, store_category,
                               address, seats, monthly_rent_fen)
            VALUES (%s,%s,'尚宫厨·长沙梅溪湖店','sgc-001','dine_in','banquet',
                   '湖南省长沙市岳麓区梅溪湖国际新城',120,10000000)
            ON CONFLICT (id) DO UPDATE SET
                store_name=EXCLUDED.store_name,
                monthly_rent_fen=EXCLUDED.monthly_rent_fen
        """, (STORE_UUID, TENANT_UUID))
        record_count += 1

        # ── 3. 桌台 ──────────────────────────────────────────────────────────
        print("3. 创建桌台 (15张)...")
        tables_data = [
            # 大厅（6席）
            ("A01", "大厅", 6), ("A02", "大厅", 6), ("A03", "大厅", 6),
            ("A04", "大厅", 6), ("A05", "大厅", 6),
            # 商务厅（8席）
            ("B01", "商务厅", 8), ("B02", "商务厅", 8), ("B03", "商务厅", 8),
            ("B04", "商务厅", 8), ("B05", "商务厅", 8),
            # 宴席厅（12席）
            ("VIP01", "宴席厅", 12), ("VIP02", "宴席厅", 12), ("VIP03", "宴席厅", 12),
            ("VIP04", "宴席厅", 12), ("VIP05", "宴席厅", 12),
        ]
        for table_no, area, seats in tables_data:
            cur.execute("""
                INSERT INTO tables (id, tenant_id, store_id, table_no, area, seats, status)
                VALUES (%s,%s,%s,%s,%s,%s,'free')
                ON CONFLICT (id) DO UPDATE SET area=EXCLUDED.area, seats=EXCLUDED.seats
            """, (sid(f"sgc-table-{table_no}"), TENANT_UUID, STORE_UUID, table_no, area, seats))
        record_count += len(tables_data)

        # ── 4. 菜品 ──────────────────────────────────────────────────────────
        print("4. 创建菜品 (15道)...")
        dishes_data = [
            ("尚宫特色全鱼宴",   "宴席", 12800),
            ("红烧湘猪头",       "湘菜",  8800),
            ("剁椒全鱼",         "湘菜",  7800),
            ("毛氏红烧肉宴席版", "湘菜",  5800),
            ("湘西土匪鸭",       "湘菜",  6500),
            ("组庵鱼翅",         "宴席", 15800),
            ("宫廷荷叶饭",       "主食",  2800),
            ("皇宫糯米鸡",       "宴席",  3500),
            ("宫廷八宝饭",       "宴席",  4200),
            ("尚宫银耳羹",       "甜品",  2200),
            ("湘妃醉虾",         "湘菜",  8800),
            ("宫廷腊味煲",       "湘菜",  5500),
            ("御品清蒸鲈鱼",     "宴席",  9800),
            ("宫廷红烧肉",       "湘菜",  5200),
            ("尚宫炸酥肉",       "湘菜",  3800),
        ]
        for i, (name, category, price_fen) in enumerate(dishes_data):
            did = sid(f"sgc-dish-{name}")
            cur.execute("""
                INSERT INTO dishes (id, tenant_id, store_id, dish_name, dish_code,
                                   price_fen, original_price_fen, is_available)
                VALUES (%s,%s,%s,%s,%s,%s,%s,TRUE)
                ON CONFLICT (id) DO UPDATE SET
                    dish_name=EXCLUDED.dish_name,
                    price_fen=EXCLUDED.price_fen
            """, (did, TENANT_UUID, STORE_UUID, name, f"SGC{i+1:03d}", price_fen, price_fen))
        record_count += len(dishes_data)

        # ── 5. 会员 ──────────────────────────────────────────────────────────
        print("5. 创建会员 (8位，以企业客户为主)...")
        members_data = [
            ("湘中建工集团",   "18900000001"),
            ("星城地产",       "18900000002"),
            ("长沙银行贵宾部", "18900000003"),
            ("湘雅医院行政",   "18900000004"),
            ("中联重科接待",   "18900000005"),
            ("三一重工宴会",   "18900000006"),
            ("省政府接待处",   "18900000007"),
            ("南方航空湘分",   "18900000008"),
        ]
        for name, phone in members_data:
            mid = sid(f"sgc-member-{phone}")
            cur.execute("""
                INSERT INTO members (id, tenant_id, name, phone, status)
                VALUES (%s,%s,%s,%s,'active')
                ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name
            """, (mid, TENANT_UUID, name, phone))
        record_count += len(members_data)

        # ── 6. 历史订单 ──────────────────────────────────────────────────────
        print("6. 创建历史订单 (20条，宴席高客单，近60天)...")
        rng = random.Random(44)
        now = datetime.now(timezone.utc)
        table_ids = [sid(f"sgc-table-{t[0]}") for t in tables_data]
        member_ids = [sid(f"sgc-member-{m[1]}") for m in members_data]

        for i in range(20):
            oid = sid(f"sgc-order-{i:03d}")
            days_ago = rng.randint(0, 59)
            order_time = now - timedelta(days=days_ago, hours=rng.randint(11, 20))
            total_fen = rng.randint(30000, 120000)
            table_id = rng.choice(table_ids)
            member_id = rng.choice(member_ids) if rng.random() > 0.2 else None

            cur.execute("""
                INSERT INTO orders (id, tenant_id, store_id, table_id, member_id,
                                   total_fen, status, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,'paid',%s)
                ON CONFLICT (id) DO UPDATE SET
                    total_fen=EXCLUDED.total_fen,
                    status=EXCLUDED.status
            """, (oid, TENANT_UUID, STORE_UUID, table_id, member_id, total_fen, order_time))
        record_count += 20

        # ── 7. 宴会订金（可选）────────────────────────────────────────────────
        print("7. 尝试创建宴会订金记录 (5条)...")
        if _table_exists(cur, "banquet_deposits"):
            deposits_data = [
                (sid(f"sgc-deposit-{i}"), rng.randint(5000000, 20000000))
                for i in range(5)
            ]
            for dep_id, amount_fen in deposits_data:
                banquet_order_id = sid(f"sgc-order-{rng.randint(0, 19):03d}")
                cur.execute("""
                    INSERT INTO banquet_deposits (id, tenant_id, store_id, order_id, deposit_amount_fen, status)
                    VALUES (%s,%s,%s,%s,%s,'confirmed')
                    ON CONFLICT (id) DO UPDATE SET deposit_amount_fen=EXCLUDED.deposit_amount_fen
                """, (dep_id, TENANT_UUID, STORE_UUID, banquet_order_id, amount_fen))
            record_count += 5
            print("   宴会订金表已存在，已写入 5 条记录")
        else:
            print("   ⚠️  banquet_deposits 表不存在，跳过宴会订金数据（请运行相关迁移后重新执行）")

        # ── 8. KPI 权重配置 ───────────────────────────────────────────────────
        print("8. 配置 KPI 权重...")
        kpi_weights = {
            "avg_ticket":           0.30,
            "banquet_deposit_rate": 0.20,
            "labor_cost_ratio":     0.15,
            "member_repurchase":    0.10,
            "revenue_growth":       0.15,
            "seat_utilization":     0.10,
        }
        config_id = sid(f"sgc-kpi-config")
        cur.execute("""
            INSERT INTO merchant_kpi_weight_configs (id, tenant_id, merchant_code, weights)
            VALUES (%s,%s,%s,%s)
            ON CONFLICT (id) DO UPDATE SET weights=EXCLUDED.weights
        """, (config_id, TENANT_UUID, MERCHANT_CODE, psycopg2.extras.Json(kpi_weights)))
        record_count += 1

        conn.commit()
        print(f"\n✅ 种子数据加载完成: sgc — {record_count} records")
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
