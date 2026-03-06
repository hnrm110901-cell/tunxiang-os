"""
闲庭食记演示数据种子脚本

生成10家门店30天的真实经营数据：
- 10家门店 + 每店6-8名员工
- 中式菜品菜单（30个SKU） + BOM配方
- 库存食材 + 采购记录
- 30天历史订单（每店日均100-180桌）
- 损耗事件
- KPI记录

运行：
    cd apps/api-gateway
    python scripts/seed_demo_xiantin.py
"""
import asyncio
import os
import random
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

# 必须在所有 src.* 导入前设置环境变量
for _k, _v in {
    "DATABASE_URL":          os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/zhilian"),
    "REDIS_URL":             os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    "CELERY_BROKER_URL":     os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"),
    "CELERY_RESULT_BACKEND": os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/0"),
    "SECRET_KEY":            os.getenv("SECRET_KEY", "demo-secret-key"),
    "JWT_SECRET":            os.getenv("JWT_SECRET", "demo-jwt-secret"),
}.items():
    os.environ.setdefault(_k, _v)

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.core.config import settings
from src.models.store import Store, StoreStatus
from src.models.employee import Employee
from src.models.dish import Dish, DishCategory
from src.models.inventory import InventoryItem, InventoryTransaction, TransactionType
from src.models.order import Order, OrderItem, OrderStatus
from src.models.waste_event import WasteEvent, WasteEventType, WasteEventStatus
from src.models.kpi import KPI, KPIRecord

random.seed(42)

BRAND_ID = "B001_XIANTIN"
TODAY = date(2026, 3, 6)
SEED_START = TODAY - timedelta(days=29)  # 30天数据

# ─── 门店定义 ────────────────────────────────────────────────────────────────

STORES = [
    {"id": "XT001", "code": "XT001", "name": "闲庭食记·朝阳大悦城店",   "city": "北京", "district": "朝阳区", "area": 850,  "seats": 180, "monthly_target": 1200000, "cost_target": 0.32},
    {"id": "XT002", "code": "XT002", "name": "闲庭食记·海淀五道口店",   "city": "北京", "district": "海淀区", "area": 720,  "seats": 150, "monthly_target": 1050000, "cost_target": 0.33},
    {"id": "XT003", "code": "XT003", "name": "闲庭食记·静安寺店",       "city": "上海", "district": "静安区", "area": 960,  "seats": 200, "monthly_target": 1350000, "cost_target": 0.31},
    {"id": "XT004", "code": "XT004", "name": "闲庭食记·徐汇天钥桥店",   "city": "上海", "district": "徐汇区", "area": 780,  "seats": 160, "monthly_target": 1100000, "cost_target": 0.32},
    {"id": "XT005", "code": "XT005", "name": "闲庭食记·天河正佳店",     "city": "广州", "district": "天河区", "area": 1020, "seats": 210, "monthly_target": 1150000, "cost_target": 0.33},
    {"id": "XT006", "code": "XT006", "name": "闲庭食记·南山海岸城店",   "city": "深圳", "district": "南山区", "area": 880,  "seats": 185, "monthly_target": 1250000, "cost_target": 0.32},
    {"id": "XT007", "code": "XT007", "name": "闲庭食记·锦江宾馆旁店",   "city": "成都", "district": "锦江区", "area": 650,  "seats": 140, "monthly_target":  900000, "cost_target": 0.34},
    {"id": "XT008", "code": "XT008", "name": "闲庭食记·解放碑店",       "city": "重庆", "district": "渝中区", "area": 700,  "seats": 150, "monthly_target":  950000, "cost_target": 0.34},
    {"id": "XT009", "code": "XT009", "name": "闲庭食记·湖滨银泰店",     "city": "杭州", "district": "上城区", "area": 820,  "seats": 170, "monthly_target": 1080000, "cost_target": 0.33},
    {"id": "XT010", "code": "XT010", "name": "闲庭食记·新街口德基店",   "city": "南京", "district": "玄武区", "area": 760,  "seats": 160, "monthly_target": 1000000, "cost_target": 0.33},
]

