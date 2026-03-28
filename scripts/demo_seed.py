"""演示数据种子 — 三家商户各30天订单+会员+库存+菜品

为尝在一起、最黔线、尚宫厨三家商户生成差异化演示数据。
使用：python scripts/demo_seed.py
"""
import asyncio
import os
import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

TENANTS = [
    {
        "tenant_id": uuid.UUID("10000000-0000-0000-0000-000000000001"),
        "name": "尝在一起", "brand_id": "brand_czyz", "cuisine": "湘菜",
        "daily_orders": (80, 120), "avg_ticket_fen": (6000, 8000),
        "stores": [
            {"name": "尝在一起·芙蓉路店", "code": "CZYZ-FRR", "city": "长沙", "district": "芙蓉区", "seats": 80, "area": 200},
            {"name": "尝在一起·岳麓店", "code": "CZYZ-YL", "city": "长沙", "district": "岳麓区", "seats": 60, "area": 150},
        ],
        "dishes": [
            {"name": "剁椒鱼头", "price": 8800, "cost": 3200, "cat": "招牌菜"},
            {"name": "口味虾", "price": 12800, "cost": 5500, "cat": "招牌菜"},
            {"name": "毛氏红烧肉", "price": 6800, "cost": 2800, "cat": "招牌菜"},
            {"name": "臭豆腐", "price": 2800, "cost": 800, "cat": "招牌菜"},
            {"name": "农家小炒肉", "price": 4200, "cost": 1500, "cat": "热菜"},
            {"name": "辣椒炒肉", "price": 3800, "cost": 1200, "cat": "热菜"},
            {"name": "红烧茄子", "price": 2800, "cost": 600, "cat": "热菜"},
            {"name": "干锅花菜", "price": 3200, "cost": 800, "cat": "热菜"},
            {"name": "外婆菜炒蛋", "price": 2600, "cost": 500, "cat": "热菜"},
            {"name": "湘西外婆鸡", "price": 5800, "cost": 2200, "cat": "热菜"},
            {"name": "凉拌黄瓜", "price": 900, "cost": 200, "cat": "凉菜"},
            {"name": "皮蛋豆腐", "price": 1200, "cost": 400, "cat": "凉菜"},
            {"name": "口水鸡", "price": 2800, "cost": 1000, "cat": "凉菜"},
            {"name": "番茄蛋汤", "price": 1800, "cost": 400, "cat": "汤羹"},
            {"name": "酸辣汤", "price": 2200, "cost": 600, "cat": "汤羹"},
            {"name": "米饭", "price": 300, "cost": 80, "cat": "主食"},
            {"name": "蛋炒饭", "price": 1800, "cost": 500, "cat": "主食"},
            {"name": "长沙米粉", "price": 1500, "cost": 400, "cat": "主食"},
            {"name": "酸梅汤", "price": 800, "cost": 150, "cat": "饮品"},
            {"name": "鲜榨橙汁", "price": 1500, "cost": 500, "cat": "饮品"},
        ],
    },
    {
        "tenant_id": uuid.UUID("10000000-0000-0000-0000-000000000002"),
        "name": "最黔线", "brand_id": "brand_zqx", "cuisine": "贵州菜",
        "daily_orders": (50, 80), "avg_ticket_fen": (4500, 6500),
        "stores": [
            {"name": "最黔线·五一广场店", "code": "ZQX-WY", "city": "长沙", "district": "天心区", "seats": 60, "area": 160},
            {"name": "最黔线·万达店", "code": "ZQX-WD", "city": "长沙", "district": "开福区", "seats": 50, "area": 130},
        ],
        "dishes": [
            {"name": "酸汤鱼", "price": 7800, "cost": 3000, "cat": "招牌菜"},
            {"name": "苗家酸汤牛肉", "price": 6800, "cost": 2800, "cat": "招牌菜"},
            {"name": "花江狗肉", "price": 5800, "cost": 2200, "cat": "招牌菜"},
            {"name": "折耳根炒腊肉", "price": 3800, "cost": 1200, "cat": "热菜"},
            {"name": "贵州辣子鸡", "price": 4800, "cost": 1800, "cat": "热菜"},
            {"name": "糟辣脆皮鱼", "price": 4200, "cost": 1600, "cat": "热菜"},
            {"name": "黔味宫保鸡丁", "price": 3200, "cost": 1000, "cat": "热菜"},
            {"name": "素瓜豆", "price": 2200, "cost": 500, "cat": "热菜"},
            {"name": "丝娃娃", "price": 1800, "cost": 500, "cat": "凉菜"},
            {"name": "凉拌折耳根", "price": 1200, "cost": 300, "cat": "凉菜"},
            {"name": "恋爱豆腐果", "price": 1500, "cost": 400, "cat": "凉菜"},
            {"name": "酸汤肥牛", "price": 5200, "cost": 2000, "cat": "汤羹"},
            {"name": "苗家鸡汤", "price": 3800, "cost": 1200, "cat": "汤羹"},
            {"name": "糯米饭", "price": 500, "cost": 100, "cat": "主食"},
            {"name": "羊肉粉", "price": 1800, "cost": 600, "cat": "主食"},
            {"name": "肠旺面", "price": 1500, "cost": 500, "cat": "主食"},
            {"name": "刺梨汁", "price": 1000, "cost": 200, "cat": "饮品"},
            {"name": "苦荞茶", "price": 600, "cost": 100, "cat": "饮品"},
            {"name": "米酒", "price": 1200, "cost": 300, "cat": "饮品"},
            {"name": "酸汤底料（外带）", "price": 2800, "cost": 800, "cat": "招牌菜"},
        ],
    },
    {
        "tenant_id": uuid.UUID("10000000-0000-0000-0000-000000000003"),
        "name": "尚宫厨", "brand_id": "brand_sgc", "cuisine": "韩式料理",
        "daily_orders": (40, 65), "avg_ticket_fen": (3500, 5500),
        "stores": [
            {"name": "尚宫厨·步行街店", "code": "SGC-BX", "city": "长沙", "district": "天心区", "seats": 45, "area": 120},
            {"name": "尚宫厨·大学城店", "code": "SGC-DX", "city": "长沙", "district": "岳麓区", "seats": 40, "area": 100},
        ],
        "dishes": [
            {"name": "石锅拌饭", "price": 2800, "cost": 800, "cat": "招牌菜"},
            {"name": "部队锅", "price": 5800, "cost": 2000, "cat": "招牌菜"},
            {"name": "烤五花肉套餐", "price": 6800, "cost": 2500, "cat": "招牌菜"},
            {"name": "泡菜炒饭", "price": 2200, "cost": 600, "cat": "主食"},
            {"name": "冷面", "price": 1800, "cost": 500, "cat": "主食"},
            {"name": "紫菜包饭", "price": 1500, "cost": 400, "cat": "主食"},
            {"name": "辣炒年糕", "price": 2000, "cost": 500, "cat": "热菜"},
            {"name": "酱焖排骨", "price": 4200, "cost": 1600, "cat": "热菜"},
            {"name": "芝士玉米", "price": 1800, "cost": 500, "cat": "热菜"},
            {"name": "海鲜豆腐锅", "price": 3800, "cost": 1400, "cat": "汤羹"},
            {"name": "大酱汤", "price": 1500, "cost": 400, "cat": "汤羹"},
            {"name": "韩式炸鸡", "price": 3800, "cost": 1200, "cat": "招牌菜"},
            {"name": "泡菜煎饼", "price": 1800, "cost": 500, "cat": "凉菜"},
            {"name": "杂菜", "price": 2200, "cost": 600, "cat": "凉菜"},
            {"name": "蜂蜜柚子茶", "price": 1200, "cost": 300, "cat": "饮品"},
            {"name": "烧酒", "price": 2800, "cost": 800, "cat": "饮品"},
            {"name": "韩式米酒", "price": 1500, "cost": 400, "cat": "饮品"},
            {"name": "可乐", "price": 600, "cost": 150, "cat": "饮品"},
            {"name": "牛骨汤", "price": 3200, "cost": 1000, "cat": "汤羹"},
            {"name": "烤牛舌", "price": 4800, "cost": 2000, "cat": "招牌菜"},
        ],
    },
]

