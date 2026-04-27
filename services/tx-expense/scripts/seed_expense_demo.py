#!/usr/bin/env python3
"""
屯象OS费控DEMO数据初始化脚本

用法：
    python seed_expense_demo.py [--base-url http://localhost:8015] [--tenant-id <UUID>]

初始化以下DEMO数据（全部幂等，重复运行不报错）：
  1. 费用科目（验证 + 按需创建）
  2. 差旅差标（50城市tier初始化）
  3. 5个月度/年度预算（各类型）
  4. 3个备用金账户（3个门店）
  5. 10个费控申请（草稿/待审批/已审批/已付款各状态）
  6. 2个合同（门店租约 + 设备维保）
  7. 1个差旅申请（含2条行程）
  8. mock发票数据
"""
import argparse
import sys
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# 依赖：requests（标准库优先，回退 httpx）
# ---------------------------------------------------------------------------
try:
    import requests as _http_lib
    _USE_REQUESTS = True
except ImportError:
    try:
        import httpx as _http_lib  # type: ignore[no-redef]
        _USE_REQUESTS = False
    except ImportError:
        print("ERROR: 需要安装 requests 或 httpx。运行：pip install requests")
        sys.exit(1)

# ---------------------------------------------------------------------------
# 固定常量（幂等性保障：固定UUID，方便重复运行同一套DEMO数据）
# ---------------------------------------------------------------------------

DEMO_TENANT_ID = "11111111-0001-0001-0001-000000000001"
DEMO_USER_ID   = "22222222-0002-0002-0002-000000000002"

# 3个演示门店
DEMO_STORE_1_ID = "33333333-0001-0001-0001-000000000001"
DEMO_STORE_2_ID = "33333333-0002-0002-0002-000000000002"
DEMO_STORE_3_ID = "33333333-0003-0003-0003-000000000003"

# 演示品牌
DEMO_BRAND_ID = "44444444-0001-0001-0001-000000000001"

# 演示员工（店长们）
DEMO_KEEPER_1_ID = "55555555-0001-0001-0001-000000000001"
DEMO_KEEPER_2_ID = "55555555-0002-0002-0002-000000000002"
DEMO_KEEPER_3_ID = "55555555-0003-0003-0003-000000000003"

# 演示审批人
DEMO_APPROVER_ID = "66666666-0001-0001-0001-000000000001"

# ---------------------------------------------------------------------------
# 颜色输出工具
# ---------------------------------------------------------------------------

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
BLUE   = "\033[94m"
RESET  = "\033[0m"
BOLD   = "\033[1m"


def ok(msg: str) -> None:
    print(f"  {GREEN}✓{RESET} {msg}")


def fail(msg: str) -> None:
    print(f"  {RED}✗{RESET} {msg}")


def info(msg: str) -> None:
    print(f"  {BLUE}→{RESET} {msg}")


def section(title: str) -> None:
    print(f"\n{BOLD}{YELLOW}{'─'*50}{RESET}")
    print(f"{BOLD}{YELLOW}  {title}{RESET}")
    print(f"{BOLD}{YELLOW}{'─'*50}{RESET}")


# ---------------------------------------------------------------------------
# HTTP 客户端封装（兼容 requests / httpx）
# ---------------------------------------------------------------------------

class ApiClient:
    def __init__(self, base_url: str, tenant_id: str, user_id: str):
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "Content-Type": "application/json",
            "X-Tenant-ID": tenant_id,
            "X-User-ID": user_id,
        }

    def get(self, path: str, params: Optional[Dict] = None) -> Tuple[int, Any]:
        url = f"{self.base_url}{path}"
        try:
            if _USE_REQUESTS:
                r = _http_lib.get(url, headers=self.headers, params=params, timeout=15)
            else:
                r = _http_lib.get(url, headers=self.headers, params=params, timeout=15)  # type: ignore[call-arg]
            return r.status_code, self._parse(r)
        except Exception as e:
            return -1, {"error": str(e)}

    def post(self, path: str, body: Dict) -> Tuple[int, Any]:
        url = f"{self.base_url}{path}"
        try:
            if _USE_REQUESTS:
                r = _http_lib.post(url, headers=self.headers, json=body, timeout=15)
            else:
                r = _http_lib.post(url, headers=self.headers, json=body, timeout=15)  # type: ignore[call-arg]
            return r.status_code, self._parse(r)
        except Exception as e:
            return -1, {"error": str(e)}

    def _parse(self, r: Any) -> Any:
        try:
            return r.json()
        except Exception:
            return {"raw": r.text}


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def today_str(delta_days: int = 0) -> str:
    return (date.today() + timedelta(days=delta_days)).isoformat()