# ─── 员工职位 ────────────────────────────────────────────────────────────────

POSITIONS = ["store_manager", "chef", "sous_chef", "waiter", "cashier", "supervisor"]

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
    "齐超", "康华", "施燕", "葛涛", "邓华", "段磊", "晏颖", "祝超",
]

# ─── 菜品（30个SKU）────────────────────────────────────────────────────────

DISHES = [
    # 热菜 (price in cents)
    {"name": "宫保鸡丁",     "code": "DISH001", "cat": "热菜", "price": 5800,  "cost_rate": 0.32},
    {"name": "鱼香肉丝",     "code": "DISH002", "cat": "热菜", "price": 4800,  "cost_rate": 0.30},
    {"name": "麻婆豆腐",     "code": "DISH003", "cat": "热菜", "price": 3800,  "cost_rate": 0.28},
    {"name": "回锅肉",       "code": "DISH004", "cat": "热菜", "price": 5200,  "cost_rate": 0.35},
    {"name": "东坡肉",       "code": "DISH005", "cat": "热菜", "price": 6800,  "cost_rate": 0.38},
    {"name": "糖醋排骨",     "code": "DISH006", "cat": "热菜", "price": 6200,  "cost_rate": 0.36},
    {"name": "清蒸鲈鱼",     "code": "DISH007", "cat": "热菜", "price": 9800,  "cost_rate": 0.42},
    {"name": "蒜蓉虾",       "code": "DISH008", "cat": "热菜", "price": 8800,  "cost_rate": 0.40},
    {"name": "干煸四季豆",   "code": "DISH009", "cat": "热菜", "price": 3600,  "cost_rate": 0.25},
    {"name": "辣子鸡",       "code": "DISH010", "cat": "热菜", "price": 6800,  "cost_rate": 0.34},
    # 凉菜
    {"name": "夫妻肺片",     "code": "DISH011", "cat": "凉菜", "price": 4800,  "cost_rate": 0.30},
    {"name": "口水鸡",       "code": "DISH012", "cat": "凉菜", "price": 4200,  "cost_rate": 0.32},
    {"name": "凉拌木耳",     "code": "DISH013", "cat": "凉菜", "price": 2800,  "cost_rate": 0.22},
    {"name": "拍黄瓜",       "code": "DISH014", "cat": "凉菜", "price": 2200,  "cost_rate": 0.20},
    {"name": "花生米",       "code": "DISH015", "cat": "凉菜", "price": 1800,  "cost_rate": 0.18},
    # 主食
    {"name": "扬州炒饭",     "code": "DISH016", "cat": "主食", "price": 2800,  "cost_rate": 0.30},
    {"name": "担担面",       "code": "DISH017", "cat": "主食", "price": 2600,  "cost_rate": 0.28},
    {"name": "蛋炒饭",       "code": "DISH018", "cat": "主食", "price": 2200,  "cost_rate": 0.26},
    {"name": "葱油拌面",     "code": "DISH019", "cat": "主食", "price": 2000,  "cost_rate": 0.24},
    {"name": "酸辣汤饭",     "code": "DISH020", "cat": "主食", "price": 2400,  "cost_rate": 0.28},
    # 汤品
    {"name": "番茄蛋花汤",   "code": "DISH021", "cat": "汤品", "price": 1800,  "cost_rate": 0.22},
    {"name": "酸辣汤",       "code": "DISH022", "cat": "汤品", "price": 2200,  "cost_rate": 0.24},
    {"name": "紫菜蛋花汤",   "code": "DISH023", "cat": "汤品", "price": 1600,  "cost_rate": 0.20},
    {"name": "玉米排骨汤",   "code": "DISH024", "cat": "汤品", "price": 4800,  "cost_rate": 0.35},
    # 饮品
    {"name": "菊花茶",       "code": "DISH025", "cat": "饮品", "price": 1200,  "cost_rate": 0.15},
    {"name": "乌梅汁",       "code": "DISH026", "cat": "饮品", "price": 1400,  "cost_rate": 0.16},
    {"name": "绿茶",         "code": "DISH027", "cat": "饮品", "price": 1000,  "cost_rate": 0.14},
    # 小吃
    {"name": "锅贴",         "code": "DISH028", "cat": "小吃", "price": 3200,  "cost_rate": 0.28},
    {"name": "春卷",         "code": "DISH029", "cat": "小吃", "price": 2800,  "cost_rate": 0.26},
    {"name": "炸藕盒",       "code": "DISH030", "cat": "小吃", "price": 3600,  "cost_rate": 0.30},
]

