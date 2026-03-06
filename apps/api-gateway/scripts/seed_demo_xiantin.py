"""
闲庭食记演示数据种子脚本（直接 SQL，兼容实际 DB schema）

生成10家门店30天真实经营数据：
- 10家门店 + 每店7名员工
- 中式菜品（30个SKU）
- 库存食材（20种）
- 30天历史订单（每店日均100-160桌）
- 损耗事件 + KPI记录

运行：
    cd apps/api-gateway
    DATABASE_URL='postgresql+asyncpg://...' python3 scripts/seed_demo_xiantin.py
"""
import asyncio
import os
import random
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

# 必须在所有 src.* 导入前设置环境变量
for _k, _v in {
    "DATABASE_URL":          os.getenv("DATABASE_URL", "postgresql+asyncpg://zhilian:zhilian@localhost:5432/zhilian_os"),
    "REDIS_URL":             os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    "CELERY_BROKER_URL":     os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"),
    "CELERY_RESULT_BACKEND": os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/0"),
    "SECRET_KEY":            os.getenv("SECRET_KEY", "demo-secret-key"),
    "JWT_SECRET":            os.getenv("JWT_SECRET", "demo-jwt-secret"),
}.items():
    os.environ.setdefault(_k, _v)

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncConnection

random.seed(42)

BRAND_ID = "B001_XIANTIN"
TODAY = date(2026, 3, 6)
SEED_START = TODAY - timedelta(days=29)  # 30天数据

# ─── 门店定义 ────────────────────────────────────────────────────────────────

STORES = [
    {"id": "XT001", "code": "XT001", "name": "闲庭食记·朝阳大悦城店", "address": "北京市朝阳区朝阳北路101号大悦城"},
    {"id": "XT002", "code": "XT002", "name": "闲庭食记·海淀五道口店", "address": "北京市海淀区成府路28号五道口购物中心"},
    {"id": "XT003", "code": "XT003", "name": "闲庭食记·静安寺店",     "address": "上海市静安区愚园路88号"},
    {"id": "XT004", "code": "XT004", "name": "闲庭食记·徐汇天钥桥店", "address": "上海市徐汇区天钥桥路188号"},
    {"id": "XT005", "code": "XT005", "name": "闲庭食记·天河正佳店",   "address": "广州市天河区天河路228号正佳广场"},
    {"id": "XT006", "code": "XT006", "name": "闲庭食记·南山海岸城店", "address": "深圳市南山区海岸城购物中心B1"},
    {"id": "XT007", "code": "XT007", "name": "闲庭食记·锦江宾馆旁店", "address": "成都市锦江区人民南路二段66号"},
    {"id": "XT008", "code": "XT008", "name": "闲庭食记·解放碑店",     "address": "重庆市渝中区邹容路68号"},
    {"id": "XT009", "code": "XT009", "name": "闲庭食记·湖滨银泰店",   "address": "杭州市上城区中河中路298号银泰城"},
    {"id": "XT010", "code": "XT010", "name": "闲庭食记·新街口德基店", "address": "南京市玄武区中山路8号德基广场"},
]

# 门店指标配置（独立于 stores 表）
STORE_METRICS = {
    "XT001": {"seats": 180, "monthly_target_yuan": 12000, "cost_target": 0.32},
    "XT002": {"seats": 150, "monthly_target_yuan": 10500, "cost_target": 0.33},
    "XT003": {"seats": 200, "monthly_target_yuan": 13500, "cost_target": 0.31},
    "XT004": {"seats": 160, "monthly_target_yuan": 11000, "cost_target": 0.32},
    "XT005": {"seats": 210, "monthly_target_yuan": 11500, "cost_target": 0.33},
    "XT006": {"seats": 185, "monthly_target_yuan": 12500, "cost_target": 0.32},
    "XT007": {"seats": 140, "monthly_target_yuan":  9000, "cost_target": 0.34},
    "XT008": {"seats": 150, "monthly_target_yuan":  9500, "cost_target": 0.34},
    "XT009": {"seats": 170, "monthly_target_yuan": 10800, "cost_target": 0.33},
    "XT010": {"seats": 160, "monthly_target_yuan": 10000, "cost_target": 0.33},
}

# ─── 员工 ────────────────────────────────────────────────────────────────────

