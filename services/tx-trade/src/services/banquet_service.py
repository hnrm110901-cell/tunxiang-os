"""宴会智能管理 — 品质正餐的核心利润引擎

婚宴/寿宴/商务宴/团建/周年庆 全生命周期管理。
从线索获取 → AI方案推荐 → 成本测算 → 合同确认 → 执行检查 → 结算复盘。

所有金额单位：分（fen）。
"""
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional

import structlog

logger = structlog.get_logger()


# ─── 数据模型 ───

@dataclass
class BanquetProposal:
    """宴会方案"""
    proposal_id: str
    event_type: str  # wedding/birthday/business/team_building/anniversary
    guest_count: int
    tiers: list[dict]  # 3 tiers with menu + price
    venue: dict  # {name, capacity, features, cost}
    decoration: dict  # {theme, items, cost}
    service_plan: dict  # {waiters, chefs, coordinator}
    cost_breakdown: dict
    estimated_total: int  # fen
    margin_rate: float
    confidence: float
    similar_cases: list[dict] = field(default_factory=list)


@dataclass
class BanquetCostEstimate:
    """宴会成本估算"""
    proposal_id: str
    food_cost_fen: int
    labor_cost_fen: int
    venue_cost_fen: int
    decoration_cost_fen: int
    beverage_cost_fen: int
    misc_cost_fen: int
    total_cost_fen: int
    estimated_revenue_fen: int
    estimated_margin_fen: int
    margin_rate: float


# ─── 宴会菜单模板 ───

EVENT_TYPE_CONFIG = {
    "wedding": {
        "name": "婚宴",
        "course_count": (10, 12),
        "theme_color": "red",
        "must_have_dishes": ["龙虾", "鲍鱼", "石斑鱼", "乳猪", "炖汤"],
        "optional_premium": ["鱼翅", "花胶", "海参"],
        "taboo": ["梨(离)", "苦瓜"],
        "decoration_items": ["鲜花拱门", "红色桌布", "喜字", "签到台", "LED屏"],
        "service_extras": ["司仪协调", "灯光控场", "礼炮", "甜品台"],
    },
    "birthday": {
        "name": "寿宴",
        "course_count": (8, 10),
        "theme_color": "gold",
        "must_have_dishes": ["寿桃", "长寿面", "蒸鱼(年年有余)", "炖汤"],
        "optional_premium": ["鲍鱼", "花胶", "佛跳墙"],
        "taboo": [],
        "decoration_items": ["寿字背景", "金色桌布", "鲜花", "蛋糕台"],
        "service_extras": ["寿桃仪式", "祝寿环节", "蛋糕切割"],
    },
    "business": {
        "name": "商务宴",
        "course_count": (8, 10),
        "theme_color": "navy",
        "must_have_dishes": ["鲍鱼", "石斑鱼", "和牛", "炖汤"],
        "optional_premium": ["龙虾", "帝王蟹", "松露"],
        "taboo": [],
        "decoration_items": ["简约桌花", "品牌桌卡", "投影设备"],
        "service_extras": ["专属管家", "红酒侍酒", "茶艺服务"],
    },
    "team_building": {
        "name": "团建",
        "course_count": (8, 12),
        "theme_color": "blue",
        "must_have_dishes": ["烤鱼", "小龙虾", "烤肉", "火锅"],
        "optional_premium": ["海鲜拼盘"],
        "taboo": [],
        "decoration_items": ["团队横幅", "气球装饰", "音响设备"],
        "service_extras": ["互动游戏", "抽奖环节"],
    },
    "anniversary": {
        "name": "周年庆",
        "course_count": (10, 12),
        "theme_color": "custom",
        "must_have_dishes": ["招牌菜", "特色菜", "炖汤"],
        "optional_premium": ["定制菜品", "限定甜品"],
        "taboo": [],
        "decoration_items": ["定制背景板", "鲜花", "纪念品展台", "LED屏"],
        "service_extras": ["定制仪式", "摄影摄像", "纪念品制作"],
    },
}

# 菜品单价参考（分/位）— 用于方案测算
TIER_PRICING = {
    "economy": {
        "wedding": 68800,      # 688元/位
        "birthday": 58800,     # 588元/位
        "business": 78800,     # 788元/位
        "team_building": 18800,  # 188元/位
        "anniversary": 58800,  # 588元/位
    },
    "standard": {
        "wedding": 98800,      # 988元/位
        "birthday": 78800,     # 788元/位
        "business": 118800,    # 1188元/位
        "team_building": 28800,  # 288元/位
        "anniversary": 88800,  # 888元/位
    },
    "premium": {
        "wedding": 158800,     # 1588元/位
        "birthday": 128800,    # 1288元/位
        "business": 188800,    # 1888元/位
        "team_building": 48800,  # 488元/位
        "anniversary": 138800,  # 1388元/位
    },
}