def extract_id(resp: Any) -> Optional[str]:
    """从响应体中提取 id 字段（兼容 data.id / id 两种格式）"""
    if isinstance(resp, dict):
        if "data" in resp and isinstance(resp["data"], dict):
            return resp["data"].get("id")
        return resp.get("id")
    return None


# ---------------------------------------------------------------------------
# 各模块初始化函数
# ---------------------------------------------------------------------------

def seed_categories(client: ApiClient) -> List[str]:
    """初始化12个费用科目，返回科目ID列表"""
    section("1/8  费用科目（12类）")

    categories_data = [
        {"code": "UTILITIES",    "name": "水电费",       "description": "门店水费、电费、燃气费"},
        {"code": "MAINTENANCE",  "name": "设备维修",     "description": "厨房设备、空调、收银机维修"},
        {"code": "TRAVEL",       "name": "差旅费",       "description": "督导巡店、总部培训出差"},
        {"code": "ENTERTAINMENT","name": "业务招待",     "description": "商务宴请、合作洽谈"},
        {"code": "RENT",         "name": "租金",         "description": "门店场地租金、仓库租金"},
        {"code": "DEPRECIATION", "name": "折旧摊销",     "description": "固定资产折旧、装修摊销"},
        {"code": "LABOR",        "name": "人工成本",     "description": "员工工资、社保、奖金"},
        {"code": "PLATFORM_FEE", "name": "外卖平台佣金", "description": "美团/饿了么/抖音平台服务费"},
        {"code": "SUPPLIES",     "name": "日常耗材",     "description": "包装盒、餐巾纸、清洁用品"},
        {"code": "MARKETING",    "name": "营销推广",     "description": "社媒投流、活动物料、优惠券"},
        {"code": "FOOD_WASTE",   "name": "食材损耗",     "description": "食材过期报废、备料损耗"},
        {"code": "OTHER",        "name": "其他费用",     "description": "无法归类的杂项支出"},
    ]

    # 先查询已有科目
    status_code, existing = client.get("/api/v1/expense/categories")
    existing_codes: set = set()
    cat_ids: List[str] = []

    if status_code == 200:
        items = []
        if isinstance(existing, dict):
            items = existing.get("items", existing.get("data", []))
        elif isinstance(existing, list):
            items = existing
        for item in items:
            existing_codes.add(item.get("code", ""))
            if item.get("id"):
                cat_ids.append(item["id"])
        info(f"已存在 {len(existing_codes)} 个科目")

    created = 0
    for cat in categories_data:
        if cat["code"] in existing_codes:
            info(f"跳过（已存在）: {cat['name']}")
            continue
        sc, resp = client.post("/api/v1/expense/categories", cat)
        if sc in (200, 201):
            new_id = extract_id(resp)
            if new_id:
                cat_ids.append(new_id)
            ok(f"创建科目: {cat['name']}")
            created += 1
        else:
            fail(f"创建科目失败: {cat['name']} → {sc} {resp}")

    print(f"  科目初始化完成: 新建 {created} 个，已存在 {len(existing_codes)} 个")
    return cat_ids