EMPLOYEE_NAMES = [
    "张伟", "李娜", "王芳", "刘洋", "陈静", "杨帆", "黄磊", "赵雪",
    "周明", "吴丽", "徐强", "孙莉", "马超", "胡燕", "林峰", "何梅",
    "郭勇", "高红", "谢宁", "郑博", "宋燕", "许刚", "邓晨", "韩雨",
    "冯磊", "曹青", "彭飞", "唐霞", "董健", "萧雪", "程鹏", "傅波",
    "蒋浩", "沈璐", "薛辉", "范冰", "潘建", "严明", "史磊", "孔颖",
    "邵斌", "毛丽", "姜涛", "卢芳", "贾伟", "钱宇", "秦萌", "苏华",
    "侯文", "常娜", "武勇", "田雪", "廖杰", "余静", "魏磊", "谭颖",
    "席超", "蔡丽", "贺波", "丁涛", "龙飞", "熊红", "陆阳", "戴璐",
    "汪明", "石燕", "崔健", "顾雪", "江磊", "洪丽", "夏波", "陶颖",
]

POSITIONS_PER_STORE = ["store_manager", "chef", "sous_chef", "waiter", "waiter", "waiter", "cashier"]

# ─── 菜品（30个SKU）─────────────────────────────────────────────────────────

DISHES = [
    # 热菜 (price in yuan)
    {"name": "宫保鸡丁",   "code": "DISH001", "cat": "热菜", "price": 58.0,  "cost_rate": 0.32},
    {"name": "鱼香肉丝",   "code": "DISH002", "cat": "热菜", "price": 48.0,  "cost_rate": 0.30},
    {"name": "麻婆豆腐",   "code": "DISH003", "cat": "热菜", "price": 38.0,  "cost_rate": 0.28},
    {"name": "回锅肉",     "code": "DISH004", "cat": "热菜", "price": 52.0,  "cost_rate": 0.35},
    {"name": "东坡肉",     "code": "DISH005", "cat": "热菜", "price": 68.0,  "cost_rate": 0.38},
    {"name": "糖醋排骨",   "code": "DISH006", "cat": "热菜", "price": 62.0,  "cost_rate": 0.36},
    {"name": "清蒸鲈鱼",   "code": "DISH007", "cat": "热菜", "price": 98.0,  "cost_rate": 0.42},
    {"name": "蒜蓉虾",     "code": "DISH008", "cat": "热菜", "price": 88.0,  "cost_rate": 0.40},
    {"name": "干煸四季豆", "code": "DISH009", "cat": "热菜", "price": 36.0,  "cost_rate": 0.25},
    {"name": "辣子鸡",     "code": "DISH010", "cat": "热菜", "price": 68.0,  "cost_rate": 0.34},
    # 凉菜
    {"name": "夫妻肺片",   "code": "DISH011", "cat": "凉菜", "price": 48.0,  "cost_rate": 0.30},
    {"name": "口水鸡",     "code": "DISH012", "cat": "凉菜", "price": 42.0,  "cost_rate": 0.32},
    {"name": "凉拌木耳",   "code": "DISH013", "cat": "凉菜", "price": 28.0,  "cost_rate": 0.22},
    {"name": "拍黄瓜",     "code": "DISH014", "cat": "凉菜", "price": 22.0,  "cost_rate": 0.20},
    {"name": "花生米",     "code": "DISH015", "cat": "凉菜", "price": 18.0,  "cost_rate": 0.18},
    # 主食
    {"name": "扬州炒饭",   "code": "DISH016", "cat": "主食", "price": 28.0,  "cost_rate": 0.30},
    {"name": "担担面",     "code": "DISH017", "cat": "主食", "price": 26.0,  "cost_rate": 0.28},
    {"name": "蛋炒饭",     "code": "DISH018", "cat": "主食", "price": 22.0,  "cost_rate": 0.26},
    {"name": "葱油拌面",   "code": "DISH019", "cat": "主食", "price": 20.0,  "cost_rate": 0.24},
    {"name": "酸辣汤饭",   "code": "DISH020", "cat": "主食", "price": 24.0,  "cost_rate": 0.28},
    # 汤品
    {"name": "番茄蛋花汤", "code": "DISH021", "cat": "汤品", "price": 18.0,  "cost_rate": 0.22},
    {"name": "酸辣汤",     "code": "DISH022", "cat": "汤品", "price": 22.0,  "cost_rate": 0.24},
    {"name": "紫菜蛋花汤", "code": "DISH023", "cat": "汤品", "price": 16.0,  "cost_rate": 0.20},
    {"name": "玉米排骨汤", "code": "DISH024", "cat": "汤品", "price": 48.0,  "cost_rate": 0.35},
    # 饮品
    {"name": "菊花茶",     "code": "DISH025", "cat": "饮品", "price": 12.0,  "cost_rate": 0.15},
    {"name": "乌梅汁",     "code": "DISH026", "cat": "饮品", "price": 14.0,  "cost_rate": 0.16},
    {"name": "绿茶",       "code": "DISH027", "cat": "饮品", "price": 10.0,  "cost_rate": 0.14},
    # 小吃
    {"name": "锅贴",       "code": "DISH028", "cat": "小吃", "price": 32.0,  "cost_rate": 0.28},
    {"name": "春卷",       "code": "DISH029", "cat": "小吃", "price": 28.0,  "cost_rate": 0.26},
    {"name": "炸藕盒",     "code": "DISH030", "cat": "小吃", "price": 36.0,  "cost_rate": 0.30},
]

