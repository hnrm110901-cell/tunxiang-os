"""种子数据 — 演示用（尝在一起·芙蓉路店）

创建完整的门店运营数据集：
- 1 个品牌 + 2 家门店
- 6 个分类 + 24 道菜品（含 BOM）
- 10 名员工
- 12 张桌台
- 示例顾客

使用：python scripts/seed_demo_data.py
"""
import asyncio
import uuid
import os

TENANT_ID = uuid.UUID("10000000-0000-0000-0000-000000000001")
BRAND_ID = "brand_czyz"

# ─── 门店 ───
STORES = [
    {"id": uuid.uuid5(uuid.NAMESPACE_URL, "store:czyz-frr"), "store_name": "尝在一起·芙蓉路店", "store_code": "CZYZ-FRR",
     "city": "长沙", "district": "芙蓉区", "seats": 80, "area": 200, "brand_id": BRAND_ID,
     "monthly_revenue_target_fen": 30000000, "cost_ratio_target": 0.32, "labor_cost_ratio_target": 0.25},
    {"id": uuid.uuid5(uuid.NAMESPACE_URL, "store:czyz-yl"), "store_name": "尝在一起·岳麓店", "store_code": "CZYZ-YL",
     "city": "长沙", "district": "岳麓区", "seats": 60, "area": 150, "brand_id": BRAND_ID,
     "monthly_revenue_target_fen": 25000000, "cost_ratio_target": 0.33, "labor_cost_ratio_target": 0.26},
]

# ─── 菜品分类 ───
CATEGORIES = ["招牌菜", "热菜", "凉菜", "汤羹", "主食", "饮品"]

# ─── 菜品（尝在一起特色湘菜） ───
DISHES = [
    # 招牌菜
    {"name": "剁椒鱼头", "code": "ZP001", "price": 8800, "cost": 3200, "cat": "招牌菜", "station": "热菜档", "prep": 18},
    {"name": "口味虾", "code": "ZP002", "price": 12800, "cost": 5500, "cat": "招牌菜", "station": "热菜档", "prep": 15},
    {"name": "毛氏红烧肉", "code": "ZP003", "price": 6800, "cost": 2800, "cat": "招牌菜", "station": "热菜档", "prep": 25},
    {"name": "臭豆腐", "code": "ZP004", "price": 2800, "cost": 800, "cat": "招牌菜", "station": "炸档", "prep": 8},
    # 热菜
    {"name": "农家小炒肉", "code": "RC001", "price": 4200, "cost": 1500, "cat": "热菜", "station": "热菜档", "prep": 10},
    {"name": "辣椒炒肉", "code": "RC002", "price": 3800, "cost": 1200, "cat": "热菜", "station": "热菜档", "prep": 8},
    {"name": "红烧茄子", "code": "RC003", "price": 2800, "cost": 600, "cat": "热菜", "station": "热菜档", "prep": 12},
    {"name": "干锅花菜", "code": "RC004", "price": 3200, "cost": 800, "cat": "热菜", "station": "热菜档", "prep": 10},
    {"name": "外婆菜炒蛋", "code": "RC005", "price": 2600, "cost": 500, "cat": "热菜", "station": "热菜档", "prep": 6},
    {"name": "湘西外婆鸡", "code": "RC006", "price": 5800, "cost": 2200, "cat": "热菜", "station": "热菜档", "prep": 20},
    # 凉菜
    {"name": "凉拌黄瓜", "code": "LC001", "price": 900, "cost": 200, "cat": "凉菜", "station": "凉菜档", "prep": 3},
    {"name": "皮蛋豆腐", "code": "LC002", "price": 1200, "cost": 400, "cat": "凉菜", "station": "凉菜档", "prep": 3},
    {"name": "口水鸡", "code": "LC003", "price": 2800, "cost": 1000, "cat": "凉菜", "station": "凉菜档", "prep": 5},
    {"name": "凉拌木耳", "code": "LC004", "price": 1000, "cost": 300, "cat": "凉菜", "station": "凉菜档", "prep": 3},
    # 汤羹
    {"name": "番茄蛋汤", "code": "TG001", "price": 1800, "cost": 400, "cat": "汤羹", "station": "热菜档", "prep": 8},
    {"name": "酸辣汤", "code": "TG002", "price": 2200, "cost": 600, "cat": "汤羹", "station": "热菜档", "prep": 10},
    {"name": "紫菜蛋花汤", "code": "TG003", "price": 1200, "cost": 200, "cat": "汤羹", "station": "热菜档", "prep": 5},
    # 主食
    {"name": "米饭", "code": "ZS001", "price": 300, "cost": 80, "cat": "主食", "station": "default", "prep": 1},
    {"name": "蛋炒饭", "code": "ZS002", "price": 1800, "cost": 500, "cat": "主食", "station": "炒档", "prep": 5},
    {"name": "长沙米粉", "code": "ZS003", "price": 1500, "cost": 400, "cat": "主食", "station": "面档", "prep": 5},
    {"name": "手工馒头", "code": "ZS004", "price": 500, "cost": 100, "cat": "主食", "station": "面档", "prep": 2},
    # 饮品
    {"name": "酸梅汤", "code": "YP001", "price": 800, "cost": 150, "cat": "饮品", "station": "default", "prep": 1},
    {"name": "凉茶", "code": "YP002", "price": 600, "cost": 100, "cat": "饮品", "station": "default", "prep": 1},
    {"name": "鲜榨橙汁", "code": "YP003", "price": 1500, "cost": 500, "cat": "饮品", "station": "default", "prep": 3},
]

