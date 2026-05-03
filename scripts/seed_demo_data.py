#!/usr/bin/env python3
"""
Demo seed data for 屯象OS — 模拟徐记海鲜门店业务场景
Run: python3 scripts/seed_demo_data.py

安全说明：从 DATABASE_URL 环境变量读取，不硬编码密码。
"""
import os
import psycopg2
import uuid

DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://tunxiang:changeme@localhost:5432/tunxiang_dev",
)
TENANT_ID = "10000000-0000-0000-0000-000000000001"
STORE_ID   = "20000000-0000-0000-0000-000000000001"

def sid(namespace_str, name):
    """Deterministic UUID based on namespace + name"""
    return str(uuid.uuid5(uuid.UUID(namespace_str), name))

def run():
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False
    cur = conn.cursor()
    cur.execute(f"SET app.tenant_id = '{TENANT_ID}'")

    try:
        # ── 1. 租户 ──────────────────────────────────────────────────────
        print("1. 创建租户...")
        cur.execute("""
            INSERT INTO platform_tenants (tenant_id, merchant_code, name, plan_template, status, subscription_expires_at)
            VALUES (%s, 'XJ001', '屯象演示·徐记海鲜集团', 'enterprise', 'active', '2027-12-31')
            ON CONFLICT (tenant_id) DO UPDATE SET name=EXCLUDED.name, status='active'
        """, (TENANT_ID,))

        # ── 2. 门店 ──────────────────────────────────────────────────────
        print("2. 创建门店...")
        cur.execute("""
            INSERT INTO stores (id, tenant_id, store_name, store_code, store_type, store_category,
                               address, phone, seats,
                               monthly_rent_fen, monthly_utility_fen, monthly_other_fixed_fen)
            VALUES (%s,%s,'徐记海鲜·五一广场旗舰店','XJ-HN-001','dine_in','seafood',
                   '湖南省长沙市天心区五一广场8号','0731-88888888',280,
                   8000000,1500000,500000)
            ON CONFLICT (id) DO UPDATE SET store_name=EXCLUDED.store_name
        """, (STORE_ID, TENANT_ID))

        # ── 3. 桌台 ──────────────────────────────────────────────────────
        print("3. 创建桌台 (15张)...")
        tables_data = [
            ("A01","大厅A区",4), ("A02","大厅A区",4), ("A03","大厅A区",6),
            ("A04","大厅A区",6), ("A05","大厅A区",8),
            ("B01","大厅B区",4), ("B02","大厅B区",4), ("B03","大厅B区",6),
            ("B04","大厅B区",8), ("B05","大厅B区",10),
            ("VIP01","VIP包间",8), ("VIP02","VIP包间",10), ("VIP03","VIP包间",12),
            ("T01","散台区",2),   ("T02","散台区",2),
        ]
        for table_no, area, seats in tables_data:
            cur.execute("""
                INSERT INTO tables (id, tenant_id, store_id, table_no, area, seats, status)
                VALUES (%s,%s,%s,%s,%s,%s,'free')
                ON CONFLICT (id) DO UPDATE SET area=EXCLUDED.area, seats=EXCLUDED.seats
            """, (sid(STORE_ID, f"t_{table_no}"), TENANT_ID, STORE_ID, table_no, area, seats))

        # ── 4. 员工 ──────────────────────────────────────────────────────
        print("4. 创建员工 (6人)...")
        employees_data = [
            ("张经理","18600000001","manager"),
            ("李收银","18600000002","cashier"),
            ("王服务","18600000003","waiter"),
            ("陈服务","18600000004","waiter"),
            ("赵厨师","18600000005","chef"),
            ("钱前台","18600000006","cashier"),
        ]
        for name, phone, role in employees_data:
            eid = sid(STORE_ID, f"emp_{phone}")
            cur.execute("""
                INSERT INTO employees (id, tenant_id, store_id, emp_name, phone, role, employment_status)
                VALUES (%s,%s,%s,%s,%s,%s,'regular')
                ON CONFLICT (id) DO UPDATE SET emp_name=EXCLUDED.emp_name
            """, (eid, TENANT_ID, STORE_ID, name, phone, role))
            if role == "manager":
                cur.execute("UPDATE stores SET manager_id=%s WHERE id=%s", (eid, STORE_ID))

        # ── 5. 菜品分类 ──────────────────────────────────────────────────
        print("5. 创建菜品分类 (7类)...")
        cats_data = [
            ("活鲜海鲜","seafood_live",1),
            ("海鲜加工","seafood_cooked",2),
            ("冷菜凉拌","cold_dish",3),
            ("热菜炒菜","hot_dish",4),
            ("汤品煲类","soup",5),
            ("主食点心","staple",6),
            ("饮品酒水","beverage",7),
        ]
        CAT = {}
        for cname, ccode, sort in cats_data:
            cid = sid(STORE_ID, f"cat_{ccode}")
            CAT[ccode] = cid
            cur.execute("""
                INSERT INTO dish_categories (id, tenant_id, store_id, name, code, sort_order)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name
            """, (cid, TENANT_ID, STORE_ID, cname, ccode, sort))

        # ── 6. 菜品 ──────────────────────────────────────────────────────
        print("6. 创建菜品 (30道)...")
        dishes_data = [
            # 活鲜
            ("大连鲍鱼",  "seafood_live",  8800, "个", 0),
            ("澳洲龙虾",  "seafood_live", 48800, "只", 0),
            ("波士顿龙虾","seafood_live", 38800, "只", 0),
            ("象拔蚌",    "seafood_live", 12800, "份", 0),
            ("生蚝",      "seafood_live",  3800, "打", 0),
            ("基围虾",    "seafood_live",  9800, "斤", 0),
            ("螃蟹",      "seafood_live", 13800, "只", 0),
            ("石斑鱼",    "seafood_live", 18800, "斤", 0),
            # 加工
            ("蒜蓉粉丝蒸扇贝", "seafood_cooked",  6800, "份", 0),
            ("葱姜炒花蟹",     "seafood_cooked", 10800, "份", 1),
            ("白灼濑尿虾",     "seafood_cooked", 14800, "份", 0),
            ("清蒸石斑鱼",     "seafood_cooked", 22800, "份", 1),
            ("香辣小龙虾",     "seafood_cooked",  8800, "份", 2),
            # 冷菜
            ("醉鸡",    "cold_dish", 3800, "份", 0),
            ("皮蛋豆腐","cold_dish", 2800, "份", 0),
            ("酸辣粉",  "cold_dish", 2200, "份", 0),
            # 热菜
            ("剁椒鱼头","hot_dish",  9800, "份", 2),
            ("红烧肉",  "hot_dish",  5800, "份", 0),
            ("土豆丝",  "hot_dish",  2800, "份", 0),
            ("炒时蔬",  "hot_dish",  2400, "份", 0),
            ("干锅虾",  "hot_dish",  8800, "份", 1),
            # 汤
            ("海鲜乌鸡汤","soup", 5800, "例", 0),
            ("冬瓜排骨汤","soup", 3800, "例", 0),
            # 主食
            ("白米饭",  "staple",  200, "碗", 0),
            ("蛋炒饭",  "staple", 1800, "份", 0),
            ("捞面",    "staple", 2200, "碗", 0),
            # 饮品
            ("可乐",      "beverage",   800, "瓶", 0),
            ("雪碧",      "beverage",   800, "瓶", 0),
            ("青岛啤酒",  "beverage",  1500, "瓶", 0),
            ("长城干红葡萄酒","beverage",28800,"瓶", 0),
        ]
        for i, (dname, ccode, price_fen, unit, spicy) in enumerate(dishes_data):
            did = sid(STORE_ID, f"dish_{dname}")
            dcode = f"D{i+1:03d}"
            cur.execute("""
                INSERT INTO dishes (id, tenant_id, store_id, dish_name, dish_code, category_id,
                                   price_fen, original_price_fen, unit, spicy_level, is_available)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE)
                ON CONFLICT (id) DO UPDATE SET
                    dish_name=EXCLUDED.dish_name, price_fen=EXCLUDED.price_fen
            """, (did, TENANT_ID, STORE_ID, dname, dcode, CAT.get(ccode), price_fen, price_fen, unit, spicy))

        conn.commit()
        print(f"""
╔══════════════════════════════════════════╗
║      ✅ Demo数据创建成功！               ║
╚══════════════════════════════════════════╝
  租户ID: {TENANT_ID}
  门店ID: {STORE_ID}
  桌台:   {len(tables_data)} 张
  员工:   {len(employees_data)} 人
  分类:   {len(cats_data)} 个
  菜品:   {len(dishes_data)} 道

访问地址：
  管理后台  http://localhost:5173
  POS收银   http://localhost:5174
  KDS出餐   http://localhost:5175

注意：前端页面需要在URL或Header中传入 store_id 和 tenant_id
""")

    except Exception as e:
        conn.rollback()
        import traceback
        print(f"❌ 错误: {e}")
        traceback.print_exc()
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    run()