HOT_DISHES = ["DISH001", "DISH003", "DISH004", "DISH007", "DISH010", "DISH016"]

# ─── 食材 ────────────────────────────────────────────────────────────────────

INGREDIENTS = [
    {"id": "INV001", "name": "鸡胸肉",      "cat": "肉类",   "unit": "kg",  "unit_cost": 1800,  "min_qty": 10, "max_qty": 50},
    {"id": "INV002", "name": "猪里脊",      "cat": "肉类",   "unit": "kg",  "unit_cost": 2200,  "min_qty": 8,  "max_qty": 40},
    {"id": "INV003", "name": "猪五花",      "cat": "肉类",   "unit": "kg",  "unit_cost": 1900,  "min_qty": 8,  "max_qty": 40},
    {"id": "INV004", "name": "猪排骨",      "cat": "肉类",   "unit": "kg",  "unit_cost": 2800,  "min_qty": 5,  "max_qty": 30},
    {"id": "INV005", "name": "鲈鱼",        "cat": "水产",   "unit": "kg",  "unit_cost": 3500,  "min_qty": 5,  "max_qty": 25},
    {"id": "INV006", "name": "大虾",        "cat": "水产",   "unit": "kg",  "unit_cost": 4800,  "min_qty": 5,  "max_qty": 25},
    {"id": "INV007", "name": "豆腐",        "cat": "豆制品", "unit": "kg",  "unit_cost":  400,  "min_qty": 15, "max_qty": 60},
    {"id": "INV008", "name": "四季豆",      "cat": "蔬菜",   "unit": "kg",  "unit_cost":  600,  "min_qty": 8,  "max_qty": 40},
    {"id": "INV009", "name": "黄瓜",        "cat": "蔬菜",   "unit": "kg",  "unit_cost":  380,  "min_qty": 8,  "max_qty": 40},
    {"id": "INV010", "name": "番茄",        "cat": "蔬菜",   "unit": "kg",  "unit_cost":  450,  "min_qty": 10, "max_qty": 50},
    {"id": "INV011", "name": "大米",        "cat": "主食",   "unit": "kg",  "unit_cost":  350,  "min_qty": 30, "max_qty": 120},
    {"id": "INV012", "name": "面条",        "cat": "主食",   "unit": "kg",  "unit_cost":  280,  "min_qty": 15, "max_qty": 60},
    {"id": "INV013", "name": "食用油",      "cat": "调料",   "unit": "L",   "unit_cost":  900,  "min_qty": 10, "max_qty": 40},
    {"id": "INV014", "name": "黑木耳（干）","cat": "干货",   "unit": "kg",  "unit_cost": 2400,  "min_qty": 3,  "max_qty": 15},
    {"id": "INV015", "name": "花生米",      "cat": "干货",   "unit": "kg",  "unit_cost":  800,  "min_qty": 5,  "max_qty": 25},
    {"id": "INV016", "name": "鸡蛋",        "cat": "蛋类",   "unit": "个",  "unit_cost":   80,  "min_qty": 60, "max_qty": 200},
    {"id": "INV017", "name": "葱",          "cat": "调料",   "unit": "kg",  "unit_cost":  280,  "min_qty": 5,  "max_qty": 20},
    {"id": "INV018", "name": "姜",          "cat": "调料",   "unit": "kg",  "unit_cost":  350,  "min_qty": 3,  "max_qty": 15},
    {"id": "INV019", "name": "蒜",          "cat": "调料",   "unit": "kg",  "unit_cost":  450,  "min_qty": 3,  "max_qty": 15},
    {"id": "INV020", "name": "干辣椒",      "cat": "调料",   "unit": "kg",  "unit_cost": 1200,  "min_qty": 2,  "max_qty": 10},
]

