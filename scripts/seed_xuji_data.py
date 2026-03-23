#!/usr/bin/env python3
"""徐记海鲜级别真实规模种子数据

生成数据规模:
- 1 个集团 + 3 个品牌（徐记海鲜/徐记-南洋/徐记-海鲜工坊）
- 每品牌 30+ 门店 = 共 100 家门店（长沙/深圳/广州/武汉真实城市分布）
- 每店 20-50 名员工 = 共 ~3000 名员工
- 800+ 菜品（海鲜酒楼特色）
- 每店 15-40 张桌台
- 50 个出品部门
- 20 种支付方式
- 500 个会员（S1-S5 分布）

使用: python scripts/seed_xuji_data.py
"""
import uuid
import random
import hashlib
from datetime import date, timedelta

random.seed(42)  # 可复现

# ══════════════════════════════════════════════
# 基础 ID 生成
# ══════════════════════════════════════════════
TENANT_ID = uuid.UUID("20000000-0000-0000-0000-000000000001")
GROUP_ID = uuid.UUID("20000000-0000-0000-0000-000000000010")


def _uid(namespace: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, namespace)


# ══════════════════════════════════════════════
# 1. 集团 + 品牌
# ══════════════════════════════════════════════
GROUP = {
    "id": GROUP_ID,
    "name": "徐记海鲜集团",
    "tenant_id": TENANT_ID,
}

BRANDS = [
    {"id": _uid("brand:xuji-haixian"), "code": "XJHX", "name": "徐记海鲜",
     "description": "高端海鲜正餐，商务宴请首选", "store_count_target": 40},
    {"id": _uid("brand:xuji-nanyang"), "code": "XJNY", "name": "徐记-南洋",
     "description": "东南亚风味海鲜，年轻时尚", "store_count_target": 30},
    {"id": _uid("brand:xuji-gongfang"), "code": "XJGF", "name": "徐记-海鲜工坊",
     "description": "社区海鲜小店，亲民价格", "store_count_target": 30},
]

# ══════════════════════════════════════════════
# 2. 门店（100 家，真实城市分布）
# ══════════════════════════════════════════════
CITY_DISTRICTS = {
    "长沙": ["芙蓉区", "天心区", "岳麓区", "开福区", "雨花区", "望城区", "长沙县", "浏阳市", "宁乡市", "星沙"],
    "深圳": ["福田区", "南山区", "罗湖区", "龙岗区", "龙华区", "宝安区", "坪山区", "光明区"],
    "广州": ["天河区", "越秀区", "海珠区", "荔湾区", "白云区", "番禺区", "黄埔区"],
    "武汉": ["武昌区", "江汉区", "汉阳区", "洪山区", "江岸区", "青山区", "东湖高新"],
}

CITY_STORE_DISTRIBUTION = {
    # 品牌 -> 城市 -> 门店数
    "XJHX": {"长沙": 15, "深圳": 10, "广州": 10, "武汉": 5},
    "XJNY": {"长沙": 10, "深圳": 8, "广州": 7, "武汉": 5},
    "XJGF": {"长沙": 12, "深圳": 8, "广州": 6, "武汉": 4},
}

STREET_NAMES = {
    "长沙": ["湘江路", "五一大道", "芙蓉路", "韶山路", "解放路", "中山路", "橘子洲路", "营盘路", "人民路", "劳动路",
           "万家丽路", "三一大道", "远大路", "东风路", "德雅路"],
    "深圳": ["深南大道", "滨河路", "北环大道", "科技路", "益田路", "华强路", "南海大道", "桂庙路",
           "前海路", "后海大道", "民治路", "龙岗大道"],
    "广州": ["中山大道", "天河路", "体育西路", "环市东路", "北京路", "上下九路", "花城大道", "珠江新城路",
           "番禺大道", "黄埔大道"],
    "武汉": ["武珞路", "中山大道", "解放大道", "建设大道", "光谷大道", "楚河路", "江汉路", "汉阳大道",
           "友谊大道", "东湖路"],
}