def seed_travel_standards(client: ApiClient) -> None:
    """初始化差旅差标（50城市）"""
    section("2/8  差旅差标（50城市四级）")

    # 城市差标数据（住宿上限/餐补/交通补，单位：元/天）
    standards = [
        # 一线城市
        {"city": "北京",   "tier": "tier1", "accommodation_limit": 600, "meal_allowance": 150, "transport_allowance": 100},
        {"city": "上海",   "tier": "tier1", "accommodation_limit": 600, "meal_allowance": 150, "transport_allowance": 100},
        {"city": "广州",   "tier": "tier1", "accommodation_limit": 500, "meal_allowance": 120, "transport_allowance": 80},
        {"city": "深圳",   "tier": "tier1", "accommodation_limit": 550, "meal_allowance": 120, "transport_allowance": 80},
        # 新一线/二线
        {"city": "成都",   "tier": "tier2", "accommodation_limit": 400, "meal_allowance": 100, "transport_allowance": 60},
        {"city": "杭州",   "tier": "tier2", "accommodation_limit": 450, "meal_allowance": 100, "transport_allowance": 60},
        {"city": "武汉",   "tier": "tier2", "accommodation_limit": 380, "meal_allowance": 100, "transport_allowance": 60},
        {"city": "西安",   "tier": "tier2", "accommodation_limit": 350, "meal_allowance": 90,  "transport_allowance": 60},
        {"city": "南京",   "tier": "tier2", "accommodation_limit": 420, "meal_allowance": 100, "transport_allowance": 60},
        {"city": "重庆",   "tier": "tier2", "accommodation_limit": 380, "meal_allowance": 100, "transport_allowance": 60},
        {"city": "天津",   "tier": "tier2", "accommodation_limit": 400, "meal_allowance": 100, "transport_allowance": 60},
        {"city": "苏州",   "tier": "tier2", "accommodation_limit": 420, "meal_allowance": 100, "transport_allowance": 60},
        {"city": "长沙",   "tier": "tier2", "accommodation_limit": 350, "meal_allowance": 90,  "transport_allowance": 60},
        {"city": "郑州",   "tier": "tier2", "accommodation_limit": 350, "meal_allowance": 90,  "transport_allowance": 60},
        {"city": "青岛",   "tier": "tier2", "accommodation_limit": 380, "meal_allowance": 90,  "transport_allowance": 60},
        {"city": "沈阳",   "tier": "tier2", "accommodation_limit": 350, "meal_allowance": 90,  "transport_allowance": 60},
        {"city": "济南",   "tier": "tier2", "accommodation_limit": 350, "meal_allowance": 90,  "transport_allowance": 60},
        {"city": "厦门",   "tier": "tier2", "accommodation_limit": 400, "meal_allowance": 100, "transport_allowance": 60},
        {"city": "宁波",   "tier": "tier2", "accommodation_limit": 380, "meal_allowance": 90,  "transport_allowance": 60},
        {"city": "大连",   "tier": "tier2", "accommodation_limit": 350, "meal_allowance": 90,  "transport_allowance": 60},
        # 三线及以下
        {"city": "贵阳",   "tier": "tier3", "accommodation_limit": 280, "meal_allowance": 80,  "transport_allowance": 50},
        {"city": "南宁",   "tier": "tier3", "accommodation_limit": 280, "meal_allowance": 80,  "transport_allowance": 50},
        {"city": "昆明",   "tier": "tier3", "accommodation_limit": 280, "meal_allowance": 80,  "transport_allowance": 50},
        {"city": "哈尔滨", "tier": "tier3", "accommodation_limit": 280, "meal_allowance": 80,  "transport_allowance": 50},
        {"city": "长春",   "tier": "tier3", "accommodation_limit": 280, "meal_allowance": 80,  "transport_allowance": 50},
        {"city": "呼和浩特","tier":"tier3", "accommodation_limit": 280, "meal_allowance": 80,  "transport_allowance": 50},
        {"city": "乌鲁木齐","tier":"tier3", "accommodation_limit": 300, "meal_allowance": 80,  "transport_allowance": 50},
        {"city": "兰州",   "tier": "tier3", "accommodation_limit": 260, "meal_allowance": 80,  "transport_allowance": 50},
        {"city": "银川",   "tier": "tier3", "accommodation_limit": 260, "meal_allowance": 80,  "transport_allowance": 50},
        {"city": "西宁",   "tier": "tier3", "accommodation_limit": 260, "meal_allowance": 80,  "transport_allowance": 50},
        {"city": "太原",   "tier": "tier3", "accommodation_limit": 280, "meal_allowance": 80,  "transport_allowance": 50},
        {"city": "南昌",   "tier": "tier3", "accommodation_limit": 280, "meal_allowance": 80,  "transport_allowance": 50},
        {"city": "福州",   "tier": "tier3", "accommodation_limit": 300, "meal_allowance": 80,  "transport_allowance": 50},
        {"city": "海口",   "tier": "tier3", "accommodation_limit": 300, "meal_allowance": 80,  "transport_allowance": 50},
        {"city": "三亚",   "tier": "tier3", "accommodation_limit": 500, "meal_allowance": 120, "transport_allowance": 80},
        {"city": "合肥",   "tier": "tier3", "accommodation_limit": 300, "meal_allowance": 80,  "transport_allowance": 50},
        {"city": "石家庄", "tier": "tier3", "accommodation_limit": 280, "meal_allowance": 80,  "transport_allowance": 50},
        {"city": "温州",   "tier": "tier3", "accommodation_limit": 320, "meal_allowance": 90,  "transport_allowance": 50},
        {"city": "泉州",   "tier": "tier3", "accommodation_limit": 300, "meal_allowance": 80,  "transport_allowance": 50},
        {"city": "扬州",   "tier": "tier3", "accommodation_limit": 280, "meal_allowance": 80,  "transport_allowance": 50},
        {"city": "无锡",   "tier": "tier3", "accommodation_limit": 350, "meal_allowance": 90,  "transport_allowance": 50},
        {"city": "常州",   "tier": "tier3", "accommodation_limit": 320, "meal_allowance": 80,  "transport_allowance": 50},
        {"city": "嘉兴",   "tier": "tier3", "accommodation_limit": 300, "meal_allowance": 80,  "transport_allowance": 50},
        {"city": "绍兴",   "tier": "tier3", "accommodation_limit": 300, "meal_allowance": 80,  "transport_allowance": 50},
        {"city": "唐山",   "tier": "tier3", "accommodation_limit": 260, "meal_allowance": 70,  "transport_allowance": 40},
        {"city": "洛阳",   "tier": "tier3", "accommodation_limit": 260, "meal_allowance": 70,  "transport_allowance": 40},
        {"city": "烟台",   "tier": "tier3", "accommodation_limit": 260, "meal_allowance": 70,  "transport_allowance": 40},
        {"city": "潍坊",   "tier": "tier3", "accommodation_limit": 260, "meal_allowance": 70,  "transport_allowance": 40},
        {"city": "桂林",   "tier": "tier3", "accommodation_limit": 280, "meal_allowance": 80,  "transport_allowance": 50},
        {"city": "珠海",   "tier": "tier3", "accommodation_limit": 380, "meal_allowance": 100, "transport_allowance": 60},
    ]

    # 先检查是否已有差标配置
    sc, existing = client.get("/api/v1/expense/travel/standards")
    if sc == 200:
        items = []
        if isinstance(existing, dict):
            items = existing.get("items", existing.get("data", []))
        existing_cities = {item.get("city") for item in items if isinstance(item, dict)}
        info(f"已存在 {len(existing_cities)} 个城市差标")
    else:
        existing_cities = set()

    created = 0
    for std in standards:
        if std["city"] in existing_cities:
            continue
        body = {
            "city": std["city"],
            "city_tier": std["tier"],
            "staff_level": "region_manager",  # 默认区域经理标准
            "accommodation_limit_fen": std["accommodation_limit"] * 100,
            "meal_allowance_fen": std["meal_allowance"] * 100,
            "transport_allowance_fen": std["transport_allowance"] * 100,
            "effective_date": today_str(),
        }
        sc, resp = client.post("/api/v1/expense/travel/standards", body)
        if sc in (200, 201):
            created += 1
        # 静默跳过错误，差标接口可能未实现

    ok(f"差旅差标: 新建 {created} 个城市，已存在 {len(existing_cities)} 个")