WASTE_EVENT_TYPES = [
    "cooking_loss", "spoilage", "over_prep", "drop_damage",
    "quality_reject", "transfer_loss", "unknown",
]


# ─── 主函数 ──────────────────────────────────────────────────────────────────

async def seed():
    db_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(db_url, echo=False)

    async with engine.begin() as conn:
        await _seed_stores(conn)
        print("✓ 门店创建完成")

    async with engine.begin() as conn:
        store_employees = await _seed_employees(conn)
        print("✓ 员工创建完成")

    async with engine.begin() as conn:
        dish_map = await _seed_dishes(conn)
        print("✓ 菜品创建完成")

    async with engine.begin() as conn:
        await _seed_inventory(conn)
        print("✓ 库存创建完成")

    async with engine.begin() as conn:
        await _seed_orders(conn, dish_map, store_employees)
        print("✓ 订单创建完成（30天）")

    async with engine.begin() as conn:
        await _seed_waste_events(conn)
        print("✓ 损耗事件创建完成")

    async with engine.begin() as conn:
        await _seed_kpi_records(conn)
        print("✓ KPI记录创建完成")

    await engine.dispose()
    print(f"\n演示数据初始化完成！10家门店 | 30天 ({SEED_START} → {TODAY})")


# ─── 门店 ────────────────────────────────────────────────────────────────────

async def _seed_stores(conn: AsyncConnection):
    for s in STORES:
        result = await conn.execute(
            text("SELECT id FROM stores WHERE id = :id"),
            {"id": s["id"]}
        )
        if result.fetchone():
            continue
        await conn.execute(
            text("""
                INSERT INTO stores (id, code, name, address, brand_id, status, created_at, updated_at)
                VALUES (:id, :code, :name, :address, :brand_id, 'active', NOW(), NOW())
            """),
            {
                "id": s["id"],
                "code": s["code"],
                "name": s["name"],
                "address": s["address"],
                "brand_id": BRAND_ID,
            }
        )


# ─── 员工 ────────────────────────────────────────────────────────────────────

async def _seed_employees(conn: AsyncConnection) -> dict:
    """返回 {store_id: [employee_id, ...]}"""
    store_employees = {}
    name_pool = list(EMPLOYEE_NAMES)
    random.shuffle(name_pool)
    name_idx = 0

    for store in STORES:
        sid = store["id"]
        store_employees[sid] = []
        for i, pos in enumerate(POSITIONS_PER_STORE):
            eid = f"EMP_{sid}_{i+1:02d}"
            result = await conn.execute(
                text("SELECT id FROM employees WHERE id = :id"),
                {"id": eid}
            )
            if result.fetchone():
                store_employees[sid].append(eid)
                name_idx += 1
                continue
            await conn.execute(
                text("""
                    INSERT INTO employees (id, store_id, name, position, skills, hire_date, is_active,
                                          performance_score, created_at, updated_at)
                    VALUES (:id, :store_id, :name, :position, :skills, :hire_date, TRUE,
                            '85', NOW(), NOW())
                """),
                {
                    "id": eid,
                    "store_id": sid,
                    "name": name_pool[name_idx % len(name_pool)],
                    "position": pos,
                    "skills": [pos],
                    "hire_date": date(2023, 6, 1),
                }
            )
            store_employees[sid].append(eid)
            name_idx += 1

    return store_employees


# ─── 菜品 ────────────────────────────────────────────────────────────────────