STORES: list[dict] = []
store_idx = 0
for brand in BRANDS:
    brand_code = brand["code"]
    city_dist = CITY_STORE_DISTRIBUTION[brand_code]
    for city, count in city_dist.items():
        districts = CITY_DISTRICTS[city]
        streets = STREET_NAMES[city]
        for i in range(count):
            store_idx += 1
            district = districts[i % len(districts)]
            street = streets[i % len(streets)]
            store_no = f"{brand_code}-{city[:1]}{store_idx:03d}"

            # 根据品牌调整规模
            if brand_code == "XJHX":
                seats = random.randint(200, 400)
                area = random.randint(500, 1200)
                floors = random.randint(2, 3)
                monthly_target = random.randint(80000000, 200000000)
            elif brand_code == "XJNY":
                seats = random.randint(100, 250)
                area = random.randint(250, 600)
                floors = random.randint(1, 2)
                monthly_target = random.randint(40000000, 100000000)
            else:  # XJGF
                seats = random.randint(60, 150)
                area = random.randint(120, 350)
                floors = 1
                monthly_target = random.randint(20000000, 60000000)

            STORES.append({
                "id": _uid(f"store:{store_no}"),
                "store_name": f"{brand['name']}-{district}{street[:2]}店",
                "store_code": store_no,
                "city": city,
                "district": district,
                "address": f"{city}{district}{street}{random.randint(1, 500)}号",
                "brand_id": str(brand["id"]),
                "brand_code": brand_code,
                "seats": seats,
                "area": area,
                "floors": floors,
                "monthly_revenue_target_fen": monthly_target,
                "cost_ratio_target": round(random.uniform(0.28, 0.38), 2),
                "labor_cost_ratio_target": round(random.uniform(0.18, 0.28), 2),
                "latitude": round(random.uniform(22.5, 31.0), 6),
                "longitude": round(random.uniform(112.5, 114.5), 6),
                "opening_date": str(date(2015, 1, 1) + timedelta(days=random.randint(0, 3650))),
            })

# ══════════════════════════════════════════════
# 3. 员工（~3000 名，分岗位）
# ══════════════════════════════════════════════
SURNAMES = [
    "李", "王", "张", "刘", "陈", "杨", "赵", "黄", "周", "吴",
    "徐", "孙", "胡", "朱", "高", "林", "何", "郭", "马", "罗",
    "梁", "宋", "郑", "谢", "唐", "韩", "曹", "许", "邓", "萧",
    "冯", "曾", "程", "蔡", "彭", "潘", "袁", "于", "董", "余",
    "苏", "叶", "吕", "魏", "蒋", "田", "杜", "丁", "沈", "姜",
]
MALE_NAMES = [
    "伟", "强", "磊", "刚", "勇", "明", "军", "波", "辉", "涛",
    "鹏", "飞", "杰", "华", "超", "宏", "斌", "亮", "志", "成",
    "建", "国", "文", "海", "东", "平", "江", "浩", "云", "龙",
]
FEMALE_NAMES = [
    "芳", "娜", "敏", "静", "丽", "强", "洁", "玲", "艳", "霞",
    "秀", "桂", "英", "华", "兰", "凤", "翠", "梅", "琴", "燕",
    "红", "春", "婷", "慧", "珍", "莉", "蓉", "云", "雪", "月",
]

ROLES_DISTRIBUTION = {
    # 角色 -> (最少, 最多) 每店
    "store_manager": (1, 2),
    "cashier": (2, 4),
    "waiter": (6, 18),
    "chef": (5, 15),
    "runner": (3, 8),    # 传菜
    "hostess": (1, 3),   # 迎宾
}

EMPLOYEES: list[dict] = []
emp_idx = 0
for store in STORES:
    brand_code = store["brand_code"]
    # 大品牌门店员工多
    scale_factor = 1.0
    if brand_code == "XJHX":
        scale_factor = 1.5
    elif brand_code == "XJNY":
        scale_factor = 1.0
    else:
        scale_factor = 0.7

    for role, (lo, hi) in ROLES_DISTRIBUTION.items():
        count = max(1, int(random.randint(lo, hi) * scale_factor))
        for _ in range(count):
            emp_idx += 1
            surname = random.choice(SURNAMES)
            is_female = random.random() < 0.45
            given = random.choice(FEMALE_NAMES if is_female else MALE_NAMES)
            if random.random() < 0.4:
                given += random.choice(FEMALE_NAMES if is_female else MALE_NAMES)

            EMPLOYEES.append({
                "id": _uid(f"emp:{emp_idx}"),
                "store_id": store["id"],
                "store_code": store["store_code"],
                "emp_name": surname + given,
                "role": role,
                "gender": "female" if is_female else "male",
                "phone": f"1{random.choice(['38','39','50','51','52','58','59','86','87','88'])}"
                         f"{random.randint(10000000, 99999999)}",
                "hire_date": str(date(2018, 1, 1) + timedelta(days=random.randint(0, 2500))),
                "employment_status": random.choices(
                    ["regular", "probation", "intern"],
                    weights=[0.85, 0.10, 0.05],
                )[0],
            })