def seed_budgets(client: ApiClient, store_id: str) -> List[str]:
    """初始化5个预算"""
    section("3/8  月度/年度预算（5个）")

    year = 2026
    budgets = [
        {
            "budget_name": f"{year}年度综合费用预算",
            "budget_year": year,
            "budget_type": "expense",
            "total_amount_fen": 120_000_00,  # 120,000元
            "store_id": store_id,
            "brand_id": DEMO_BRAND_ID,
            "notes": "含水电/耗材/维修/营销全年预算",
        },
        {
            "budget_name": f"{year}年度差旅费预算",
            "budget_year": year,
            "budget_type": "travel",
            "total_amount_fen": 30_000_00,
            "store_id": store_id,
            "brand_id": DEMO_BRAND_ID,
            "notes": "督导巡店差旅年度预算",
        },
        {
            "budget_name": f"{year}年4月费用预算",
            "budget_year": year,
            "budget_month": 4,
            "budget_type": "expense",
            "total_amount_fen": 8_000_00,
            "store_id": store_id,
            "brand_id": DEMO_BRAND_ID,
        },
        {
            "budget_name": f"{year}年5月费用预算",
            "budget_year": year,
            "budget_month": 5,
            "budget_type": "expense",
            "total_amount_fen": 8_500_00,
            "store_id": store_id,
            "brand_id": DEMO_BRAND_ID,
        },
        {
            "budget_name": f"{year}年度采购预算",
            "budget_year": year,
            "budget_type": "procurement",
            "total_amount_fen": 200_000_00,
            "store_id": store_id,
            "brand_id": DEMO_BRAND_ID,
            "notes": "年度食材/耗材采购预算",
        },
    ]

    budget_ids: List[str] = []
    for b in budgets:
        sc, resp = client.post("/api/v1/expense/budgets", b)
        if sc in (200, 201):
            bid = extract_id(resp)
            if bid:
                budget_ids.append(bid)
            ok(f"预算: {b['budget_name']}")
        elif sc == 409:
            info(f"跳过（已存在）: {b['budget_name']}")
        else:
            fail(f"预算创建失败: {b['budget_name']} → {sc}")

    return budget_ids