# ─── 食材（库存）──────────────────────────────────────────────────────────────

INGREDIENTS = [
    {"id": "INV001", "name": "鸡胸肉",   "cat": "肉类",  "unit": "kg",  "unit_cost": 1800,  "min_qty": 10, "max_qty": 50},
    {"id": "INV002", "name": "猪里脊",   "cat": "肉类",  "unit": "kg",  "unit_cost": 2200,  "min_qty": 8,  "max_qty": 40},
    {"id": "INV003", "name": "猪五花",   "cat": "肉类",  "unit": "kg",  "unit_cost": 1900,  "min_qty": 8,  "max_qty": 40},
    {"id": "INV004", "name": "猪排骨",   "cat": "肉类",  "unit": "kg",  "unit_cost": 2800,  "min_qty": 5,  "max_qty": 30},
    {"id": "INV005", "name": "鲈鱼",     "cat": "水产",  "unit": "kg",  "unit_cost": 3500,  "min_qty": 5,  "max_qty": 25},
    {"id": "INV006", "name": "大虾",     "cat": "水产",  "unit": "kg",  "unit_cost": 4800,  "min_qty": 5,  "max_qty": 25},
    {"id": "INV007", "name": "豆腐",     "cat": "豆制品","unit": "kg",  "unit_cost":  400,  "min_qty": 15, "max_qty": 60},
    {"id": "INV008", "name": "四季豆",   "cat": "蔬菜",  "unit": "kg",  "unit_cost":  600,  "min_qty": 8,  "max_qty": 40},
    {"id": "INV009", "name": "黄瓜",     "cat": "蔬菜",  "unit": "kg",  "unit_cost":  380,  "min_qty": 8,  "max_qty": 40},
    {"id": "INV010", "name": "番茄",     "cat": "蔬菜",  "unit": "kg",  "unit_cost":  450,  "min_qty": 10, "max_qty": 50},
    {"id": "INV011", "name": "大米",     "cat": "主食",  "unit": "kg",  "unit_cost":  350,  "min_qty": 30, "max_qty":120},
    {"id": "INV012", "name": "面条",     "cat": "主食",  "unit": "kg",  "unit_cost":  280,  "min_qty": 15, "max_qty": 60},
    {"id": "INV013", "name": "食用油",   "cat": "调料",  "unit": "L",   "unit_cost":  900,  "min_qty": 10, "max_qty": 40},
    {"id": "INV014", "name": "黑木耳（干）","cat": "干货", "unit": "kg", "unit_cost": 2400,  "min_qty": 3,  "max_qty": 15},
    {"id": "INV015", "name": "花生米",   "cat": "干货",  "unit": "kg",  "unit_cost":  800,  "min_qty": 5,  "max_qty": 25},
    {"id": "INV016", "name": "鸡蛋",     "cat": "蛋类",  "unit": "个",  "unit_cost":   80,  "min_qty": 60, "max_qty":200},
    {"id": "INV017", "name": "葱",       "cat": "调料",  "unit": "kg",  "unit_cost":  280,  "min_qty": 5,  "max_qty": 20},
    {"id": "INV018", "name": "姜",       "cat": "调料",  "unit": "kg",  "unit_cost":  350,  "min_qty": 3,  "max_qty": 15},
    {"id": "INV019", "name": "蒜",       "cat": "调料",  "unit": "kg",  "unit_cost":  450,  "min_qty": 3,  "max_qty": 15},
    {"id": "INV020", "name": "干辣椒",   "cat": "调料",  "unit": "kg",  "unit_cost": 1200,  "min_qty": 2,  "max_qty": 10},
]