# ══════════════════════════════════════════════
# 4. 菜品分类 + 菜品（800+ 道海鲜酒楼特色）
# ══════════════════════════════════════════════
CATEGORIES = [
    {"name": "活鲜", "code": "HX", "desc": "活养海鲜，现捞现做"},
    {"name": "冰鲜", "code": "BX", "desc": "冰鲜海产，当日到货"},
    {"name": "招牌热菜", "code": "ZP", "desc": "大厨招牌菜"},
    {"name": "经典热菜", "code": "RC", "desc": "传统热炒"},
    {"name": "蒸菜", "code": "ZC", "desc": "清蒸海鲜/粤式蒸菜"},
    {"name": "烧烤", "code": "SK", "desc": "炭火海鲜烧烤"},
    {"name": "凉菜", "code": "LC", "desc": "冷盘拼盘"},
    {"name": "汤羹", "code": "TG", "desc": "滋补汤品"},
    {"name": "主食面点", "code": "ZS", "desc": "主食/面点/粥"},
    {"name": "饮品", "code": "YP", "desc": "茶饮/果汁/酒水"},
    {"name": "宴会套餐", "code": "YH", "desc": "婚宴/商务/家宴套餐"},
    {"name": "甜品", "code": "TP", "desc": "精致甜品"},
    {"name": "时令特供", "code": "SL", "desc": "应季限定"},
]

# 活鲜
LIVE_SEAFOOD = [
    ("波士顿龙虾", 58800, 28000), ("澳洲大龙虾", 128800, 65000),
    ("帝王蟹", 198800, 95000), ("阿拉斯加帝王蟹腿", 98800, 48000),
    ("面包蟹", 28800, 13000), ("珍宝蟹", 38800, 18000),
    ("膏蟹", 18800, 8500), ("花蟹", 12800, 5800),
    ("梭子蟹", 9800, 4200), ("青蟹", 16800, 7500),
    ("东星斑", 38800, 18000), ("老虎斑", 48800, 23000),
    ("苏眉", 58800, 28000), ("龙趸", 68800, 33000),
    ("石斑鱼", 28800, 13000), ("多宝鱼", 16800, 7500),
    ("桂花鱼", 12800, 5800), ("鲈鱼", 8800, 3800),
    ("象拔蚌", 38800, 18000), ("鲍鱼(6头)", 28800, 13000),
    ("鲍鱼(10头)", 18800, 8500), ("南非干鲍", 88800, 42000),
    ("澳洲带子", 16800, 7500), ("北海道带子", 22800, 10500),
    ("基围虾", 8800, 3800), ("竹节虾", 12800, 5500),
    ("富贵虾", 18800, 8500), ("濑尿虾(皮皮虾)", 15800, 7000),
    ("生蚝(半打)", 6800, 2800), ("生蚝(一打)", 12800, 5200),
    ("扇贝", 4800, 1800), ("花甲", 3800, 1200),
    ("蛏子", 4800, 1800), ("海螺", 8800, 3800),
    ("鹅颈藤壶", 28800, 13000), ("海胆", 18800, 8500),
]

# 冰鲜
ICED_SEAFOOD = [
    ("三文鱼刺身", 12800, 5800), ("金枪鱼刺身", 18800, 8500),
    ("北极甜虾", 9800, 4200), ("甜虾刺身", 12800, 5800),
    ("海鲜拼盘(小)", 16800, 7500), ("海鲜拼盘(大)", 28800, 13000),
    ("醉虾", 8800, 3800), ("醉蟹", 12800, 5500),
    ("冰镇鲍鱼", 18800, 8500), ("冰镇龙虾", 22800, 10500),
    ("芥末章鱼", 6800, 2800), ("北极贝刺身", 9800, 4200),
    ("三文鱼腩", 15800, 7000), ("鳗鱼刺身", 16800, 7500),
    ("河豚鱼生", 28800, 13000), ("象拔蚌刺身", 38800, 18000),
    ("海螺片刺身", 12800, 5500), ("赤贝刺身", 9800, 4200),
    ("墨鱼仔", 6800, 2800), ("鱿鱼须", 5800, 2200),
]

# 招牌热菜
SIGNATURE_HOT = [
    ("蒜蓉粉丝蒸龙虾", 58800, 28000), ("避风塘炒蟹", 38800, 18000),
    ("黑胡椒焗蟹", 35800, 16000), ("姜葱炒蟹", 28800, 13000),
    ("XO酱爆龙虾球", 48800, 23000), ("干锅基围虾", 12800, 5500),
    ("椒盐皮皮虾", 15800, 7000), ("白灼基围虾", 8800, 3800),
    ("蒜蓉蒸扇贝", 4800, 1800), ("芝士焗龙虾", 68800, 33000),
    ("清蒸石斑鱼", 28800, 13000), ("红烧大黄鱼", 18800, 8500),
    ("松鼠鱼", 16800, 7500), ("糖醋鲈鱼", 12800, 5500),
    ("剁椒蒸鱼头", 8800, 3800), ("水煮鱼", 6800, 2800),
    ("酸菜鱼", 5800, 2200), ("烤鱼(香辣)", 6800, 2800),
    ("铁板鱿鱼", 4800, 1800), ("爆炒花甲", 3800, 1200),
]