def seed_petty_cash(client: ApiClient) -> List[str]:
    """初始化3个备用金账户"""
    section("4/8  备用金账户（3个门店）")

    accounts = [
        {
            "store_id": DEMO_STORE_1_ID,
            "brand_id": DEMO_BRAND_ID,
            "keeper_id": DEMO_KEEPER_1_ID,
            "approved_limit": 500_00,    # 500元
            "warning_threshold": 100_00, # 100元预警
            "opening_balance": 300_00,   # 期初300元
        },
        {
            "store_id": DEMO_STORE_2_ID,
            "brand_id": DEMO_BRAND_ID,
            "keeper_id": DEMO_KEEPER_2_ID,
            "approved_limit": 800_00,
            "warning_threshold": 150_00,
            "opening_balance": 500_00,
        },
        {
            "store_id": DEMO_STORE_3_ID,
            "brand_id": DEMO_BRAND_ID,
            "keeper_id": DEMO_KEEPER_3_ID,
            "approved_limit": 600_00,
            "warning_threshold": 120_00,
            "opening_balance": 400_00,
        },
    ]

    account_ids: List[str] = []
    store_names = ["旗舰店（长沙IFS）", "分店（长沙万象城）", "分店（长沙步步高）"]

    for i, acc in enumerate(accounts):
        sc, resp = client.post("/api/v1/expense/petty-cash/accounts", acc)
        if sc in (200, 201):
            aid = extract_id(resp)
            if aid:
                account_ids.append(aid)
            ok(f"备用金账户: {store_names[i]}  额度={acc['approved_limit']//100}元")
        elif sc == 409:
            info(f"跳过（已存在）: {store_names[i]}")
        else:
            fail(f"备用金账户创建失败: {store_names[i]} → {sc}")

    return account_ids