async def _seed_dishes(conn: AsyncConnection) -> dict:
    """返回 {code: {price_yuan, cost_rate}}"""
    categories = list({d["cat"] for d in DISHES})
    cat_map = {}

    for store in STORES:
        sid = store["id"]
        for cat_name in categories:
            result = await conn.execute(
                text("SELECT id FROM dish_categories WHERE store_id = :sid AND name = :name"),
                {"sid": sid, "name": cat_name}
            )
            row = result.fetchone()
            if row:
                cat_map[f"{sid}_{cat_name}"] = row[0]
            else:
                cid = uuid.uuid4()
                await conn.execute(
                    text("""
                        INSERT INTO dish_categories (id, store_id, name, code, is_active, created_at, updated_at)
                        VALUES (:id, :store_id, :name, :code, TRUE, NOW(), NOW())
                    """),
                    {"id": cid, "store_id": sid, "name": cat_name, "code": f"CAT_{sid}_{cat_name}"}
                )
                cat_map[f"{sid}_{cat_name}"] = cid

    dish_map = {}
    for store in STORES:
        sid = store["id"]
        for d in DISHES:
            code = f"{d['code']}_{sid}"
            result = await conn.execute(
                text("SELECT id, price FROM dishes WHERE code = :code"),
                {"code": code}
            )
            row = result.fetchone()
            if row:
                dish_map[code] = {"price_yuan": float(row[1]), "cost_rate": d["cost_rate"]}
                continue

            price_factor = random.uniform(0.95, 1.05)
            price_yuan = round(d["price"] * price_factor)  # 整元

            await conn.execute(
                text("""
                    INSERT INTO dishes (id, store_id, name, code, category_id, price, is_available,
                                       created_at, updated_at)
                    VALUES (:id, :store_id, :name, :code, :cat_id, :price, TRUE, NOW(), NOW())
                """),
                {
                    "id": uuid.uuid4(),
                    "store_id": sid,
                    "name": d["name"],
                    "code": code,
                    "cat_id": cat_map.get(f"{sid}_{d['cat']}"),
                    "price": price_yuan,
                }
            )
            dish_map[code] = {"price_yuan": float(price_yuan), "cost_rate": d["cost_rate"]}

    return dish_map


# ─── 库存 ────────────────────────────────────────────────────────────────────

async def _seed_inventory(conn: AsyncConnection):
    for store in STORES:
        sid = store["id"]
        for ing in INGREDIENTS:
            iid = f"{ing['id']}_{sid}"
            result = await conn.execute(
                text("SELECT id FROM inventory_items WHERE id = :id"),
                {"id": iid}
            )
            if result.fetchone():
                continue
            current = round(random.uniform(ing["min_qty"] * 1.5, ing["max_qty"] * 0.8), 2)
            await conn.execute(
                text("""
                    INSERT INTO inventory_items
                        (id, store_id, name, category, unit, current_quantity, min_quantity, max_quantity,
                         unit_cost, status, supplier_name, supplier_contact, created_at, updated_at)
                    VALUES (:id, :store_id, :name, :category, :unit, :current_qty, :min_qty, :max_qty,
                            :unit_cost, 'normal', '奥琦玮供应链', '400-888-0001', NOW(), NOW())
                """),
                {
                    "id": iid,
                    "store_id": sid,
                    "name": ing["name"],
                    "category": ing["cat"],
                    "unit": ing["unit"],
                    "current_qty": current,
                    "min_qty": float(ing["min_qty"]),
                    "max_qty": float(ing["max_qty"]),
                    "unit_cost": ing["unit_cost"],
                }
            )


# ─── 订单 ────────────────────────────────────────────────────────────────────