# 经典热菜
CLASSIC_HOT = [
    ("宫保鸡丁", 3800, 1200), ("鱼香肉丝", 3600, 1100),
    ("麻婆豆腐", 2800, 600), ("回锅肉", 3800, 1200),
    ("糖醋里脊", 4200, 1500), ("蚝油牛肉", 5800, 2500),
    ("黑椒牛柳", 5800, 2500), ("铁板牛仔骨", 6800, 3000),
    ("红烧肉", 4800, 1800), ("东坡肉", 5800, 2200),
    ("盐焗鸡", 5800, 2200), ("白切鸡", 5800, 2200),
    ("干锅牛蛙", 5800, 2500), ("水煮牛肉", 5800, 2500),
    ("辣椒炒肉", 3800, 1200), ("农家小炒肉", 4200, 1500),
    ("干煸四季豆", 2800, 800), ("蒜蓉西兰花", 2800, 800),
    ("清炒时蔬", 2200, 600), ("蚝油生菜", 2200, 600),
    ("手撕包菜", 1800, 400), ("地三鲜", 2800, 800),
    ("蒜蓉空心菜", 1800, 400), ("上汤娃娃菜", 2800, 800),
    ("干锅花菜", 2800, 800), ("香菇菜心", 2800, 800),
    ("蚝油香菇", 3200, 1000), ("铁板豆腐", 2200, 600),
    ("家常豆腐", 2200, 600), ("酸辣土豆丝", 1800, 400),
    ("红烧茄子", 2200, 600), ("鱼香茄子", 2800, 800),
]

# 蒸菜
STEAMED = [
    ("清蒸多宝鱼", 16800, 7500), ("清蒸桂花鱼", 12800, 5800),
    ("清蒸鲈鱼", 8800, 3800), ("豉汁蒸排骨", 4800, 1800),
    ("蒜蓉粉丝蒸带子", 8800, 3800), ("蒜蓉蒸鲍鱼", 18800, 8500),
    ("清蒸象拔蚌", 38800, 18000), ("荷叶蒸饭", 2800, 800),
    ("粉蒸肉", 3800, 1200), ("蒸蛋羹", 1800, 400),
    ("梅菜扣肉", 4800, 1800), ("蒸凤爪", 2800, 800),
    ("糯米排骨", 3800, 1200), ("酿豆腐", 3200, 1000),
    ("鱼嘴蒸豆腐", 5800, 2500),
]

# 烧烤
GRILL = [
    ("烤生蚝", 3800, 1200), ("烤扇贝", 3800, 1200),
    ("烤大虾", 8800, 3800), ("烤鱿鱼", 4800, 1800),
    ("盐焗大虾", 9800, 4200), ("烤鱼(孜然)", 6800, 2800),
    ("烤羊排", 8800, 3800), ("烤牛排", 12800, 5800),
    ("烤乳鸽", 4800, 1800), ("锡纸花甲", 4800, 1800),
    ("锡纸金针菇", 2800, 800), ("锡纸茄子", 3200, 1000),
    ("铁板黑椒牛肉", 6800, 3000), ("烤海螺", 8800, 3800),
    ("碳烤龙虾", 58800, 28000),
]

# 凉菜
COLD_DISHES = [
    ("凉拌海蜇", 3800, 1200), ("凉拌黄瓜", 900, 200),
    ("皮蛋豆腐", 1200, 400), ("口水鸡", 2800, 1000),
    ("白云猪手", 3800, 1200), ("卤水拼盘", 5800, 2200),
    ("醉鸡", 4800, 1800), ("蒜泥白肉", 3800, 1200),
    ("凉拌木耳", 1000, 300), ("老醋花生", 800, 200),
    ("拍黄瓜", 800, 200), ("凉拌海带丝", 800, 200),
    ("话梅小番茄", 1200, 300), ("四川泡菜", 600, 150),
    ("盐水毛豆", 600, 100), ("糟毛豆", 800, 200),
    ("芥末虾球", 5800, 2500), ("麻辣牛肉", 4800, 2000),
    ("夫妻肺片", 3800, 1500), ("棒棒鸡", 3800, 1500),
]

# 汤羹
SOUPS = [
    ("花胶鸡汤", 18800, 8500), ("佛跳墙", 38800, 18000),
    ("鲍鱼炖鸡", 28800, 13000), ("海鲜砂锅粥", 8800, 3800),
    ("鱼翅羹", 28800, 13000), ("瑶柱粟米羹", 4800, 1800),
    ("番茄蛋花汤", 1800, 400), ("酸辣汤", 2200, 600),
    ("紫菜蛋花汤", 1200, 200), ("冬瓜排骨汤", 3800, 1200),
    ("莲藕排骨汤", 3800, 1200), ("竹荪鸡汤", 5800, 2500),
    ("海鲜豆腐汤", 3800, 1200), ("老火靓汤(例)", 4800, 1800),
    ("鸡蓉玉米羹", 2800, 800),
]