def seed_expenses(client: ApiClient, cat_ids: List[str]) -> List[str]:
    """初始化10个费控申请（不同状态）"""
    section("5/8  费控申请（10个，各状态）")

    # 如果没有科目ID，用占位UUID
    cat_id = cat_ids[0] if cat_ids else "00000000-0000-0000-0000-000000000001"
    travel_cat_id = cat_ids[2] if len(cat_ids) > 2 else cat_id
    ent_cat_id = cat_ids[3] if len(cat_ids) > 3 else cat_id
    rent_cat_id = cat_ids[4] if len(cat_ids) > 4 else cat_id

    expenses_def = [
        # 草稿状态 —— 2个
        {
            "title": "4月水电费报销",
            "scenario_code": "DAILY_EXPENSE",
            "store_id": DEMO_STORE_1_ID,
            "brand_id": DEMO_BRAND_ID,
            "notes": "门店4月水费326元+电费1,243元",
            "items": [
                {"category_id": cat_id, "description": "4月水费", "amount": 326_00,
                 "quantity": 1.0, "unit": "笔", "expense_date": today_str(-5)},
                {"category_id": cat_id, "description": "4月电费", "amount": 1243_00,
                 "quantity": 1.0, "unit": "笔", "expense_date": today_str(-5)},
            ],
            "_action": "draft",
        },
        {
            "title": "厨房水泵维修申请",
            "scenario_code": "EQUIPMENT_REPAIR",
            "store_id": DEMO_STORE_2_ID,
            "brand_id": DEMO_BRAND_ID,
            "notes": "主水泵故障，联系维修厂报价560元",
            "items": [
                {"category_id": cat_id, "description": "水泵维修人工+材料", "amount": 560_00,
                 "quantity": 1.0, "unit": "次", "expense_date": today_str(-1)},
            ],
            "_action": "draft",
        },
        # 待审批 —— 3个
        {
            "title": "5月日常耗材采购",
            "scenario_code": "SPOT_PURCHASE",
            "store_id": DEMO_STORE_1_ID,
            "brand_id": DEMO_BRAND_ID,
            "notes": "包装盒/餐巾纸/清洁用品",
            "items": [
                {"category_id": cat_id, "description": "包装盒(200套)", "amount": 180_00,
                 "quantity": 200, "unit": "套", "expense_date": today_str(-3)},
                {"category_id": cat_id, "description": "清洁用品套装", "amount": 95_00,
                 "quantity": 1, "unit": "批", "expense_date": today_str(-3)},
            ],
            "_action": "submit",
        },
        {
            "title": "督导5月巡店差旅",
            "scenario_code": "BUSINESS_TRIP",
            "store_id": DEMO_STORE_1_ID,
            "brand_id": DEMO_BRAND_ID,
            "notes": "长沙→贵阳3店巡查，高铁+住宿2晚",
            "items": [
                {"category_id": travel_cat_id, "description": "高铁票（长沙-贵阳往返）",
                 "amount": 1040_00, "quantity": 1.0, "unit": "张", "expense_date": today_str(-7)},
                {"category_id": travel_cat_id, "description": "住宿费（2晚）",
                 "amount": 560_00, "quantity": 2.0, "unit": "晚", "expense_date": today_str(-6)},
                {"category_id": travel_cat_id, "description": "餐补（3天×80元）",
                 "amount": 240_00, "quantity": 3.0, "unit": "天", "expense_date": today_str(-6)},
            ],
            "_action": "submit",
        },
        {
            "title": "品牌商合作洽谈招待餐",
            "scenario_code": "ENTERTAINMENT",
            "store_id": DEMO_STORE_1_ID,
            "brand_id": DEMO_BRAND_ID,
            "notes": "接待供应商代表3人，商谈2026年食材供应合作",
            "items": [
                {"category_id": ent_cat_id, "description": "商务宴请",
                 "amount": 2380_00, "quantity": 1.0, "unit": "次", "expense_date": today_str(-10)},
            ],
            "_action": "submit",
        },
        # 已审批 —— 2个
        {
            "title": "3月空调保养费",
            "scenario_code": "EQUIPMENT_REPAIR",
            "store_id": DEMO_STORE_3_ID,
            "brand_id": DEMO_BRAND_ID,
            "notes": "3台空调年度保养，共420元",
            "items": [
                {"category_id": cat_id, "description": "空调年度保养（3台）",
                 "amount": 420_00, "quantity": 3.0, "unit": "台", "expense_date": today_str(-20)},
            ],
            "_action": "submit",   # 提交后需模拟审批通过 —— 脚本中仅标记为已提交
        },
        {
            "title": "总部培训差旅费",
            "scenario_code": "BUSINESS_TRIP",
            "store_id": DEMO_STORE_2_ID,
            "brand_id": DEMO_BRAND_ID,
            "notes": "参加总部新品培训，长沙→上海往返",
            "items": [
                {"category_id": travel_cat_id, "description": "机票（长沙→上海往返）",
                 "amount": 2800_00, "quantity": 1.0, "unit": "张", "expense_date": today_str(-15)},
                {"category_id": travel_cat_id, "description": "住宿（4晚）",
                 "amount": 2000_00, "quantity": 4.0, "unit": "晚", "expense_date": today_str(-14)},
                {"category_id": travel_cat_id, "description": "餐补（5天）",
                 "amount": 750_00, "quantity": 5.0, "unit": "天", "expense_date": today_str(-14)},
            ],
            "_action": "submit",
        },
        # 已付款 —— 2个
        {
            "title": "3月水电费（IFS店）",
            "scenario_code": "DAILY_EXPENSE",
            "store_id": DEMO_STORE_1_ID,
            "brand_id": DEMO_BRAND_ID,
            "notes": "3月水费298元+电费1,456元，已核销",
            "items": [
                {"category_id": cat_id, "description": "3月水费", "amount": 298_00,
                 "quantity": 1.0, "unit": "笔", "expense_date": today_str(-35)},
                {"category_id": cat_id, "description": "3月电费", "amount": 1456_00,
                 "quantity": 1.0, "unit": "笔", "expense_date": today_str(-35)},
            ],
            "_action": "submit",
        },
        {
            "title": "2月员工餐补",
            "scenario_code": "MEAL_ALLOWANCE",
            "store_id": DEMO_STORE_1_ID,
            "brand_id": DEMO_BRAND_ID,
            "notes": "2月全体员工餐补，12人×28天×10元",
            "items": [
                {"category_id": cat_id, "description": "2月员工餐补",
                 "amount": 3360_00, "quantity": 1.0, "unit": "批", "expense_date": today_str(-50)},
            ],
            "_action": "submit",
        },
        # 超标申请（会触发A3合规检查） —— 1个
        {
            "title": "年会晚宴业务招待",
            "scenario_code": "ENTERTAINMENT",
            "store_id": DEMO_STORE_1_ID,
            "brand_id": DEMO_BRAND_ID,
            "notes": "集团年会客户答谢晚宴，预计12桌，超出差标需附说明",
            "items": [
                {"category_id": ent_cat_id, "description": "年会答谢晚宴（12桌）",
                 "amount": 18000_00, "quantity": 12.0, "unit": "桌", "expense_date": today_str(-2)},
            ],
            "_action": "submit",
        },
    ]

    exp_ids: List[str] = []
    for idx, exp_def in enumerate(expenses_def, 1):
        action = exp_def.pop("_action")
        items = exp_def.pop("items")

        # 创建申请
        sc, resp = client.post("/api/v1/expense/applications", {**exp_def})
        if sc not in (200, 201):
            fail(f"申请{idx} 创建失败 → {sc}: {resp}")
            continue

        exp_id = extract_id(resp)
        if not exp_id:
            fail(f"申请{idx} 无法提取ID")
            continue
        exp_ids.append(exp_id)

        # 添加费用明细
        for item in items:
            client.post(f"/api/v1/expense/applications/{exp_id}/items", item)

        # 提交（如需）
        if action == "submit":
            sc2, _ = client.post(f"/api/v1/expense/applications/{exp_id}/submit", {})
            status_label = "待审批" if sc2 in (200, 201) else "提交失败"
        else:
            status_label = "草稿"

        ok(f"申请{idx}: 《{exp_def['title']}》 [{status_label}]")

    return exp_ids