async def _seed_orders(conn: AsyncConnection, dish_map: dict, store_employees: dict):
    order_count = 0
    for store in STORES:
        sid = store["id"]
        metrics = STORE_METRICS[sid]

        for day_offset in range(30):
            d = SEED_START + timedelta(days=day_offset)
            is_weekend = d.weekday() >= 5
            tables_per_day = random.randint(
                130 if is_weekend else 90,
                170 if is_weekend else 140,
            )

            orders_batch = []
            items_batch = []

            for table_idx in range(tables_per_day):
                is_dinner = table_idx >= tables_per_day * 0.4
                hour = random.randint(17, 20) if is_dinner else random.randint(11, 13)
                minute = random.randint(0, 59)
                order_dt = datetime(d.year, d.month, d.day, hour, minute)
                order_id = uuid.uuid4()
                order_number = f"XT{d.strftime('%Y%m%d')}{sid[-3:]}{table_idx+1:03d}"

                dish_codes = _pick_dishes(sid, random.randint(3, 7))
                total_yuan = 0.0
                for dish_code in dish_codes:
                    dinfo = dish_map.get(dish_code)
                    if not dinfo:
                        continue
                    qty = random.randint(1, 2)
                    price = dinfo["price_yuan"]
                    subtotal = price * qty
                    cost_fen = int(subtotal * dinfo["cost_rate"] * 100)
                    margin = round(1 - dinfo["cost_rate"], 4)
                    total_yuan += subtotal
                    items_batch.append({
                        "id": uuid.uuid4(),
                        "order_id": order_id,
                        "store_id": sid,
                        "item_id": dish_code,
                        "item_name": _dish_name(dish_code),
                        "quantity": qty,
                        "unit_price": price,
                        "subtotal": round(subtotal, 2),
                        "food_cost_actual": cost_fen,
                        "gross_margin": margin,
                    })

                if not items_batch or total_yuan == 0:
                    continue

                waiter_id = random.choice(store_employees[sid])
                channel = random.choice(["dine_in", "dine_in", "dine_in", "takeout", "delivery"])
                orders_batch.append({
                    "id": order_id,
                    "store_id": sid,
                    "order_number": order_number,
                    "table_number": f"T{random.randint(1, metrics['seats']//4):02d}",
                    "order_time": order_dt,
                    "status": "completed",
                    "total_amount": round(total_yuan, 2),
                    "payment_method": random.choice(["wechat", "alipay", "card", "cash"]),
                    "payment_status": "paid",
                    "waiter_id": waiter_id,
                    "sales_channel": channel,
                })
                order_count += 1

            # 批量插入
            if orders_batch:
                await conn.execute(
                    text("""
                        INSERT INTO orders
                            (id, store_id, order_number, table_number, order_time, status,
                             total_amount, payment_method, payment_status, waiter_id, sales_channel,
                             created_at, updated_at)
                        VALUES
                            (:id, :store_id, :order_number, :table_number, :order_time, :status,
                             :total_amount, :payment_method, :payment_status, :waiter_id, :sales_channel,
                             NOW(), NOW())
                        ON CONFLICT (id) DO NOTHING
                    """),
                    orders_batch
                )
            if items_batch:
                await conn.execute(
                    text("""
                        INSERT INTO order_items
                            (id, order_id, store_id, item_id, item_name, quantity, unit_price, subtotal,
                             food_cost_actual, gross_margin, created_at)
                        VALUES
                            (:id, :order_id, :store_id, :item_id, :item_name, :quantity, :unit_price,
                             :subtotal, :food_cost_actual, :gross_margin, NOW())
                        ON CONFLICT (id) DO NOTHING
                    """),
                    items_batch
                )

            if day_offset % 7 == 6:
                print(f"  · {sid} 第{day_offset+1}天完成，累计订单 {order_count}")


def _pick_dishes(store_id: str, n: int) -> list:
    all_codes = [f"{d['code']}_{store_id}" for d in DISHES]
    hot_set = {f"{c}_{store_id}" for c in HOT_DISHES}
    weights = [3 if c in hot_set else 1 for c in all_codes]
    chosen = random.choices(all_codes, weights=weights, k=n * 2)
    return list(dict.fromkeys(chosen))[:n]


def _dish_name(dish_code: str) -> str:
    base = dish_code.split("_")[0]  # "DISH030_XT001" → "DISH030"
    for d in DISHES:
        if d["code"] == base:
            return d["name"]
    return dish_code


# ─── 损耗事件 ────────────────────────────────────────────────────────────────

async def _seed_waste_events(conn: AsyncConnection):
    for store in STORES:
        sid = store["id"]
        for week in range(4):
            num_events = random.randint(2, 4)
            for _ in range(num_events):
                day_offset = week * 7 + random.randint(0, 6)
                event_dt = datetime(
                    *((SEED_START + timedelta(days=day_offset)).timetuple()[:3]),
                    random.randint(8, 18), random.randint(0, 59)
                )
                ing = random.choice(INGREDIENTS)
                qty = round(random.uniform(0.5, 5.0), 4)
                await conn.execute(
                    text("""
                        INSERT INTO waste_events
                            (id, event_id, store_id, ingredient_id, event_type, status,
                             quantity, unit, occurred_at, reported_by, created_at, updated_at)
                        VALUES
                            (:id, :event_id, :store_id, :ingredient_id, :event_type, 'analyzed',
                             :quantity, :unit, :occurred_at, :reported_by, NOW(), NOW())
                        ON CONFLICT (event_id) DO NOTHING
                    """),
                    {
                        "id": uuid.uuid4(),
                        "event_id": f"WE-{uuid.uuid4().hex[:8].upper()}",
                        "store_id": sid,
                        "ingredient_id": f"{ing['id']}_{sid}",
                        "event_type": random.choice(WASTE_EVENT_TYPES),
                        "quantity": qty,
                        "unit": ing["unit"],
                        "occurred_at": event_dt,
                        "reported_by": f"EMP_{sid}_01",
                    }
                )