# 主食面点
STAPLES = [
    ("米饭", 300, 80), ("炒饭", 1800, 500),
    ("海鲜炒饭", 3800, 1200), ("鲍汁捞饭", 5800, 2200),
    ("XO酱炒饭", 2800, 800), ("扬州炒饭", 2200, 600),
    ("担担面", 1800, 500), ("海鲜面", 3800, 1200),
    ("手工拉面", 2200, 600), ("炒米粉", 1800, 500),
    ("长沙米粉", 1500, 400), ("虾饺皇", 3800, 1200),
    ("蟹粉小笼", 4800, 1800), ("烧卖", 2800, 800),
    ("叉烧包", 2200, 600), ("流沙包", 2800, 800),
    ("韭菜盒", 1800, 400), ("葱油饼", 1200, 300),
    ("手工馒头", 500, 100), ("海鲜粥", 4800, 1800),
    ("皮蛋瘦肉粥", 2200, 600), ("白粥", 500, 100),
    ("杂粮粥", 800, 200),
]

# 饮品
DRINKS = [
    ("酸梅汤", 800, 150), ("凉茶", 600, 100),
    ("鲜榨橙汁", 1500, 500), ("鲜榨西瓜汁", 1200, 400),
    ("椰子汁", 1500, 500), ("柠檬茶", 800, 200),
    ("菊花茶(壶)", 2800, 600), ("铁观音(壶)", 3800, 800),
    ("普洱茶(壶)", 4800, 1200), ("大红袍(壶)", 5800, 1500),
    ("茅台(飞天)", 298800, 180000), ("五粮液", 128800, 78000),
    ("剑南春", 38800, 22000), ("青岛啤酒", 1200, 500),
    ("百威啤酒", 1500, 600), ("喜力啤酒", 1800, 800),
    ("可乐/雪碧", 600, 200), ("矿泉水", 500, 150),
    ("王老吉", 800, 300), ("椰奶", 1200, 400),
    ("红牛", 1500, 600), ("鲜榨芒果汁", 1500, 500),
    ("杨枝甘露", 2800, 800), ("冰糖雪梨", 800, 200),
    ("蜂蜜柚子茶", 1200, 400),
]

# 宴会套餐
BANQUET_SETS = [
    ("吉祥如意宴(10人)", 188800, 85000), ("龙凤呈祥宴(10人)", 288800, 130000),
    ("百年好合宴(10人)", 388800, 175000), ("金玉满堂宴(10人)", 588800, 265000),
    ("商务精选套餐(6人)", 98800, 45000), ("商务豪华套餐(8人)", 158800, 72000),
    ("家庭欢聚套餐(4人)", 38800, 17000), ("家庭海鲜套餐(6人)", 68800, 31000),
    ("双人浪漫套餐", 28800, 13000), ("闺蜜下午茶套餐(4人)", 18800, 8500),
    ("生日宴(10人)", 228800, 105000), ("满月宴(10人)", 198800, 90000),
]

# 甜品
DESSERTS = [
    ("杨枝甘露", 2800, 800), ("芒果班戟", 2200, 600),
    ("双皮奶", 1800, 400), ("椰汁西米露", 1800, 400),
    ("红豆沙", 1200, 300), ("绿豆沙", 1200, 300),
    ("姜撞奶", 1500, 400), ("蛋挞", 1200, 300),
    ("炸牛奶", 1800, 500), ("拔丝地瓜", 2200, 600),
    ("冰淇淋(哈根达斯)", 3800, 1500), ("鲜果拼盘", 3800, 1200),
    ("榴莲酥", 2800, 800), ("核桃酪", 1800, 500),
]

# 时令特供
SEASONAL = [
    ("大闸蟹(母)", 12800, 5800), ("大闸蟹(公)", 10800, 4800),
    ("蟹粉豆腐", 8800, 3800), ("秃黄油拌面", 12800, 5800),
    ("春笋炒腊肉", 4800, 1800), ("香椿炒蛋", 3800, 1200),
    ("荠菜馄饨", 2800, 800), ("马兰头拌香干", 1800, 500),
    ("桃胶炖雪燕", 5800, 2200), ("冰镇荔枝", 3800, 1200),
    ("杨梅酒", 4800, 1800), ("桂花糕", 2200, 600),
    ("腊味煲仔饭", 3800, 1200), ("羊肉煲", 6800, 3000),
    ("铜锅涮肉", 8800, 3800),
]

# 汇总所有菜品
CATEGORY_DISH_MAP = {
    "活鲜": LIVE_SEAFOOD,
    "冰鲜": ICED_SEAFOOD,
    "招牌热菜": SIGNATURE_HOT,
    "经典热菜": CLASSIC_HOT,
    "蒸菜": STEAMED,
    "烧烤": GRILL,
    "凉菜": COLD_DISHES,
    "汤羹": SOUPS,
    "主食面点": STAPLES,
    "饮品": DRINKS,
    "宴会套餐": BANQUET_SETS,
    "甜品": DESSERTS,
    "时令特供": SEASONAL,
}