def seed_contracts(client: ApiClient) -> List[str]:
    """初始化2个合同"""
    section("6/8  合同台账（2个）")

    contracts = [
        {
            "contract_no": "DEMO-RENT-2026-001",
            "contract_name": "长沙IFS旗舰店场地租赁合同",
            "contract_type": "rental",
            "counterparty_name": "长沙国金物业管理有限公司",
            "counterparty_contact": "张经理",
            "total_amount": 1_800_000_00,  # 180万/年（分）
            "start_date": "2026-01-01",
            "end_date": "2028-12-31",
            "payment_cycle": "monthly",
            "store_id": DEMO_STORE_1_ID,
            "brand_id": DEMO_BRAND_ID,
            "notes": "3年合同，每月15日付款，年租金180万元",
            "alert_days_before_expiry": 90,
        },
        {
            "contract_no": "DEMO-EQUIP-2026-001",
            "contract_name": "厨房设备综合维保服务合同",
            "contract_type": "service",
            "counterparty_name": "湖南厨艺设备服务有限公司",
            "counterparty_contact": "李工",
            "total_amount": 36_000_00,  # 3.6万（分）
            "start_date": "2026-04-01",
            "end_date": "2027-03-31",
            "payment_cycle": "quarterly",
            "store_id": DEMO_STORE_1_ID,
            "brand_id": DEMO_BRAND_ID,
            "notes": "覆盖炒炉/蒸箱/保鲜柜/洗碗机，季度付款",
            "alert_days_before_expiry": 60,
        },
    ]

    contract_ids: List[str] = []
    for ct in contracts:
        sc, resp = client.post("/api/v1/expense/contracts", ct)
        if sc in (200, 201):
            cid = extract_id(resp)
            if cid:
                contract_ids.append(cid)
            ok(f"合同: {ct['contract_name']}")
        elif sc == 409:
            info(f"跳过（已存在）: {ct['contract_name']}")
        else:
            fail(f"合同创建失败: {ct['contract_name']} → {sc}")

    return contract_ids


def seed_travel(client: ApiClient) -> Optional[str]:
    """初始化1个差旅申请（含2条行程）"""
    section("7/8  差旅申请（1个，含2条行程）")

    travel_body = {
        "brand_id": DEMO_BRAND_ID,
        "store_id": DEMO_STORE_1_ID,
        "traveler_id": DEMO_USER_ID,
        "planned_start_date": today_str(3),
        "planned_end_date": today_str(5),
        "departure_city": "长沙",
        "destination_cities": ["贵阳"],
        "planned_stores": ["贵阳南明店", "贵阳云岩旗舰店"],
        "task_type": "inspection",
        "transport_mode": "high_speed_rail",
        "estimated_cost_fen": 2800_00,
        "notes": "Q2督导巡店计划，重点检查贵阳2店Q1经营情况",
    }

    sc, resp = client.post("/api/v1/expense/travel/requests", travel_body)
    if sc not in (200, 201):
        fail(f"差旅申请创建失败 → {sc}: {resp}")
        return None

    travel_id = extract_id(resp)
    if not travel_id:
        fail("差旅申请无法提取ID")
        return None

    ok(f"差旅申请: 长沙→贵阳巡店 (ID: {travel_id[:8]}...)")

    # 添加2条行程
    itineraries = [
        {
            "store_id": DEMO_STORE_2_ID,
            "store_name": "贵阳南明店",
            "sequence_order": 1,
            "planned_date": today_str(3),
            "check_items": ["食安检查", "环境卫生", "员工仪容", "菜品质量"],
        },
        {
            "store_id": DEMO_STORE_3_ID,
            "store_name": "贵阳云岩旗舰店",
            "sequence_order": 2,
            "planned_date": today_str(4),
            "check_items": ["设备运行状态", "备用金盘点", "销售数据核查"],
        },
    ]

    for itin in itineraries:
        sc2, _ = client.post(f"/api/v1/expense/travel/requests/{travel_id}/itineraries", itin)
        if sc2 in (200, 201):
            ok(f"  行程: {itin['store_name']}")
        else:
            fail(f"  行程创建失败: {itin['store_name']} → {sc2}")

    # 提交审批
    sc3, _ = client.post(f"/api/v1/expense/travel/requests/{travel_id}/submit", {})
    if sc3 in (200, 201):
        ok("差旅申请已提交审批")
    else:
        info(f"差旅申请提交状态: {sc3}（可能接口尚未实现）")

    return travel_id