# 热门菜品（每桌更高概率点单）
HOT_DISHES = ["DISH001", "DISH003", "DISH004", "DISH007", "DISH010", "DISH016"]


# ─── 主函数 ──────────────────────────────────────────────────────────────────

async def seed():
    db_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(db_url, echo=False)
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_maker() as db:
        await _seed_stores(db)
        await db.commit()
        print("✓ 门店创建完成")

        store_employees = await _seed_employees(db)
        await db.commit()
        print("✓ 员工创建完成")

        dish_map, cat_map = await _seed_dishes(db)
        await db.commit()
        print("✓ 菜品创建完成")

        await _seed_inventory(db)
        await db.commit()
        print("✓ 库存创建完成")

        await _seed_orders(db, dish_map, store_employees)
        await db.commit()
        print("✓ 订单创建完成（30天）")

        await _seed_waste_events(db)
        await db.commit()
        print("✓ 损耗事件创建完成")

        await _seed_kpi_records(db)
        await db.commit()
        print("✓ KPI记录创建完成")

    await engine.dispose()
    print("\n演示数据初始化完成！")
    print(f"10家门店 | 30天数据 ({SEED_START} → {TODAY})")


# ─── 门店 ────────────────────────────────────────────────────────────────────

async def _seed_stores(db: AsyncSession):
    for s in STORES:
        existing = await db.get(Store, s["id"])
        if existing:
            continue
        store = Store(
            id=s["id"],
            code=s["code"],
            name=s["name"],
            brand_id=BRAND_ID,
            city=s["city"],
            district=s["district"],
            area=float(s["area"]),
            seats=s["seats"],
            status=StoreStatus.ACTIVE.value,
            is_active=True,
            region="华东" if s["city"] in ("上海", "杭州", "南京") else
                   "华南" if s["city"] in ("广州", "深圳") else
                   "西南" if s["city"] in ("成都", "重庆") else "华北",
            monthly_revenue_target=Decimal(s["monthly_target"]) / 100,  # 转换为元
            cost_ratio_target=s["cost_target"],
            labor_cost_ratio_target=0.22,
            daily_customer_target=s["seats"] * 2,
            opening_date="2023-06-01",
            business_hours={"weekday": "11:00-22:00", "weekend": "10:30-22:30"},
        )
        db.add(store)


# ─── 员工 ────────────────────────────────────────────────────────────────────

async def _seed_employees(db: AsyncSession) -> dict:
    """返回 {store_id: [employee_id, ...]} 映射"""
    store_employees = {}
    name_pool = list(EMPLOYEE_NAMES)
    random.shuffle(name_pool)
    name_idx = 0

    for store in STORES:
        sid = store["id"]
        store_employees[sid] = []
        # 每店: 1店长 + 2厨师 + 3-4服务员 + 1收银
        positions = ["store_manager", "chef", "sous_chef", "waiter", "waiter", "waiter", "cashier"]
        for i, pos in enumerate(positions):
            eid = f"EMP_{sid}_{i+1:02d}"
            existing = await db.get(Employee, eid)
            if existing:
                store_employees[sid].append(eid)
                continue
            emp = Employee(
                id=eid,
                store_id=sid,
                name=name_pool[name_idx % len(name_pool)],
                position=pos,
                skills=[pos],
                is_active=True,
                hire_date=date(2023, 6, 1),
                performance_score="85",
            )
            db.add(emp)
            store_employees[sid].append(eid)
            name_idx += 1

    return store_employees