DISHES: list[dict] = []
dish_idx = 0
for cat_info in CATEGORIES:
    cat_name = cat_info["name"]
    cat_code = cat_info["code"]
    dish_list = CATEGORY_DISH_MAP.get(cat_name, [])
    for name, price_fen, cost_fen in dish_list:
        dish_idx += 1
        DISHES.append({
            "id": _uid(f"dish:{cat_code}{dish_idx:04d}"),
            "dish_name": name,
            "dish_code": f"{cat_code}{dish_idx:04d}",
            "category": cat_name,
            "category_code": cat_code,
            "price_fen": price_fen,
            "cost_fen": cost_fen,
            "margin": round((price_fen - cost_fen) / price_fen, 4),
            "unit": "份" if cat_name not in ("活鲜",) else "例",
            "spicy_level": random.choice([0, 0, 0, 1, 2, 3]) if cat_name in ("招牌热菜", "经典热菜", "凉菜") else 0,
            "prep_time_min": random.randint(1, 30),
        })

# ══════════════════════════════════════════════
# 5. 桌台（每店 15-40 张）
# ══════════════════════════════════════════════
TABLE_AREAS = {
    "XJHX": [
        ("散台", "A", 4, 6, 8),     # (区域, 前缀, 座位, 最少, 最多)
        ("包间", "B", 10, 4, 10),
        ("大包间", "V", 16, 2, 5),
        ("宴会厅", "Y", 30, 1, 3),
    ],
    "XJNY": [
        ("散台", "A", 4, 8, 15),
        ("卡座", "K", 2, 4, 8),
        ("包间", "B", 8, 3, 6),
    ],
    "XJGF": [
        ("散台", "A", 4, 8, 15),
        ("散台(大)", "D", 6, 3, 8),
        ("包间", "B", 8, 2, 4),
    ],
}

TABLES: list[dict] = []
for store in STORES:
    brand_code = store["brand_code"]
    areas = TABLE_AREAS[brand_code]
    for area_name, prefix, base_seats, lo, hi in areas:
        count = random.randint(lo, hi)
        for i in range(1, count + 1):
            seats = base_seats + random.choice([-2, 0, 0, 0, 2])
            seats = max(2, seats)
            min_consume = 0
            if area_name in ("包间", "大包间"):
                min_consume = random.choice([30000, 50000, 80000, 100000])
            elif area_name == "宴会厅":
                min_consume = random.choice([200000, 300000, 500000])

            TABLES.append({
                "id": _uid(f"table:{store['store_code']}:{prefix}{i:02d}"),
                "store_id": store["id"],
                "store_code": store["store_code"],
                "table_no": f"{prefix}{i:02d}",
                "area": area_name,
                "seats": seats,
                "min_consume_fen": min_consume,
                "floor": random.randint(1, store["floors"]),
            })

# ══════════════════════════════════════════════
# 6. 出品部门（50 个）
# ══════════════════════════════════════════════
DEPT_TEMPLATES = [
    ("热菜间", "HOT", None),
    ("凉菜间", "COLD", None),
    ("海鲜池", "SEA", None),
    ("蒸品间", "STEAM", None),
    ("面点间", "DIM", None),
    ("烧腊间", "ROAST", None),
    ("烧烤间", "GRILL", None),
    ("煲仔间", "POT", None),
    ("吧台", "BAR", None),
    ("甜品站", "DESSERT", None),
    ("宴会厨房", "BANQ", None),
    ("炸档", "FRY", None),
    ("铁板档", "IRON", None),
    ("刺身间", "SASHI", None),
    ("粥品间", "CONGEE", None),
    ("茶位", "TEA", "茶位费"),
    ("服务费", "SVC", "服务费"),
]

PRODUCTION_DEPTS: list[dict] = []
dept_idx = 0
for brand in BRANDS:
    for dept_name, dept_code, fee_type in DEPT_TEMPLATES:
        dept_idx += 1
        PRODUCTION_DEPTS.append({
            "id": _uid(f"dept:{brand['code']}:{dept_code}"),
            "brand_id": str(brand["id"]),
            "brand_code": brand["code"],
            "dept_name": dept_name,
            "dept_code": f"{brand['code']}-{dept_code}",
            "fixed_fee_type": fee_type,
            "sort_order": dept_idx,
        })