# 菜单模板 — 各档次代表菜品
MENU_TEMPLATES = {
    "wedding": {
        "economy": [
            {"name": "鸿运乳猪拼盘", "price_fen": 28800, "type": "cold"},
            {"name": "白灼大虾", "price_fen": 16800, "type": "hot"},
            {"name": "清蒸石斑鱼", "price_fen": 38800, "type": "hot"},
            {"name": "鲍汁花菇扣辽参", "price_fen": 32800, "type": "hot"},
            {"name": "XO酱炒带子", "price_fen": 18800, "type": "hot"},
            {"name": "避风塘炒蟹", "price_fen": 28800, "type": "hot"},
            {"name": "椒盐九肚鱼", "price_fen": 12800, "type": "hot"},
            {"name": "上汤焗龙虾", "price_fen": 58800, "type": "main"},
            {"name": "花胶鸡煲汤", "price_fen": 22800, "type": "soup"},
            {"name": "百合炒芦笋", "price_fen": 8800, "type": "vegetable"},
            {"name": "精美甜品双拼", "price_fen": 6800, "type": "dessert"},
            {"name": "时令鲜果盘", "price_fen": 5800, "type": "fruit"},
        ],
        "standard": [
            {"name": "鸿运乳猪全体", "price_fen": 38800, "type": "cold"},
            {"name": "蒜蓉蒸波士顿龙虾", "price_fen": 68800, "type": "main"},
            {"name": "鲍汁扣南非干鲍", "price_fen": 58800, "type": "hot"},
            {"name": "清蒸东星斑", "price_fen": 58800, "type": "hot"},
            {"name": "黑松露炒带子", "price_fen": 28800, "type": "hot"},
            {"name": "姜葱焗肉蟹", "price_fen": 38800, "type": "hot"},
            {"name": "蜜汁叉烧", "price_fen": 18800, "type": "hot"},
            {"name": "脆皮烧鹅", "price_fen": 22800, "type": "hot"},
            {"name": "竹笙花胶炖鸡", "price_fen": 38800, "type": "soup"},
            {"name": "松茸炒芦笋", "price_fen": 12800, "type": "vegetable"},
            {"name": "杨枝甘露+红豆沙", "price_fen": 8800, "type": "dessert"},
            {"name": "精选时令果盘", "price_fen": 8800, "type": "fruit"},
        ],
        "premium": [
            {"name": "极品鸿运乳猪全体", "price_fen": 58800, "type": "cold"},
            {"name": "芝士焗澳洲龙虾", "price_fen": 128800, "type": "main"},
            {"name": "鲍汁扣吉品鲍", "price_fen": 98800, "type": "hot"},
            {"name": "清蒸老鼠斑", "price_fen": 88800, "type": "hot"},
            {"name": "黑松露和牛粒", "price_fen": 58800, "type": "hot"},
            {"name": "帝王蟹刺身拼盘", "price_fen": 88800, "type": "hot"},
            {"name": "花胶佛跳墙", "price_fen": 78800, "type": "soup"},
            {"name": "XO酱炒象拔蚌", "price_fen": 48800, "type": "hot"},
            {"name": "金箔燕窝", "price_fen": 38800, "type": "hot"},
            {"name": "黑松露炒时蔬", "price_fen": 18800, "type": "vegetable"},
            {"name": "法式甜品三重奏", "price_fen": 18800, "type": "dessert"},
            {"name": "精品水果塔", "price_fen": 12800, "type": "fruit"},
        ],
    },
    "birthday": {
        "economy": [
            {"name": "五福拼盘", "price_fen": 22800, "type": "cold"},
            {"name": "清蒸鲈鱼(年年有余)", "price_fen": 18800, "type": "hot"},
            {"name": "鲍汁花菇", "price_fen": 22800, "type": "hot"},
            {"name": "白切鸡", "price_fen": 16800, "type": "hot"},
            {"name": "蒜蓉粉丝蒸扇贝", "price_fen": 16800, "type": "hot"},
            {"name": "红烧肉", "price_fen": 15800, "type": "hot"},
            {"name": "花胶鸡汤", "price_fen": 22800, "type": "soup"},
            {"name": "长寿面", "price_fen": 8800, "type": "staple"},
            {"name": "寿桃(6只)", "price_fen": 12800, "type": "dessert"},
            {"name": "时令果盘", "price_fen": 5800, "type": "fruit"},
        ],
        "standard": [
            {"name": "锦绣拼盘", "price_fen": 32800, "type": "cold"},
            {"name": "清蒸石斑鱼", "price_fen": 38800, "type": "hot"},
            {"name": "鲍汁扣辽参", "price_fen": 38800, "type": "hot"},
            {"name": "盐焗鸡", "price_fen": 22800, "type": "hot"},
            {"name": "避风塘炒蟹", "price_fen": 32800, "type": "hot"},
            {"name": "蜜汁叉烧", "price_fen": 18800, "type": "hot"},
            {"name": "花胶炖鸡汤", "price_fen": 32800, "type": "soup"},
            {"name": "手工长寿面", "price_fen": 12800, "type": "staple"},
            {"name": "寿桃(8只)+蛋糕", "price_fen": 18800, "type": "dessert"},
            {"name": "精选果盘", "price_fen": 8800, "type": "fruit"},
        ],
        "premium": [
            {"name": "极品海鲜拼盘", "price_fen": 58800, "type": "cold"},
            {"name": "清蒸东星斑", "price_fen": 68800, "type": "hot"},
            {"name": "鲍汁扣吉品鲍", "price_fen": 88800, "type": "hot"},
            {"name": "佛跳墙", "price_fen": 78800, "type": "soup"},
            {"name": "黑松露和牛", "price_fen": 58800, "type": "hot"},
            {"name": "帝王蟹两吃", "price_fen": 88800, "type": "hot"},
            {"name": "金箔燕窝", "price_fen": 38800, "type": "hot"},
            {"name": "手工翡翠长寿面", "price_fen": 18800, "type": "staple"},
            {"name": "寿桃(12只)+定制蛋糕", "price_fen": 28800, "type": "dessert"},
            {"name": "精品水果塔", "price_fen": 12800, "type": "fruit"},
        ],
    },
    "business": {
        "economy": [
            {"name": "精选冷菜四拼", "price_fen": 22800, "type": "cold"},
            {"name": "清蒸鲈鱼", "price_fen": 22800, "type": "hot"},
            {"name": "鲍汁花菇", "price_fen": 22800, "type": "hot"},
            {"name": "黑椒牛仔骨", "price_fen": 28800, "type": "hot"},
            {"name": "白灼虾", "price_fen": 22800, "type": "hot"},
            {"name": "松茸炖鸡汤", "price_fen": 28800, "type": "soup"},
            {"name": "炒时蔬", "price_fen": 8800, "type": "vegetable"},
            {"name": "精美甜品", "price_fen": 6800, "type": "dessert"},
            {"name": "果盘", "price_fen": 5800, "type": "fruit"},
        ],
        "standard": [
            {"name": "鲍鱼刺身拼盘", "price_fen": 38800, "type": "cold"},
            {"name": "清蒸石斑鱼", "price_fen": 48800, "type": "hot"},
            {"name": "鲍汁扣辽参", "price_fen": 42800, "type": "hot"},
            {"name": "澳洲和牛粒", "price_fen": 48800, "type": "hot"},
            {"name": "蒜蓉蒸波龙", "price_fen": 58800, "type": "main"},
            {"name": "避风塘炒蟹", "price_fen": 38800, "type": "hot"},
            {"name": "松茸花胶炖鸡", "price_fen": 38800, "type": "soup"},
            {"name": "松茸炒芦笋", "price_fen": 12800, "type": "vegetable"},
            {"name": "甜品双拼", "price_fen": 8800, "type": "dessert"},
            {"name": "精选果盘", "price_fen": 8800, "type": "fruit"},
        ],
        "premium": [
            {"name": "极品海鲜刺身船", "price_fen": 68800, "type": "cold"},
            {"name": "清蒸老鼠斑", "price_fen": 98800, "type": "hot"},
            {"name": "鲍汁扣吉品鲍", "price_fen": 88800, "type": "hot"},
            {"name": "A5和牛西冷", "price_fen": 88800, "type": "hot"},
            {"name": "芝士焗澳龙", "price_fen": 118800, "type": "main"},
            {"name": "帝王蟹刺身", "price_fen": 98800, "type": "hot"},
            {"name": "佛跳墙", "price_fen": 78800, "type": "soup"},
            {"name": "黑松露炒时蔬", "price_fen": 18800, "type": "vegetable"},
            {"name": "法式甜品", "price_fen": 18800, "type": "dessert"},
            {"name": "精品水果塔", "price_fen": 12800, "type": "fruit"},
        ],
    },
    "team_building": {
        "economy": [
            {"name": "凉菜六拼", "price_fen": 12800, "type": "cold"},
            {"name": "烤鱼", "price_fen": 15800, "type": "hot"},
            {"name": "口水鸡", "price_fen": 10800, "type": "hot"},
            {"name": "毛血旺", "price_fen": 12800, "type": "hot"},
            {"name": "小龙虾", "price_fen": 16800, "type": "hot"},
            {"name": "蒜蓉扇贝", "price_fen": 10800, "type": "hot"},
            {"name": "酸菜鱼", "price_fen": 12800, "type": "hot"},
            {"name": "炒时蔬", "price_fen": 5800, "type": "vegetable"},
            {"name": "米饭/面条", "price_fen": 2800, "type": "staple"},
            {"name": "西瓜", "price_fen": 3800, "type": "fruit"},
        ],
        "standard": [
            {"name": "卤水拼盘", "price_fen": 18800, "type": "cold"},
            {"name": "香辣蟹", "price_fen": 28800, "type": "hot"},
            {"name": "烤全羊(例)", "price_fen": 22800, "type": "hot"},
            {"name": "蒜蓉大虾", "price_fen": 22800, "type": "hot"},
            {"name": "小龙虾(大份)", "price_fen": 22800, "type": "hot"},
            {"name": "水煮牛肉", "price_fen": 18800, "type": "hot"},
            {"name": "铁板鱿鱼", "price_fen": 12800, "type": "hot"},
            {"name": "炒时蔬两道", "price_fen": 8800, "type": "vegetable"},
            {"name": "主食", "price_fen": 3800, "type": "staple"},
            {"name": "饮料+果盘", "price_fen": 6800, "type": "fruit"},
        ],
        "premium": [
            {"name": "海鲜拼盘", "price_fen": 38800, "type": "cold"},
            {"name": "帝王蟹火锅", "price_fen": 58800, "type": "hot"},
            {"name": "烤全羊", "price_fen": 38800, "type": "hot"},
            {"name": "蒜蓉蒸波龙", "price_fen": 48800, "type": "hot"},
            {"name": "鲍鱼焖鸡", "price_fen": 38800, "type": "hot"},
            {"name": "石斑鱼两吃", "price_fen": 38800, "type": "hot"},
            {"name": "和牛寿喜烧", "price_fen": 38800, "type": "hot"},
            {"name": "炒时蔬两道", "price_fen": 12800, "type": "vegetable"},
            {"name": "精美主食", "price_fen": 6800, "type": "staple"},
            {"name": "甜品+果盘", "price_fen": 12800, "type": "fruit"},
        ],
    },
    "anniversary": {
        "economy": [
            {"name": "精选冷菜拼盘", "price_fen": 22800, "type": "cold"},
            {"name": "清蒸鲈鱼", "price_fen": 18800, "type": "hot"},
            {"name": "鲍汁花菇", "price_fen": 22800, "type": "hot"},
            {"name": "盐焗鸡", "price_fen": 16800, "type": "hot"},
            {"name": "蒜蓉虾", "price_fen": 18800, "type": "hot"},
            {"name": "红烧肉", "price_fen": 15800, "type": "hot"},
            {"name": "炖汤", "price_fen": 22800, "type": "soup"},
            {"name": "炒时蔬", "price_fen": 8800, "type": "vegetable"},
            {"name": "纪念甜品", "price_fen": 8800, "type": "dessert"},
            {"name": "果盘", "price_fen": 5800, "type": "fruit"},
        ],
        "standard": [
            {"name": "锦绣拼盘", "price_fen": 32800, "type": "cold"},
            {"name": "清蒸石斑鱼", "price_fen": 38800, "type": "hot"},
            {"name": "鲍汁扣辽参", "price_fen": 38800, "type": "hot"},
            {"name": "脆皮烧鹅", "price_fen": 22800, "type": "hot"},
            {"name": "蒜蓉蒸波龙", "price_fen": 58800, "type": "main"},
            {"name": "避风塘炒蟹", "price_fen": 32800, "type": "hot"},
            {"name": "花胶炖鸡汤", "price_fen": 32800, "type": "soup"},
            {"name": "松茸炒芦笋", "price_fen": 12800, "type": "vegetable"},
            {"name": "定制纪念甜品", "price_fen": 12800, "type": "dessert"},
            {"name": "精选果盘", "price_fen": 8800, "type": "fruit"},
        ],
        "premium": [
            {"name": "极品海鲜拼盘", "price_fen": 58800, "type": "cold"},
            {"name": "清蒸东星斑", "price_fen": 68800, "type": "hot"},
            {"name": "鲍汁扣吉品鲍", "price_fen": 88800, "type": "hot"},
            {"name": "佛跳墙", "price_fen": 78800, "type": "soup"},
            {"name": "芝士焗澳龙", "price_fen": 118800, "type": "main"},
            {"name": "A5和牛西冷", "price_fen": 88800, "type": "hot"},
            {"name": "帝王蟹两吃", "price_fen": 88800, "type": "hot"},
            {"name": "黑松露炒时蔬", "price_fen": 18800, "type": "vegetable"},
            {"name": "法式定制甜品", "price_fen": 18800, "type": "dessert"},
            {"name": "精品水果塔", "price_fen": 12800, "type": "fruit"},
        ],
    },
}