# ─── 菜品 ────────────────────────────────────────────────────────────────────

async def _seed_dishes(db: AsyncSession) -> tuple:
    """返回 (dish_map={code: dish_id_uuid}, cat_map={cat_name: cat_id})"""
    categories = ["热菜", "凉菜", "主食", "汤品", "饮品", "小吃"]
    cat_map = {}

    # 每家店创建相同分类和菜品
    for store in STORES:
        sid = store["id"]
        for cat_name in categories:
            # 检查是否已存在（用 name+store_id）
            from sqlalchemy import select
            r = await db.execute(
                select(DishCategory).where(
                    DishCategory.store_id == sid,
                    DishCategory.name == cat_name,
                )
            )
            existing_cat = r.scalar_one_or_none()
            if existing_cat:
                cat_map[f"{sid}_{cat_name}"] = existing_cat.id
            else:
                cat_id = uuid.uuid4()
                cat = DishCategory(
                    id=cat_id,
                    store_id=sid,
                    name=cat_name,
                    code=f"CAT_{cat_name}_{sid}",
                    is_active=True,
                )
                db.add(cat)
                cat_map[f"{sid}_{cat_name}"] = cat_id

    await db.flush()

    dish_map = {}
    for store in STORES:
        sid = store["id"]
        for d in DISHES:
            code = f"{d['code']}_{sid}"
            from sqlalchemy import select
            r = await db.execute(select(Dish).where(Dish.code == code))
            existing_dish = r.scalar_one_or_none()
            if existing_dish:
                dish_map[code] = {
                    "id": existing_dish.id,
                    "price": int(existing_dish.price * 100),
                    "cost_rate": d["cost_rate"],
                }
                continue

            dish_id = uuid.uuid4()
            # 门店差异化定价 ±5%，四舍五入到整元（100分）
            price_factor = random.uniform(0.95, 1.05)
            price_cents = int(round(d["price"] * price_factor / 100) * 100)
            dish = Dish(
                id=dish_id,
                store_id=sid,
                name=d["name"],
                code=code,
                category_id=cat_map.get(f"{sid}_{d['cat']}"),
                price=Decimal(price_cents) / 100,
                is_available=True,
            )
            db.add(dish)
            dish_map[code] = {
                "id": dish_id,
                "price": price_cents,
                "cost_rate": d["cost_rate"],
            }

    return dish_map, cat_map


# ─── 库存 ────────────────────────────────────────────────────────────────────

async def _seed_inventory(db: AsyncSession):
    for store in STORES:
        sid = store["id"]
        for ing in INGREDIENTS:
            iid = f"{ing['id']}_{sid}"
            existing = await db.get(InventoryItem, iid)
            if existing:
                continue
            current = random.uniform(ing["min_qty"] * 1.5, ing["max_qty"] * 0.8)
            item = InventoryItem(
                id=iid,
                store_id=sid,
                name=ing["name"],
                category=ing["cat"],
                unit=ing["unit"],
                current_quantity=round(current, 2),
                min_quantity=float(ing["min_qty"]),
                max_quantity=float(ing["max_qty"]),
                unit_cost=ing["unit_cost"],
                supplier_name="奥琦玮供应链",
                supplier_contact="400-888-0001",
            )
            db.add(item)


# ─── 订单 ────────────────────────────────────────────────────────────────────