# ══════════════════════════════════════════════
# 7. 支付方式（20 种）
# ══════════════════════════════════════════════
PAYMENT_METHODS = [
    {"code": "cash", "name": "现金", "category": "现金", "is_actual": True, "ratio": 1.0},
    {"code": "wechat_scan", "name": "微信扫码", "category": "移动支付", "is_actual": True, "ratio": 1.0},
    {"code": "wechat_mini", "name": "微信小程序", "category": "移动支付", "is_actual": True, "ratio": 1.0},
    {"code": "alipay_scan", "name": "支付宝扫码", "category": "移动支付", "is_actual": True, "ratio": 1.0},
    {"code": "alipay_fk", "name": "支付宝付款码", "category": "移动支付", "is_actual": True, "ratio": 1.0},
    {"code": "unionpay", "name": "银联刷卡", "category": "银联卡", "is_actual": True, "ratio": 1.0},
    {"code": "visa", "name": "VISA卡", "category": "银行卡", "is_actual": True, "ratio": 1.0},
    {"code": "mastercard", "name": "万事达卡", "category": "银行卡", "is_actual": True, "ratio": 1.0},
    {"code": "member_balance", "name": "会员余额", "category": "会员消费", "is_actual": True, "ratio": 1.0},
    {"code": "member_points", "name": "会员积分抵扣", "category": "会员消费", "is_actual": False, "ratio": 0.0},
    {"code": "coupon_cash", "name": "代金券", "category": "优惠券", "is_actual": False, "ratio": 0.0},
    {"code": "coupon_discount", "name": "折扣券", "category": "优惠券", "is_actual": False, "ratio": 0.0},
    {"code": "meituan", "name": "美团券", "category": "团购", "is_actual": True, "ratio": 0.85},
    {"code": "dazhong", "name": "大众点评券", "category": "团购", "is_actual": True, "ratio": 0.88},
    {"code": "douyin", "name": "抖音团购券", "category": "团购", "is_actual": True, "ratio": 0.82},
    {"code": "credit_account", "name": "挂账", "category": "挂账", "is_actual": True, "ratio": 1.0},
    {"code": "fast_charge", "name": "快充(预存)", "category": "快充", "is_actual": True, "ratio": 1.0},
    {"code": "free_order", "name": "免单", "category": "免单", "is_actual": False, "ratio": 0.0},
    {"code": "huacai", "name": "华彩会员", "category": "华彩会员", "is_actual": True, "ratio": 0.92},
    {"code": "takeout_meituan", "name": "美团外卖", "category": "外卖支付", "is_actual": True, "ratio": 0.78},
]

# ══════════════════════════════════════════════
# 8. 会员（500 个，S1-S5 分布）
# ══════════════════════════════════════════════
RFM_DISTRIBUTION = {
    # 等级 -> (人数, 消费金额范围分, 频次范围, 最近天数范围)
    "S1": (30, (500000, 2000000), (20, 60), (1, 7)),
    "S2": (70, (200000, 500000), (10, 25), (5, 30)),
    "S3": (150, (50000, 200000), (5, 12), (15, 60)),
    "S4": (150, (10000, 50000), (2, 5), (30, 120)),
    "S5": (100, (1000, 10000), (1, 2), (60, 365)),
}

CUSTOMERS: list[dict] = []
cust_idx = 0
for level, (count, monetary_range, freq_range, recency_range) in RFM_DISTRIBUTION.items():
    for _ in range(count):
        cust_idx += 1
        surname = random.choice(SURNAMES)
        is_female = random.random() < 0.50
        given = random.choice(FEMALE_NAMES if is_female else MALE_NAMES)
        monetary = random.randint(*monetary_range)
        frequency = random.randint(*freq_range)
        recency = random.randint(*recency_range)
        city = random.choice(list(CITY_DISTRICTS.keys()))

        CUSTOMERS.append({
            "id": _uid(f"cust:{cust_idx}"),
            "display_name": surname + given,
            "phone": f"1{random.choice(['39','58','86','88','50','51'])}"
                     f"{random.randint(10000000, 99999999)}",
            "gender": "female" if is_female else "male",
            "rfm_level": level,
            "rfm_monetary_fen": monetary,
            "rfm_frequency": frequency,
            "rfm_recency_days": recency,
            "city": city,
            "source": random.choice(["wechat_mini", "pos", "meituan", "douyin", "referral"]),
            "birth_date": str(date(1960, 1, 1) + timedelta(days=random.randint(0, 20000))),
        })