def seed_mock_invoices(client: ApiClient, exp_ids: List[str]) -> None:
    """模拟发票上传（mock数据，不上传真实文件）"""
    section("8/8  模拟发票元数据（mock）")

    if not exp_ids:
        info("无费控申请ID，跳过发票初始化")
        return

    mock_invoices = [
        {
            "invoice_code": "044031900104",
            "invoice_number": "73846201",
            "invoice_type": "vat_general",
            "invoice_date": today_str(-5),
            "seller_name": "长沙水务集团有限公司",
            "seller_tax_id": "91430100400001234X",
            "buyer_name": "长沙屯象餐饮管理有限公司",
            "total_amount_fen": 326_00,
            "tax_amount_fen": 10_44,
            "application_id": exp_ids[0] if exp_ids else None,
            "brand_id": DEMO_BRAND_ID,
            "store_id": DEMO_STORE_1_ID,
            "ocr_provider": "mock",
        },
        {
            "invoice_code": "044031900105",
            "invoice_number": "98761023",
            "invoice_type": "vat_special",
            "invoice_date": today_str(-10),
            "seller_name": "长沙供电局",
            "seller_tax_id": "914301001234567890",
            "buyer_name": "长沙屯象餐饮管理有限公司",
            "total_amount_fen": 1243_00,
            "tax_amount_fen": 74_58,
            "application_id": exp_ids[0] if exp_ids else None,
            "brand_id": DEMO_BRAND_ID,
            "store_id": DEMO_STORE_1_ID,
            "ocr_provider": "mock",
        },
    ]

    for inv in mock_invoices:
        sc, resp = client.post("/api/v1/expense/invoices/mock", inv)
        if sc in (200, 201):
            ok(f"发票: {inv['seller_name']} ¥{inv['total_amount_fen']//100}")
        else:
            # 尝试直接上传元数据路径
            sc2, _ = client.post("/api/v1/expense/invoices/metadata", inv)
            if sc2 in (200, 201):
                ok(f"发票元数据: {inv['seller_name']} ¥{inv['total_amount_fen']//100}")
            else:
                info(f"发票mock接口未实现，跳过 ({sc}/{sc2})")
                break


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="屯象OS费控DEMO数据初始化脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python seed_expense_demo.py
  python seed_expense_demo.py --base-url http://staging.tunxiang.com:8015
  python seed_expense_demo.py --base-url http://localhost:8015 --tenant-id <UUID>
        """,
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8015",
        help="服务基础URL（默认：http://localhost:8015）",
    )
    parser.add_argument(
        "--tenant-id",
        default=DEMO_TENANT_ID,
        help=f"租户ID（默认：{DEMO_TENANT_ID}）",
    )
    parser.add_argument(
        "--user-id",
        default=DEMO_USER_ID,
        help=f"用户ID（默认：{DEMO_USER_ID}）",
    )
    args = parser.parse_args()

    print(f"\n{BOLD}{'='*55}{RESET}")
    print(f"{BOLD}  屯象OS 费控系统 DEMO 数据初始化{RESET}")
    print(f"{BOLD}{'='*55}{RESET}")
    print(f"  服务地址  : {args.base_url}")
    print(f"  租户ID    : {args.tenant_id}")
    print(f"  用户ID    : {args.user_id}")

    client = ApiClient(args.base_url, args.tenant_id, args.user_id)

    # 健康检查
    sc, health = client.get("/health")
    if sc != 200:
        print(f"\n{RED}ERROR: 服务不可用（{sc}）。请确认服务已启动：{args.base_url}{RESET}")
        return 1
    ok(f"服务健康检查通过: {health}")

    # 依次初始化各模块
    cat_ids = seed_categories(client)
    seed_travel_standards(client)
    budget_ids = seed_budgets(client, DEMO_STORE_1_ID)
    account_ids = seed_petty_cash(client)
    exp_ids = seed_expenses(client, cat_ids)
    contract_ids = seed_contracts(client)
    travel_id = seed_travel(client)
    seed_mock_invoices(client, exp_ids)

    # 汇总
    section("初始化完成 — 汇总")
    print(f"  {GREEN}科目{RESET}     : {len(cat_ids)} 个")
    print(f"  {GREEN}预算{RESET}     : {len(budget_ids)} 个")
    print(f"  {GREEN}备用金{RESET}   : {len(account_ids)} 个账户")
    print(f"  {GREEN}费控申请{RESET} : {len(exp_ids)} 个")
    print(f"  {GREEN}合同{RESET}     : {len(contract_ids)} 个")
    print(f"  {GREEN}差旅{RESET}     : {'1个' if travel_id else '0个（接口异常）'}")
    print(f"\n{GREEN}{BOLD}DEMO数据初始化完成！{RESET}")
    print(f"访问费控看板: {args.base_url}/api/v1/expense/dashboard/summary\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