# 场地参考配置
VENUE_TEMPLATES = {
    "small_hall": {"name": "小宴会厅", "capacity": 60, "features": ["独立空调", "投影"], "cost_fen": 200000},
    "medium_hall": {"name": "中型宴会厅", "capacity": 150, "features": ["独立空调", "投影", "LED屏", "音响"], "cost_fen": 500000},
    "large_hall": {"name": "大宴会厅", "capacity": 300, "features": ["独立空调", "投影", "LED屏", "音响", "舞台", "灯光"], "cost_fen": 1000000},
    "vip_room": {"name": "VIP包间", "capacity": 20, "features": ["独立空调", "投影", "KTV", "独立卫生间"], "cost_fen": 100000},
    "outdoor": {"name": "户外花园", "capacity": 200, "features": ["自然景观", "帐篷", "灯光"], "cost_fen": 800000},
}


def _gen_id() -> str:
    return uuid.uuid4().hex[:12].upper()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── 内存存储（生产环境替换为 DB Repository） ───

_inquiries: dict[str, dict] = {}
_proposals: dict[str, BanquetProposal] = {}
_bookings: dict[str, dict] = {}
_feedbacks: dict[str, dict] = {}
_cases: dict[str, dict] = {}


class BanquetService:
    """宴会智能管理 -- 品质正餐的核心利润引擎"""

    def __init__(self, tenant_id: str, store_id: str):
        self.tenant_id = tenant_id
        self.store_id = store_id

    # ─── 1. Lead Management (线索管理) ───

    def create_inquiry(
        self,
        customer_name: str,
        event_type: str,
        guest_count: int,
        budget_range: tuple[int, int],
        preferred_date: str,
        special_requests: Optional[str] = None,
    ) -> dict:
        """创建宴会咨询线索

        Args:
            customer_name: 客户姓名
            event_type: 宴会类型 wedding/birthday/business/team_building/anniversary
            guest_count: 预计宾客人数
            budget_range: 预算区间 (min_fen, max_fen)
            preferred_date: 首选日期 ISO格式
            special_requests: 特殊要求
        """
        if event_type not in EVENT_TYPE_CONFIG:
            raise ValueError(f"Unsupported event_type: {event_type}. "
                             f"Must be one of {list(EVENT_TYPE_CONFIG.keys())}")
        if guest_count <= 0:
            raise ValueError("guest_count must be positive")
        if budget_range[0] > budget_range[1]:
            raise ValueError("budget_range min must not exceed max")

        inquiry_id = f"INQ-{_gen_id()}"
        config = EVENT_TYPE_CONFIG[event_type]

        # 自动计算桌数 (标准10人/桌)
        table_count = (guest_count + 9) // 10

        inquiry = {
            "inquiry_id": inquiry_id,
            "tenant_id": self.tenant_id,
            "store_id": self.store_id,
            "customer_name": customer_name,
            "event_type": event_type,
            "event_type_name": config["name"],
            "guest_count": guest_count,
            "table_count": table_count,
            "budget_range_fen": list(budget_range),
            "budget_per_head_fen": budget_range[1] // guest_count if guest_count else 0,
            "preferred_date": preferred_date,
            "special_requests": special_requests,
            "status": "new",  # new -> contacted -> proposal_sent -> confirmed -> cancelled
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "follow_up_notes": [],
        }

        _inquiries[inquiry_id] = inquiry
        logger.info("banquet_inquiry_created", inquiry_id=inquiry_id,
                     event_type=event_type, guest_count=guest_count)
        return inquiry

    def list_inquiries(
        self,
        store_id: Optional[str] = None,
        status: Optional[str] = None,
        date_range: Optional[tuple[str, str]] = None,
    ) -> list[dict]:
        """列出宴会咨询线索"""
        target_store = store_id or self.store_id
        results = []
        for inq in _inquiries.values():
            if inq["tenant_id"] != self.tenant_id:
                continue
            if inq["store_id"] != target_store:
                continue
            if status and inq["status"] != status:
                continue
            if date_range:
                if inq["preferred_date"] < date_range[0] or inq["preferred_date"] > date_range[1]:
                    continue
            results.append(inq)

        results.sort(key=lambda x: x["preferred_date"])
        return results

    # ─── 2. AI Proposal (AI方案推荐) ───

    def generate_proposal(
        self,
        inquiry_id: str,
        guest_count: int,
        budget_per_head_fen: int,
        event_type: str,
        dietary_restrictions: Optional[list[str]] = None,
    ) -> BanquetProposal:
        """AI 智能生成宴会方案

        根据预算、人数、宴会类型自动推荐三档方案，含菜单、场地、装饰、服务方案。
        """
        if event_type not in EVENT_TYPE_CONFIG:
            raise ValueError(f"Unsupported event_type: {event_type}")

        config = EVENT_TYPE_CONFIG[event_type]
        dietary_restrictions = dietary_restrictions or []

        # 构建三档方案
        tiers = []
        for tier_name in ["economy", "standard", "premium"]:
            tier_price = TIER_PRICING[tier_name].get(event_type, 68800)
            menu_items = MENU_TEMPLATES.get(event_type, {}).get(tier_name, [])

            # 如果有饮食禁忌，过滤并标注
            filtered_menu = []
            for item in menu_items:
                flagged = False
                for restriction in dietary_restrictions:
                    if restriction.lower() in item["name"].lower():
                        flagged = True
                        break
                filtered_menu.append({
                    **item,
                    "flagged_dietary": flagged,
                    "substitute_available": flagged,
                })

            tier_total_fen = tier_price * guest_count
            tiers.append({
                "tier": tier_name,
                "tier_name": {"economy": "经济档", "standard": "标准档", "premium": "豪华档"}[tier_name],
                "price_per_head_fen": tier_price,
                "total_fen": tier_total_fen,
                "menu": filtered_menu,
                "course_count": len(filtered_menu),
                "recommended": tier_name == "standard",
            })

        # 推荐场地
        if guest_count <= 20:
            venue_key = "vip_room"
        elif guest_count <= 60:
            venue_key = "small_hall"
        elif guest_count <= 150:
            venue_key = "medium_hall"
        else:
            venue_key = "large_hall"
        venue = {**VENUE_TEMPLATES[venue_key], "venue_key": venue_key}

        # 装饰方案
        decoration_items = config["decoration_items"]
        decoration_cost_per_table = 15000  # 150元/桌
        table_count = (guest_count + 9) // 10
        decoration = {
            "theme": config["theme_color"],
            "items": decoration_items,
            "table_count": table_count,
            "cost_fen": decoration_cost_per_table * table_count + 50000,  # 基础费 500元
        }

        # 服务人力方案
        waiter_count = max(2, guest_count // 15)  # 1个服务员服务15位客人
        chef_count = max(2, guest_count // 25)    # 1个厨师服务25位客人
        service_plan = {
            "waiters": waiter_count,
            "chefs": chef_count,
            "coordinator": 1,
            "extras": config.get("service_extras", []),
            "labor_cost_fen": (waiter_count * 30000 + chef_count * 50000 + 80000),  # 服务员300/厨师500/协调800
        }

        # 成本测算（使用标准档作为基准）
        std_tier = tiers[1]  # standard
        food_cost_rate = 0.35  # 食材成本率35%
        food_cost_fen = int(std_tier["total_fen"] * food_cost_rate)

        cost_breakdown = {
            "food_cost_fen": food_cost_fen,
            "labor_cost_fen": service_plan["labor_cost_fen"],
            "venue_cost_fen": venue["cost_fen"],
            "decoration_cost_fen": decoration["cost_fen"],
            "misc_cost_fen": int(std_tier["total_fen"] * 0.05),  # 杂项5%
        }
        total_cost = sum(cost_breakdown.values())
        estimated_total = std_tier["total_fen"]
        margin_rate = (estimated_total - total_cost) / estimated_total if estimated_total > 0 else 0

        # 匹配历史成功案例
        similar_cases = self._find_similar_cases(event_type, guest_count, budget_per_head_fen)

        # 置信度 — 基于历史数据量
        confidence = min(0.95, 0.7 + len(similar_cases) * 0.05)

        proposal_id = f"PRP-{_gen_id()}"
        proposal = BanquetProposal(
            proposal_id=proposal_id,
            event_type=event_type,
            guest_count=guest_count,
            tiers=tiers,
            venue=venue,
            decoration=decoration,
            service_plan=service_plan,
            cost_breakdown=cost_breakdown,
            estimated_total=estimated_total,
            margin_rate=round(margin_rate, 4),
            confidence=confidence,
            similar_cases=similar_cases,
        )

        _proposals[proposal_id] = proposal

        # 更新线索状态
        if inquiry_id in _inquiries:
            _inquiries[inquiry_id]["status"] = "proposal_sent"
            _inquiries[inquiry_id]["proposal_id"] = proposal_id
            _inquiries[inquiry_id]["updated_at"] = _now_iso()

        logger.info("banquet_proposal_generated", proposal_id=proposal_id,
                     event_type=event_type, guest_count=guest_count,
                     margin_rate=round(margin_rate, 4))
        return proposal

    def _find_similar_cases(self, event_type: str, guest_count: int, budget_fen: int) -> list[dict]:
        """从历史案例中找到相似案例"""
        similar = []
        for case in _cases.values():
            if case.get("event_type") != event_type:
                continue
            gc = case.get("guest_count", 0)
            if abs(gc - guest_count) <= guest_count * 0.3:
                similar.append({
                    "case_id": case["case_id"],
                    "event_type": case["event_type"],
                    "guest_count": gc,
                    "satisfaction_score": case.get("satisfaction_score", 0),
                    "highlights": case.get("highlights", []),
                })
        # 返回最相似的3个
        return sorted(similar, key=lambda x: x.get("satisfaction_score", 0), reverse=True)[:3]

    # ─── 3. Cost Estimation (成本实时测算) ───

    def estimate_cost(self, proposal_id: str) -> BanquetCostEstimate:
        """根据方案ID实时测算成本与利润"""
        proposal = _proposals.get(proposal_id)
        if not proposal:
            raise ValueError(f"Proposal not found: {proposal_id}")

        cb = proposal.cost_breakdown
        food_cost = cb.get("food_cost_fen", 0)
        labor_cost = cb.get("labor_cost_fen", 0)
        venue_cost = cb.get("venue_cost_fen", 0)
        decoration_cost = cb.get("decoration_cost_fen", 0)
        misc_cost = cb.get("misc_cost_fen", 0)

        # 酒水成本 — 估算人均50元
        beverage_cost = proposal.guest_count * 5000

        total_cost = food_cost + labor_cost + venue_cost + decoration_cost + beverage_cost + misc_cost
        revenue = proposal.estimated_total + beverage_cost  # 酒水额外收入（加价率100%）
        margin_fen = revenue - total_cost
        margin_rate = margin_fen / revenue if revenue > 0 else 0

        estimate = BanquetCostEstimate(
            proposal_id=proposal_id,
            food_cost_fen=food_cost,
            labor_cost_fen=labor_cost,
            venue_cost_fen=venue_cost,
            decoration_cost_fen=decoration_cost,
            beverage_cost_fen=beverage_cost,
            misc_cost_fen=misc_cost,
            total_cost_fen=total_cost,
            estimated_revenue_fen=revenue,
            estimated_margin_fen=margin_fen,
            margin_rate=round(margin_rate, 4),
        )

        logger.info("banquet_cost_estimated", proposal_id=proposal_id,
                     total_cost_fen=total_cost, margin_rate=round(margin_rate, 4))
        return estimate

    # ─── 4. Contract & Confirmation ───

    def confirm_booking(
        self,
        inquiry_id: str,
        proposal_id: str,
        deposit_amount_fen: int,
        final_menu: list[dict],
        special_notes: Optional[str] = None,
    ) -> dict:
        """确认宴会预订 — 生成合同"""
        inquiry = _inquiries.get(inquiry_id)
        if not inquiry:
            raise ValueError(f"Inquiry not found: {inquiry_id}")

        proposal = _proposals.get(proposal_id)
        if not proposal:
            raise ValueError(f"Proposal not found: {proposal_id}")

        # 校验定金 — 最低为预估总价的 20%
        min_deposit = int(proposal.estimated_total * 0.2)
        if deposit_amount_fen < min_deposit:
            raise ValueError(
                f"Deposit {deposit_amount_fen} fen below minimum {min_deposit} fen (20% of total)"
            )

        booking_id = f"BKG-{_gen_id()}"

        # 计算最终菜品总价
        menu_total_fen = sum(item.get("price_fen", 0) * item.get("quantity", 1) for item in final_menu)

        booking = {
            "booking_id": booking_id,
            "tenant_id": self.tenant_id,
            "store_id": self.store_id,
            "inquiry_id": inquiry_id,
            "proposal_id": proposal_id,
            "customer_name": inquiry["customer_name"],
            "event_type": proposal.event_type,
            "event_date": inquiry["preferred_date"],
            "guest_count": proposal.guest_count,
            "table_count": inquiry["table_count"],
            "final_menu": final_menu,
            "menu_total_fen": menu_total_fen,
            "venue": asdict(proposal) if isinstance(proposal, BanquetProposal) else proposal.venue,
            "decoration": proposal.decoration,
            "service_plan": proposal.service_plan,
            "deposit_amount_fen": deposit_amount_fen,
            "deposit_paid": True,
            "estimated_total_fen": proposal.estimated_total,
            "special_notes": special_notes,
            "status": "confirmed",  # confirmed -> preparing -> executing -> completed -> settled
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        # Fix: store only venue dict, not full proposal
        booking["venue"] = proposal.venue

        _bookings[booking_id] = booking

        # 更新线索状态
        inquiry["status"] = "confirmed"
        inquiry["booking_id"] = booking_id
        inquiry["updated_at"] = _now_iso()

        logger.info("banquet_booking_confirmed", booking_id=booking_id,
                     event_type=proposal.event_type, guest_count=proposal.guest_count,
                     deposit_fen=deposit_amount_fen)
        return booking

    def update_booking_status(self, booking_id: str, status: str) -> dict:
        """更新宴会预订状态"""
        valid_statuses = ["confirmed", "preparing", "executing", "completed", "settled", "cancelled"]
        if status not in valid_statuses:
            raise ValueError(f"Invalid status: {status}. Must be one of {valid_statuses}")

        booking = _bookings.get(booking_id)
        if not booking:
            raise ValueError(f"Booking not found: {booking_id}")

        old_status = booking["status"]
        booking["status"] = status
        booking["updated_at"] = _now_iso()

        logger.info("banquet_status_updated", booking_id=booking_id,
                     old_status=old_status, new_status=status)
        return {"booking_id": booking_id, "old_status": old_status, "new_status": status}

    # ─── 5. Execution Checklist (宴会执行检查清单) ───

    def generate_execution_checklist(self, booking_id: str) -> list[dict]:
        """生成宴会执行检查清单 — T-7 到 T+1 全流程"""
        booking = _bookings.get(booking_id)
        if not booking:
            raise ValueError(f"Booking not found: {booking_id}")

        event_type = booking["event_type"]
        config = EVENT_TYPE_CONFIG.get(event_type, {})
        guest_count = booking["guest_count"]

        checklist = [
            # T-7: 筹备启动
            {
                "phase": "T-7",
                "phase_name": "筹备启动",
                "items": [
                    {"task": "食材预订确认 — 高端食材(龙虾/鲍鱼/帝王蟹)提前锁定供应商", "responsible": "采购主管", "status": "pending", "required": True},
                    {"task": "人力排班确认 — 确认服务员/厨师/协调员排班到位", "responsible": "前厅经理", "status": "pending", "required": True},
                    {"task": "场地布置方案确认 — 与客户确认最终装饰方案和布局图", "responsible": "宴会经理", "status": "pending", "required": True},
                    {"task": "设备检查 — LED屏/音响/灯光/投影设备预约和检测", "responsible": "工程部", "status": "pending", "required": True},
                    {"task": "客户确认 — 电话确认最终人数、菜单、特殊需求", "responsible": "宴会经理", "status": "pending", "required": True},
                    {"task": "酒水备货 — 根据预算和人数准备酒水饮料", "responsible": "吧台主管", "status": "pending", "required": False},
                ],
            },
            # T-3: 物料到位
            {
                "phase": "T-3",
                "phase_name": "物料到位",
                "items": [
                    {"task": f"食材到货验收 — 检查{guest_count}位宾客所需食材新鲜度和数量", "responsible": "采购主管", "status": "pending", "required": True},
                    {"task": "特殊器材准备 — 装饰物料/鲜花/气球/横幅到位", "responsible": "宴会经理", "status": "pending", "required": True},
                    {"task": "餐具清点 — 确认足够的碗碟杯筷（含备用10%）", "responsible": "前厅领班", "status": "pending", "required": True},
                    {"task": "菜品试做 — 主要菜品预制准备和试味", "responsible": "行政总厨", "status": "pending", "required": True},
                    {"task": "活鲜入池 — 活海鲜入养殖池暂养", "responsible": "海鲜池管理员", "status": "pending", "required": event_type in ("wedding", "business", "anniversary")},
                ],
            },
            # T-1: 彩排准备
            {
                "phase": "T-1",
                "phase_name": "彩排准备",
                "items": [
                    {"task": "场地布置 — 按方案完成桌椅/装饰/灯光/音响布置", "responsible": "宴会经理", "status": "pending", "required": True},
                    {"task": "灯光音响测试 — 全流程灯光音响走一遍", "responsible": "工程部", "status": "pending", "required": True},
                    {"task": "服务流程彩排 — 全体服务人员走位演练", "responsible": "前厅经理", "status": "pending", "required": True},
                    {"task": "菜品预制 — 可提前预制的菜品开始准备", "responsible": "行政总厨", "status": "pending", "required": True},
                    {"task": "客户最终确认 — 确认最终到场人数和座位安排", "responsible": "宴会经理", "status": "pending", "required": True},
                ],
            },
            # T-0: 宴会当天
            {
                "phase": "T-0",
                "phase_name": "宴会当天",
                "items": [
                    {"task": "场地最终检查 — 开场前2小时全面检查", "responsible": "宴会经理", "status": "pending", "required": True},
                    {"task": "迎宾准备 — 签到台/引导牌/迎宾花篮就位", "responsible": "前厅领班", "status": "pending", "required": True},
                    {"task": "迎宾 — 引导宾客入座、发放伴手礼", "responsible": "服务团队", "status": "pending", "required": True},
                    {"task": "开场仪式 — 按流程执行(婚礼仪式/祝寿/致辞等)", "responsible": "宴会协调员", "status": "pending", "required": True},
                    {"task": "上菜 — 按顺序上菜：冷盘→热菜→主菜→汤→甜品→水果", "responsible": "传菜组", "status": "pending", "required": True},
                    {"task": "祝酒/互动环节 — 协助敬酒、游戏互动", "responsible": "宴会协调员", "status": "pending", "required": event_type in ("wedding", "birthday", "team_building")},
                    {"task": "甜品/蛋糕环节 — 切蛋糕、甜品台开放", "responsible": "甜品师", "status": "pending", "required": event_type in ("wedding", "birthday", "anniversary")},
                    {"task": "送客 — 客户致谢、伴手礼分发、合影留念", "responsible": "宴会经理", "status": "pending", "required": True},
                    {"task": "现场拆除与清洁 — 宴会结束后30分钟内开始", "responsible": "保洁组", "status": "pending", "required": True},
                ],
            },
            # T+1: 结算复盘
            {
                "phase": "T+1",
                "phase_name": "结算复盘",
                "items": [
                    {"task": "费用结算 — 核对最终费用、收取尾款", "responsible": "财务", "status": "pending", "required": True},
                    {"task": "客户回访 — 24小时内电话/微信回访，收集满意度", "responsible": "宴会经理", "status": "pending", "required": True},
                    {"task": "案例沉淀 — 整理照片/视频/数据，归档为案例", "responsible": "宴会经理", "status": "pending", "required": False},
                    {"task": "团队复盘 — 总结亮点和改进点", "responsible": "店长", "status": "pending", "required": False},
                    {"task": "物料盘点 — 清点剩余物料、计算损耗", "responsible": "采购主管", "status": "pending", "required": True},
                ],
            },
        ]

        # 更新预订状态
        booking["status"] = "preparing"
        booking["checklist"] = checklist
        booking["updated_at"] = _now_iso()

        logger.info("banquet_checklist_generated", booking_id=booking_id,
                     total_phases=len(checklist),
                     total_items=sum(len(phase["items"]) for phase in checklist))
        return checklist

    # ─── 6. Post-Event ───

    def settle_banquet(
        self,
        booking_id: str,
        actual_guest_count: int,
        additional_charges: Optional[list[dict]] = None,
    ) -> dict:
        """宴会结算

        Args:
            booking_id: 预订ID
            actual_guest_count: 实际到场人数
            additional_charges: 额外费用 [{"item": "加菜", "amount_fen": 15800}, ...]
        """
        booking = _bookings.get(booking_id)
        if not booking:
            raise ValueError(f"Booking not found: {booking_id}")

        additional_charges = additional_charges or []
        additional_total = sum(c.get("amount_fen", 0) for c in additional_charges)

        # 根据实际人数调整
        planned_count = booking["guest_count"]
        count_diff = actual_guest_count - planned_count

        # 如果实际人数少于预订人数的80%，按80%收费
        billing_count = max(actual_guest_count, int(planned_count * 0.8))

        # 计算应收
        per_head = booking["estimated_total_fen"] // planned_count if planned_count > 0 else 0
        base_total = per_head * billing_count
        final_total = base_total + additional_total
        balance_due = final_total - booking["deposit_amount_fen"]

        settlement = {
            "booking_id": booking_id,
            "planned_guest_count": planned_count,
            "actual_guest_count": actual_guest_count,
            "billing_guest_count": billing_count,
            "count_diff": count_diff,
            "per_head_fen": per_head,
            "base_total_fen": base_total,
            "additional_charges": additional_charges,
            "additional_total_fen": additional_total,
            "final_total_fen": final_total,
            "deposit_paid_fen": booking["deposit_amount_fen"],
            "balance_due_fen": balance_due,
            "settled_at": _now_iso(),
        }

        booking["status"] = "settled"
        booking["settlement"] = settlement
        booking["updated_at"] = _now_iso()

        logger.info("banquet_settled", booking_id=booking_id,
                     final_total_fen=final_total, balance_due_fen=balance_due)
        return settlement

    def collect_feedback(
        self,
        booking_id: str,
        satisfaction_score: int,
        feedback_text: str,
    ) -> dict:
        """收集宴会客户反馈

        Args:
            satisfaction_score: 1-10 满意度评分
            feedback_text: 客户反馈文本
        """
        booking = _bookings.get(booking_id)
        if not booking:
            raise ValueError(f"Booking not found: {booking_id}")

        if not 1 <= satisfaction_score <= 10:
            raise ValueError("satisfaction_score must be between 1 and 10")

        feedback_id = f"FB-{_gen_id()}"
        feedback = {
            "feedback_id": feedback_id,
            "booking_id": booking_id,
            "customer_name": booking["customer_name"],
            "event_type": booking["event_type"],
            "satisfaction_score": satisfaction_score,
            "satisfaction_level": (
                "excellent" if satisfaction_score >= 9 else
                "good" if satisfaction_score >= 7 else
                "average" if satisfaction_score >= 5 else
                "poor"
            ),
            "feedback_text": feedback_text,
            "collected_at": _now_iso(),
        }

        _feedbacks[feedback_id] = feedback
        booking["feedback_id"] = feedback_id
        booking["updated_at"] = _now_iso()

        logger.info("banquet_feedback_collected", booking_id=booking_id,
                     score=satisfaction_score)
        return feedback

    def archive_as_case(
        self,
        booking_id: str,
        photos: list[str],
        highlights: list[str],
    ) -> dict:
        """将宴会归档为案例 — 用于AI方案推荐参考"""
        booking = _bookings.get(booking_id)
        if not booking:
            raise ValueError(f"Booking not found: {booking_id}")

        feedback = None
        if "feedback_id" in booking:
            feedback = _feedbacks.get(booking["feedback_id"])

        case_id = f"CASE-{_gen_id()}"
        case = {
            "case_id": case_id,
            "booking_id": booking_id,
            "tenant_id": self.tenant_id,
            "store_id": self.store_id,
            "customer_name": booking["customer_name"],
            "event_type": booking["event_type"],
            "event_date": booking["event_date"],
            "guest_count": booking["guest_count"],
            "final_menu": booking["final_menu"],
            "venue": booking["venue"],
            "decoration": booking["decoration"],
            "settlement": booking.get("settlement"),
            "satisfaction_score": feedback["satisfaction_score"] if feedback else None,
            "feedback_text": feedback["feedback_text"] if feedback else None,
            "photos": photos,
            "highlights": highlights,
            "archived_at": _now_iso(),
        }

        _cases[case_id] = case
        booking["case_id"] = case_id
        booking["updated_at"] = _now_iso()

        logger.info("banquet_case_archived", case_id=case_id, booking_id=booking_id,
                     event_type=booking["event_type"])
        return case