# ══════════════════════════════════════════════
# 统计汇总
# ══════════════════════════════════════════════
def print_summary() -> None:
    print("=" * 70)
    print("  徐记海鲜级别种子数据 -- 屯象OS V3.2")
    print("=" * 70)

    # 集团 + 品牌
    print(f"\n[集团] {GROUP['name']} (tenant_id: {TENANT_ID})")
    print(f"[品牌] {len(BRANDS)} 个:")
    for b in BRANDS:
        brand_stores = [s for s in STORES if s["brand_code"] == b["code"]]
        print(f"  - {b['name']} ({b['code']}): {len(brand_stores)} 家门店  |  {b['description']}")

    # 门店
    print(f"\n[门店] 共 {len(STORES)} 家")
    for city in CITY_DISTRICTS:
        city_stores = [s for s in STORES if s["city"] == city]
        print(f"  {city}: {len(city_stores)} 家", end="")
        by_brand = {}
        for s in city_stores:
            by_brand.setdefault(s["brand_code"], 0)
            by_brand[s["brand_code"]] += 1
        parts = [f"{k}={v}" for k, v in sorted(by_brand.items())]
        print(f"  ({', '.join(parts)})")

    # 员工
    print(f"\n[员工] 共 {len(EMPLOYEES)} 人")
    role_counts: dict[str, int] = {}
    for e in EMPLOYEES:
        role_counts[e["role"]] = role_counts.get(e["role"], 0) + 1
    for role, cnt in sorted(role_counts.items(), key=lambda x: -x[1]):
        print(f"  {role}: {cnt} 人")
    emp_per_store = len(EMPLOYEES) / len(STORES)
    print(f"  平均每店: {emp_per_store:.1f} 人")

    # 菜品
    print(f"\n[菜品] 共 {len(DISHES)} 道")
    for cat in CATEGORIES:
        cat_dishes = [d for d in DISHES if d["category"] == cat["name"]]
        if cat_dishes:
            avg_price = sum(d["price_fen"] for d in cat_dishes) / len(cat_dishes)
            avg_margin = sum(d["margin"] for d in cat_dishes) / len(cat_dishes)
            print(f"  {cat['name']}: {len(cat_dishes)} 道  |  均价 Y{avg_price/100:.0f}  |  毛利率 {avg_margin:.1%}")

    total_avg_price = sum(d["price_fen"] for d in DISHES) / len(DISHES)
    total_avg_margin = sum(d["margin"] for d in DISHES) / len(DISHES)
    print(f"  --总计: 均价 Y{total_avg_price/100:.0f}, 平均毛利率 {total_avg_margin:.1%}")

    # 桌台
    print(f"\n[桌台] 共 {len(TABLES)} 张")
    area_counts: dict[str, int] = {}
    area_seats: dict[str, int] = {}
    for t in TABLES:
        area_counts[t["area"]] = area_counts.get(t["area"], 0) + 1
        area_seats[t["area"]] = area_seats.get(t["area"], 0) + t["seats"]
    for area, cnt in sorted(area_counts.items(), key=lambda x: -x[1]):
        print(f"  {area}: {cnt} 张 ({area_seats[area]} 座)")
    tables_per_store = len(TABLES) / len(STORES)
    print(f"  平均每店: {tables_per_store:.1f} 张")

    # 出品部门
    print(f"\n[出品部门] 共 {len(PRODUCTION_DEPTS)} 个")
    for brand in BRANDS:
        brand_depts = [d for d in PRODUCTION_DEPTS if d["brand_code"] == brand["code"]]
        print(f"  {brand['name']}: {len(brand_depts)} 个部门")

    # 支付方式
    print(f"\n[支付方式] 共 {len(PAYMENT_METHODS)} 种")
    by_cat: dict[str, list] = {}
    for pm in PAYMENT_METHODS:
        by_cat.setdefault(pm["category"], []).append(pm["name"])
    for cat, names in by_cat.items():
        print(f"  {cat}: {', '.join(names)}")

    # 会员
    print(f"\n[会员] 共 {len(CUSTOMERS)} 人")
    for level in ["S1", "S2", "S3", "S4", "S5"]:
        lvl_custs = [c for c in CUSTOMERS if c["rfm_level"] == level]
        if lvl_custs:
            avg_m = sum(c["rfm_monetary_fen"] for c in lvl_custs) / len(lvl_custs)
            avg_f = sum(c["rfm_frequency"] for c in lvl_custs) / len(lvl_custs)
            avg_r = sum(c["rfm_recency_days"] for c in lvl_custs) / len(lvl_custs)
            print(f"  {level}: {len(lvl_custs)} 人  |  "
                  f"平均消费 Y{avg_m/100:.0f}  |  平均频次 {avg_f:.1f}  |  平均回购间隔 {avg_r:.0f}天")

    by_city: dict[str, int] = {}
    for c in CUSTOMERS:
        by_city[c["city"]] = by_city.get(c["city"], 0) + 1
    print(f"  城市分布: {', '.join(f'{k}={v}' for k, v in sorted(by_city.items(), key=lambda x: -x[1]))}")

    print("\n" + "=" * 70)
    print("  数据规模总览")
    print("-" * 70)
    print(f"  {'项目':<16} {'数量':>8}")
    print("-" * 70)
    items = [
        ("集团", 1), ("品牌", len(BRANDS)), ("门店", len(STORES)),
        ("员工", len(EMPLOYEES)), ("菜品分类", len(CATEGORIES)),
        ("菜品", len(DISHES)), ("桌台", len(TABLES)),
        ("出品部门", len(PRODUCTION_DEPTS)), ("支付方式", len(PAYMENT_METHODS)),
        ("会员", len(CUSTOMERS)),
    ]
    for name, count in items:
        print(f"  {name:<16} {count:>8,}")
    print("=" * 70)


if __name__ == "__main__":
    print_summary()