# ─── KPI记录 ─────────────────────────────────────────────────────────────────

async def _seed_kpi_records(conn: AsyncConnection):
    kpi_defs = [
        {"id": "KPI_REVENUE",    "name": "日营业额",    "category": "revenue",    "unit": "yuan", "target": 36000.0},
        {"id": "KPI_COST_RATE",  "name": "食材成本率",  "category": "cost",       "unit": "%",    "target": 32.0,  "warning": 35.0, "critical": 38.0},
        {"id": "KPI_TABLE_TURN", "name": "翻台率",      "category": "efficiency", "unit": "次",   "target": 2.5},
        {"id": "KPI_COMPLAINT",  "name": "投诉率",      "category": "quality",    "unit": "%",    "target": 0.5,   "warning": 1.0,  "critical": 2.0},
    ]
    for kd in kpi_defs:
        r = await conn.execute(text("SELECT id FROM kpis WHERE id = :id"), {"id": kd["id"]})
        if not r.fetchone():
            await conn.execute(
                text("""
                    INSERT INTO kpis (id, name, category, unit, target_value, warning_threshold,
                                     critical_threshold, calculation_method, is_active, created_at, updated_at)
                    VALUES (:id, :name, :category, :unit, :target, :warning, :critical,
                            'daily', 'true', NOW(), NOW())
                """),
                {
                    "id": kd["id"],
                    "name": kd["name"],
                    "category": kd["category"],
                    "unit": kd["unit"],
                    "target": kd.get("target"),
                    "warning": kd.get("warning"),
                    "critical": kd.get("critical"),
                }
            )

    for store in STORES:
        sid = store["id"]
        metrics = STORE_METRICS[sid]
        seats = metrics["seats"]
        for day_offset in range(30):
            d = SEED_START + timedelta(days=day_offset)
            is_weekend = d.weekday() >= 5

            daily_revenue = random.uniform(
                38000 if is_weekend else 28000,
                58000 if is_weekend else 45000,
            )
            cost_rate = random.uniform(30.0, 37.0)
            tables = random.randint(130 if is_weekend else 90, 170 if is_weekend else 140)
            table_turn = round(tables / (seats / 4), 2)
            complaint_rate = round(random.uniform(0.0, 1.5), 2)

            records = [
                ("KPI_REVENUE",    daily_revenue, metrics["monthly_target_yuan"] / 30, False),
                ("KPI_COST_RATE",  cost_rate,     32.0,  True),
                ("KPI_TABLE_TURN", table_turn,    2.5,   False),
                ("KPI_COMPLAINT",  complaint_rate, 0.5,  True),
            ]
            batch = []
            for kpi_id, val, target, lower_is_better in records:
                if lower_is_better:
                    status = "on_track" if val <= target else (
                             "at_risk" if val <= target * 1.1 else "off_track")
                else:
                    status = "on_track" if val >= target * 0.9 else (
                             "at_risk" if val >= target * 0.75 else "off_track")
                batch.append({
                    "id": uuid.uuid4(),
                    "kpi_id": kpi_id,
                    "store_id": sid,
                    "record_date": d,
                    "value": round(val, 2),
                    "target_value": round(target, 2),
                    "achievement_rate": round(val / target, 4) if target else None,
                    "status": status,
                    "trend": random.choice(["stable", "increasing", "decreasing"]),
                })
            await conn.execute(
                text("""
                    INSERT INTO kpi_records
                        (id, kpi_id, store_id, record_date, value, target_value,
                         achievement_rate, status, trend, created_at, updated_at)
                    VALUES
                        (:id, :kpi_id, :store_id, :record_date, :value, :target_value,
                         :achievement_rate, :status, :trend, NOW(), NOW())
                    ON CONFLICT DO NOTHING
                """),
                batch
            )


# ─── 入口 ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("开始初始化闲庭食记演示数据...")
    print(f"数据库: {os.environ['DATABASE_URL']}")
    asyncio.run(seed())