async def _seed_orders(db: AsyncSession, dish_map: dict, store_employees: dict):
    order_count = 0
    for store in STORES:
        sid = store["id"]
        waiters = [e for e in store_employees[sid] if "waiter" in e or True]

        for day_offset in range(30):
            d = SEED_START + timedelta(days=day_offset)
            is_weekend = d.weekday() >= 5

            # 日均桌数：工作日100-140，周末150-180
            tables_per_day = random.randint(130 if is_weekend else 90,
                                            180 if is_weekend else 140)

            # 午餐和晚餐分布
            for table_idx in range(tables_per_day):
                is_dinner = table_idx >= tables_per_day * 0.4
                hour = random.randint(17, 20) if is_dinner else random.randint(11, 13)
                minute = random.randint(0, 59)
                order_dt = datetime(d.year, d.month, d.day, hour, minute)

                order_id = f"ORD_{d.strftime('%Y%m%d')}_{sid}_{table_idx+1:03d}"

                # 每桌点3-7道菜
                num_dishes = random.randint(3, 7)
                dish_codes = _pick_dishes(sid, num_dishes)

                total_amount = 0
                items_data = []
                for dish_code in dish_codes:
                    dinfo = dish_map.get(dish_code)
                    if not dinfo:
                        continue
                    qty = random.randint(1, 2)
                    price = dinfo["price"]
                    subtotal = price * qty
                    cost = int(subtotal * dinfo["cost_rate"])
                    margin = round(1 - dinfo["cost_rate"], 4)
                    total_amount += subtotal
                    items_data.append({
                        "item_id": dish_code,
                        "item_name": _dish_name_from_code(dish_code),
                        "quantity": qty,
                        "unit_price": price,
                        "subtotal": subtotal,
                        "food_cost_actual": cost,
                        "gross_margin": Decimal(str(margin)),
                    })

                if not items_data:
                    continue

                # 轻微折扣（会员/优惠）
                discount = int(total_amount * random.choice([0, 0, 0, 0.05, 0.1]))
                final_amount = total_amount - discount

                waiter_id = random.choice(store_employees[sid])
                channel = random.choice(["dine_in", "dine_in", "dine_in", "takeout", "delivery"])

                order = Order(
                    id=order_id,
                    store_id=sid,
                    table_number=f"T{random.randint(1, store['seats']//4):02d}",
                    status=OrderStatus.COMPLETED.value,
                    total_amount=total_amount,
                    discount_amount=discount,
                    final_amount=final_amount,
                    order_time=order_dt,
                    confirmed_at=order_dt + timedelta(minutes=2),
                    completed_at=order_dt + timedelta(minutes=random.randint(45, 90)),
                    waiter_id=waiter_id,
                    sales_channel=channel,
                )
                db.add(order)

                for item_data in items_data:
                    oi = OrderItem(
                        id=uuid.uuid4(),
                        order_id=order_id,
                        **item_data,
                    )
                    db.add(oi)

                order_count += 1

            # 每日批量提交避免内存溢出
            if day_offset % 5 == 4:
                await db.flush()
                print(f"  · {sid} {d} 已处理，累计订单 {order_count}")


def _pick_dishes(store_id: str, n: int) -> list:
    """按热门度加权随机选菜"""
    all_codes = [f"{d['code']}_{store_id}" for d in DISHES]
    hot_codes = [f"{c}_{store_id}" for c in HOT_DISHES]
    weights = [3 if c in hot_codes else 1 for c in all_codes]
    chosen = random.choices(all_codes, weights=weights, k=n * 2)
    return list(dict.fromkeys(chosen))[:n]  # 去重，取前n个


def _dish_name_from_code(dish_code: str) -> str:
    base_code = dish_code.split("_")[0] + "_" + dish_code.split("_")[1]
    for d in DISHES:
        if d["code"] == base_code:
            return d["name"]
    return dish_code


# ─── 损耗事件 ────────────────────────────────────────────────────────────────