INGREDIENT_TEMPLATES = [
    {"name": "猪肉", "cat": "肉类", "unit": "kg", "qty": 50, "min": 10},
    {"name": "牛肉", "cat": "肉类", "unit": "kg", "qty": 30, "min": 8},
    {"name": "鸡肉", "cat": "肉类", "unit": "kg", "qty": 40, "min": 10},
    {"name": "鱼", "cat": "水产", "unit": "kg", "qty": 20, "min": 5},
    {"name": "虾", "cat": "水产", "unit": "kg", "qty": 15, "min": 5},
    {"name": "豆腐", "cat": "豆制品", "unit": "块", "qty": 100, "min": 20},
    {"name": "鸡蛋", "cat": "蛋类", "unit": "个", "qty": 200, "min": 50},
    {"name": "大米", "cat": "粮油", "unit": "kg", "qty": 100, "min": 30},
    {"name": "食用油", "cat": "粮油", "unit": "L", "qty": 30, "min": 10},
    {"name": "酱油", "cat": "调料", "unit": "瓶", "qty": 20, "min": 5},
    {"name": "醋", "cat": "调料", "unit": "瓶", "qty": 15, "min": 5},
    {"name": "盐", "cat": "调料", "unit": "袋", "qty": 30, "min": 10},
    {"name": "辣椒", "cat": "蔬菜", "unit": "kg", "qty": 25, "min": 8},
    {"name": "大蒜", "cat": "蔬菜", "unit": "kg", "qty": 15, "min": 5},
    {"name": "生姜", "cat": "蔬菜", "unit": "kg", "qty": 10, "min": 3},
    {"name": "青菜", "cat": "蔬菜", "unit": "kg", "qty": 30, "min": 10},
    {"name": "土豆", "cat": "蔬菜", "unit": "kg", "qty": 40, "min": 10},
    {"name": "番茄", "cat": "蔬菜", "unit": "kg", "qty": 20, "min": 8},
    {"name": "黄瓜", "cat": "蔬菜", "unit": "kg", "qty": 15, "min": 5},
    {"name": "花菜", "cat": "蔬菜", "unit": "kg", "qty": 20, "min": 8},
    {"name": "茄子", "cat": "蔬菜", "unit": "kg", "qty": 15, "min": 5},
    {"name": "木耳", "cat": "干货", "unit": "kg", "qty": 5, "min": 2},
    {"name": "香菇", "cat": "干货", "unit": "kg", "qty": 5, "min": 2},
    {"name": "粉丝", "cat": "干货", "unit": "包", "qty": 30, "min": 10},
    {"name": "面粉", "cat": "粮油", "unit": "kg", "qty": 30, "min": 10},
    {"name": "啤酒", "cat": "饮品", "unit": "瓶", "qty": 100, "min": 30},
    {"name": "可乐", "cat": "饮品", "unit": "罐", "qty": 80, "min": 20},
    {"name": "矿泉水", "cat": "饮品", "unit": "瓶", "qty": 100, "min": 30},
    {"name": "白糖", "cat": "调料", "unit": "kg", "qty": 10, "min": 3},
    {"name": "料酒", "cat": "调料", "unit": "瓶", "qty": 10, "min": 3},
]