# ─── 员工 ───
EMPLOYEES = [
    {"name": "张明华", "role": "manager", "phone": "138****0001"},
    {"name": "李翠花", "role": "cashier", "phone": "138****0002"},
    {"name": "王大厨", "role": "chef", "phone": "138****0003"},
    {"name": "赵师傅", "role": "chef", "phone": "138****0004"},
    {"name": "刘小妹", "role": "waiter", "phone": "138****0005"},
    {"name": "陈小弟", "role": "waiter", "phone": "138****0006"},
    {"name": "周阿姨", "role": "waiter", "phone": "138****0007"},
    {"name": "吴师傅", "role": "chef", "phone": "138****0008"},
    {"name": "郑小华", "role": "waiter", "phone": "138****0009"},
    {"name": "孙经理", "role": "manager", "phone": "138****0010"},
]

# ─── 桌台 ───
TABLES = [
    *[{"no": f"A{i:02d}", "seats": 4, "area": "大厅"} for i in range(1, 7)],
    *[{"no": f"B{i:02d}", "seats": s, "area": "包间"} for i, s in [(1, 8), (2, 10), (3, 12)]],
    *[{"no": f"C{i:02d}", "seats": 6, "area": "露台"} for i in range(1, 4)],
]

# ─── 顾客 ───
CUSTOMERS = [
    {"phone": "139****1001", "name": "张总", "rfm": "S1", "monetary": 120000, "frequency": 24, "recency": 3},
    {"phone": "139****1002", "name": "李经理", "rfm": "S2", "monetary": 50000, "frequency": 10, "recency": 15},
    {"phone": "139****1003", "name": "王女士", "rfm": "S3", "monetary": 20000, "frequency": 5, "recency": 45},
    {"phone": "139****1004", "name": "赵先生", "rfm": "S4", "monetary": 8000, "frequency": 2, "recency": 90},
    {"phone": "139****1005", "name": "刘小姐", "rfm": "S5", "monetary": 3000, "frequency": 1, "recency": 180},
]


def print_summary():
    """打印种子数据摘要"""
    print("=" * 50)
    print("屯象OS V3.0 演示种子数据")
    print("=" * 50)
    print(f"品牌: 尝在一起 ({BRAND_ID})")
    print(f"门店: {len(STORES)} 家")
    for s in STORES:
        print(f"  - {s['store_name']} ({s['store_code']}) {s['seats']}座")
    print(f"分类: {len(CATEGORIES)} 个 ({', '.join(CATEGORIES)})")
    print(f"菜品: {len(DISHES)} 道")
    for cat in CATEGORIES:
        count = sum(1 for d in DISHES if d["cat"] == cat)
        print(f"  - {cat}: {count} 道")
    print(f"员工: {len(EMPLOYEES)} 人")
    for role in ["manager", "chef", "waiter", "cashier"]:
        count = sum(1 for e in EMPLOYEES if e["role"] == role)
        print(f"  - {role}: {count} 人")
    print(f"桌台: {len(TABLES)} 张")
    for area in ["大厅", "包间", "露台"]:
        count = sum(1 for t in TABLES if t["area"] == area)
        print(f"  - {area}: {count} 张")
    print(f"顾客: {len(CUSTOMERS)} 人 (S1-S5 各1人)")
    print(f"\n租户ID: {TENANT_ID}")

    # 菜品统计
    total_items = len(DISHES)
    avg_price = sum(d["price"] for d in DISHES) / total_items
    avg_margin = sum((d["price"] - d["cost"]) / d["price"] for d in DISHES) / total_items
    print(f"\n菜品均价: ¥{avg_price/100:.0f}")
    print(f"平均毛利率: {avg_margin:.1%}")
    print("=" * 50)


if __name__ == "__main__":
    print_summary()