async def _seed_waste_events(db: AsyncSession):
    waste_types = list(WasteEventType)
    for store in STORES:
        sid = store["id"]
        # 每店每周2-4次损耗事件
        for week in range(4):
            num_events = random.randint(2, 4)
            for _ in range(num_events):
                day_offset = week * 7 + random.randint(0, 6)
                event_dt = datetime(
                    *((SEED_START + timedelta(days=day_offset)).timetuple()[:3]),
                    random.randint(8, 18), random.randint(0, 59)
                )
                ing = random.choice(INGREDIENTS)
                qty = round(random.uniform(0.5, 5.0), 2)
                cost_fen = int(qty * ing["unit_cost"])

                event = WasteEvent(
                    id=uuid.uuid4(),
                    event_id=f"WE-{uuid.uuid4().hex[:8].upper()}",
                    store_id=sid,
                    ingredient_id=f"{ing['id']}_{sid}",
                    event_type=random.choice(waste_types),
                    quantity=Decimal(str(qty)),
                    unit=ing["unit"],
                    occurred_at=event_dt,
                    status=WasteEventStatus.ANALYZED,
                    reported_by=f"EMP_{sid}_01",
                    notes=f"{ing['name']} 损耗 {qty}{ing['unit']}，成本约¥{cost_fen/100:.1f}",
                )
                db.add(event)


# ─── KPI记录 ─────────────────────────────────────────────────────────────────

async def _seed_kpi_records(db: AsyncSession):
    # 确保KPI定义存在
    kpi_defs = [
        {"id": "KPI_REVENUE", "name": "日营业额", "category": "revenue", "unit": "yuan", "target": 36000.0},
        {"id": "KPI_COST_RATE", "name": "食材成本率", "category": "cost", "unit": "%", "target": 32.0, "warning": 35.0, "critical": 38.0},
        {"id": "KPI_TABLE_TURN", "name": "翻台率", "category": "efficiency", "unit": "次", "target": 2.5},
        {"id": "KPI_COMPLAINT", "name": "投诉率", "category": "quality", "unit": "%", "target": 0.5, "warning": 1.0, "critical": 2.0},
    ]
    for kd in kpi_defs:
        existing = await db.get(KPI, kd["id"])
        if not existing:
            kpi = KPI(
                id=kd["id"],
                name=kd["name"],
                category=kd["category"],
                unit=kd["unit"],
                target_value=kd.get("target"),
                warning_threshold=kd.get("warning"),
                critical_threshold=kd.get("critical"),
                calculation_method="daily",
                is_active="true",
            )
            db.add(kpi)
    await db.flush()

    # 每店每天写KPI记录
    for store in STORES:
        sid = store["id"]
        seats = store["seats"]
        for day_offset in range(30):
            d = SEED_START + timedelta(days=day_offset)
            is_weekend = d.weekday() >= 5

            # 模拟真实波动
            daily_revenue = random.uniform(
                28000 if not is_weekend else 38000,
                45000 if not is_weekend else 58000,
            )
            cost_rate = random.uniform(30.0, 37.0)
            tables = random.randint(90 if not is_weekend else 130,
                                    140 if not is_weekend else 180)
            table_turn = round(tables / (seats / 4), 2)
            complaint_rate = round(random.uniform(0.0, 1.5), 2)

            records = [
                ("KPI_REVENUE", daily_revenue, store["monthly_target"] / 30 / 100, False),
                ("KPI_COST_RATE", cost_rate, 32.0, True),   # lower is better
                ("KPI_TABLE_TURN", table_turn, 2.5, False),
                ("KPI_COMPLAINT", complaint_rate, 0.5, True),  # lower is better
            ]
            for kpi_id, val, target, lower_is_better in records:
                if lower_is_better:
                    status = "on_track" if val <= target else \
                             "at_risk" if val <= target * 1.1 else "off_track"
                else:
                    status = "on_track" if val >= target * 0.9 else \
                             "at_risk" if val >= target * 0.75 else "off_track"
                rec = KPIRecord(
                    id=uuid.uuid4(),
                    kpi_id=kpi_id,
                    store_id=sid,
                    record_date=d,
                    value=round(val, 2),
                    target_value=round(target, 2),
                    achievement_rate=round(val / target, 4) if target else None,
                    status=status,
                    trend=random.choice(["stable", "increasing", "decreasing"]),
                )
                db.add(rec)


# ─── 入口 ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("开始初始化闲庭食记演示数据...")
    print(f"数据库: {os.environ['DATABASE_URL']}")
    asyncio.run(seed())