SURNAMES = "张王李赵刘陈杨黄周吴徐孙胡朱高林何郭马罗梁宋郑谢韩唐冯于董萧程曹袁邓许傅沈曾彭吕苏卢蒋蔡贾丁魏薛叶阎余潘杜戴夏钟汪田任姜范方石姚谭廖邹熊金陆郝孔白崔康毛邱秦江史顾侯邵孟龙万段雷钱汤尹黎易常武乔贺赖龚文"

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://tunxiang:changeme_dev@localhost/tunxiang_os")


async def seed_all() -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    engine = create_async_engine(DATABASE_URL, echo=False)
    sf = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    print("=" * 60)
    print("屯象OS 三商户演示数据生成")
    print("=" * 60)
    for tenant in TENANTS:
        tid = tenant["tenant_id"]
        print(f"\n商户: {tenant['name']} ({tid})")
        async with sf() as session:
            await session.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tid)})
            for t in ["order_items","orders","ingredients","customers","dishes","dish_categories","stores"]:
                await session.execute(text(f"DELETE FROM {t} WHERE tenant_id = :tid"), {"tid": str(tid)})
            store_ids = []
            for s in tenant["stores"]:
                sid = uuid.uuid5(uuid.NAMESPACE_URL, f"store:{tenant['brand_id']}:{s['code']}")
                store_ids.append(sid)
                await session.execute(text("INSERT INTO stores (id,tenant_id,store_name,store_code,city,district,seats,area_sqm,brand_id,status,store_type) VALUES (:id,:tid,:name,:code,:city,:district,:seats,:area,:brand,'active','physical') ON CONFLICT (id) DO NOTHING"),
                    {"id":str(sid),"tid":str(tid),"name":s["name"],"code":s["code"],"city":s["city"],"district":s["district"],"seats":s["seats"],"area":s["area"],"brand":tenant["brand_id"]})
            print(f"  门店: {len(store_ids)}")
            dish_map = []
            for i,d in enumerate(tenant["dishes"]):
                did = uuid.uuid5(uuid.NAMESPACE_URL, f"dish:{tenant['brand_id']}:{d['name']}")
                dish_map.append({"id":did,"name":d["name"],"price":d["price"],"cost":d["cost"]})
                await session.execute(text("INSERT INTO dishes (id,tenant_id,dish_name,dish_code,price_fen,cost_fen,status,is_available,sort_order) VALUES (:id,:tid,:name,:code,:price,:cost,'active',true,:sort) ON CONFLICT (id) DO NOTHING"),
                    {"id":str(did),"tid":str(tid),"name":d["name"],"code":f"D{i+1:03d}","price":d["price"],"cost":d["cost"],"sort":i})
            print(f"  菜品: {len(dish_map)}")
            rfm_levels = ["S1"]*10+["S2"]*30+["S3"]*60+["S4"]*60+["S5"]*40
            for i in range(200):
                cid = uuid.uuid5(uuid.NAMESPACE_URL, f"customer:{tenant['brand_id']}:{i}")
                surname = random.choice(SURNAMES)
                gender = random.choice(["male","female"])
                phone = f"1{random.choice(['38','39','58','59','86','87'])}{random.randint(10000000,99999999)}"
                rfm = rfm_levels[i] if i < len(rfm_levels) else "S3"
                visits = {"S1":random.randint(20,50),"S2":random.randint(8,20),"S3":random.randint(3,8),"S4":random.randint(1,3),"S5":random.randint(0,1)}[rfm]
                total_fen = visits * random.randint(*tenant["avg_ticket_fen"])
                await session.execute(text("INSERT INTO customers (id,tenant_id,primary_phone,display_name,gender,rfm_level,total_order_count,total_order_amount_fen,source) VALUES (:id,:tid,:phone,:name,:gender,:rfm,:visits,:total,'pinzhi') ON CONFLICT (id) DO NOTHING"),
                    {"id":str(cid),"tid":str(tid),"phone":phone,"name":f"{surname}{'先生' if gender=='male' else '女士'}","gender":gender,"rfm":rfm,"visits":visits,"total":total_fen})
            print(f"  会员: 200")
            ing_count = 0
            for store_id in store_ids:
                for ing in INGREDIENT_TEMPLATES:
                    iid = uuid.uuid5(uuid.NAMESPACE_URL, f"ing:{tenant['brand_id']}:{store_id}:{ing['name']}")
                    qty = max(0, ing["qty"]+random.randint(-10,20))
                    status = "out_of_stock" if qty<=0 else ("low" if qty<=ing["min"] else "normal")
                    await session.execute(text("INSERT INTO ingredients (id,tenant_id,store_id,ingredient_name,category,unit,current_quantity,min_quantity,status) VALUES (:id,:tid,:sid,:name,:cat,:unit,:qty,:min,:status) ON CONFLICT (id) DO NOTHING"),
                        {"id":str(iid),"tid":str(tid),"sid":str(store_id),"name":ing["name"],"cat":ing["cat"],"unit":ing["unit"],"qty":qty,"min":ing["min"],"status":status})
                    ing_count += 1
            print(f"  食材: {ing_count}")
            now = datetime.now(timezone.utc)
            order_count = 0
            item_count = 0
            for day_offset in range(30,0,-1):
                day = now - timedelta(days=day_offset)
                is_weekend = day.weekday() >= 5
                for store_id in store_ids:
                    lo,hi = tenant["daily_orders"]
                    dc = int(random.randint(lo,hi) * (1.2 if is_weekend else 1.0))
                    for _ in range(dc):
                        r = random.random()
                        hour = random.randint(11,13) if r<0.4 else (random.randint(17,20) if r<0.8 else random.choice([10,14,15,16,21]))
                        otime = day.replace(hour=hour,minute=random.randint(0,59),second=random.randint(0,59))
                        oid = uuid.uuid4()
                        ono = f"TX{otime.strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:4].upper()}"
                        selected = random.sample(dish_map, min(random.randint(2,5), len(dish_map)))
                        items = []
                        subtotal = 0
                        for dish in selected:
                            qty = random.choices([1,2,3],weights=[70,25,5])[0]
                            sub = dish["price"]*qty
                            subtotal += sub
                            items.append({"did":dish["id"],"name":dish["name"],"qty":qty,"price":dish["price"],"sub":sub})
                        discount = int(subtotal*random.uniform(0.05,0.15)) if random.random()<0.2 else 0
                        final = subtotal - discount
                        await session.execute(text("INSERT INTO orders (id,tenant_id,order_no,store_id,order_type,total_amount_fen,discount_amount_fen,final_amount_fen,status,guest_count,order_time,completed_at) VALUES (:id,:tid,:no,:sid,:type,:total,:disc,:final,'completed',:guests,:otime,:ctime)"),
                            {"id":str(oid),"tid":str(tid),"no":ono,"sid":str(store_id),"type":random.choices(["dine_in","takeaway"],weights=[75,25])[0],"total":subtotal,"disc":discount,"final":final,"guests":random.randint(1,6),"otime":otime.isoformat(),"ctime":(otime+timedelta(minutes=random.randint(20,60))).isoformat()})
                        for it in items:
                            await session.execute(text("INSERT INTO order_items (id,tenant_id,order_id,dish_id,item_name,quantity,unit_price_fen,subtotal_fen) VALUES (:id,:tid,:oid,:did,:name,:qty,:price,:sub)"),
                                {"id":str(uuid.uuid4()),"tid":str(tid),"oid":str(oid),"did":str(it["did"]),"name":it["name"],"qty":it["qty"],"price":it["price"],"sub":it["sub"]})
                            item_count += 1
                        order_count += 1
            print(f"  订单: {order_count} 单, {item_count} 菜品明细")
            await session.commit()
            print(f"  ✓ {tenant['name']} 完成")
    await engine.dispose()
    print(f"\n{'='*60}\n全部完成！\n{'='*60}")


if __name__ == "__main__":
    asyncio.run(seed_all())
