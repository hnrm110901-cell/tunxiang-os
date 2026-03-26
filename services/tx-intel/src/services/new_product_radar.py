"""新品/新原料雷达 — 帮助菜研从拍脑袋到有情报有适配有试点

跟踪市场热门菜品/食材/做法趋势，评估与品牌的适配度，
推荐试点门店，创建试点计划并跟踪效果。
"""
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

import structlog

logger = structlog.get_logger()


# ─── 常量 ───

OPPORTUNITY_STATUSES = ["discovered", "evaluating", "approved", "piloting",
                        "scaling", "rejected", "archived"]

OPPORTUNITY_CATEGORIES = [
    "trending_dish", "trending_ingredient", "new_cooking_method",
    "regional_specialty", "seasonal_item", "fusion_innovation",
    "health_trend", "dessert_innovation",
]

# ─── 门店候选池（用于试点推荐） ───

_STORE_POOL: list[dict] = [
    {"store_id": "S001", "name": "芙蓉路旗舰店", "city": "长沙", "type": "flagship", "monthly_traffic": 12000, "avg_check_fen": 7800, "innovation_score": 0.9},
    {"store_id": "S002", "name": "五一广场店", "city": "长沙", "type": "standard", "monthly_traffic": 9500, "avg_check_fen": 7200, "innovation_score": 0.7},
    {"store_id": "S003", "name": "梅溪湖店", "city": "长沙", "type": "standard", "monthly_traffic": 7000, "avg_check_fen": 7000, "innovation_score": 0.8},
    {"store_id": "S005", "name": "南山科技园店", "city": "深圳", "type": "flagship", "monthly_traffic": 11000, "avg_check_fen": 8500, "innovation_score": 0.85},
    {"store_id": "S006", "name": "福田CBD店", "city": "深圳", "type": "premium", "monthly_traffic": 8000, "avg_check_fen": 9200, "innovation_score": 0.75},
    {"store_id": "S010", "name": "天河城店", "city": "广州", "type": "standard", "monthly_traffic": 8500, "avg_check_fen": 7600, "innovation_score": 0.7},
    {"store_id": "S015", "name": "光谷店", "city": "武汉", "type": "standard", "monthly_traffic": 6500, "avg_check_fen": 6800, "innovation_score": 0.65},
]


# ─── 种子数据 ───

_SEED_OPPORTUNITIES: list[dict] = [
    {
        "name": "酸汤火锅",
        "category": "trending_dish",
        "source": "社交媒体趋势+竞对动态",
        "description": "酸汤火锅2025年下半年起持续走红，贵州酸汤+火锅形态创新，"
                       "抖音相关话题播放超50亿。适合湘菜品牌延伸品类。",
        "market_heat_score": 0.95,
        "brand_fit_score": 0.75,
        "audience_fit_score": 0.85,
        "cost_feasibility_score": 0.70,
    },
    {
        "name": "潮汕牛肉火锅",
        "category": "trending_dish",
        "source": "市场调研",
        "description": "潮汕牛肉火锅强调现切现涮，品质感强。一线城市已形成独立品类，"
                       "二三线城市仍有空间。需要稳定牛肉供应链。",
        "market_heat_score": 0.80,
        "brand_fit_score": 0.55,
        "audience_fit_score": 0.70,
        "cost_feasibility_score": 0.60,
    },
    {
        "name": "日式烧鸟",
        "category": "trending_dish",
        "source": "社交媒体趋势",
        "description": "日式烧鸟（yakitori）在一线城市年轻群体中爆火，"
                       "单店模型轻、翻台率高。与湘菜品牌可做跨品类副线。",
        "market_heat_score": 0.88,
        "brand_fit_score": 0.40,
        "audience_fit_score": 0.75,
        "cost_feasibility_score": 0.80,
    },
    {
        "name": "贵州酸汤鱼",
        "category": "regional_specialty",
        "source": "竞对动态+消费反馈",
        "description": "贵州酸汤鱼与湘菜品牌高度契合，酸辣口味与湘菜调性一致。"
                       "费大厨已上线酸汤系列，需要快速跟进。",
        "market_heat_score": 0.85,
        "brand_fit_score": 0.90,
        "audience_fit_score": 0.88,
        "cost_feasibility_score": 0.85,
    },
    {
        "name": "云南菌菇",
        "category": "seasonal_item",
        "source": "供应链情报",
        "description": "云南野生菌菇6-9月应季，高端食材形象，"
                       "菌菇火锅/菌菇煲汤在养生趋势下热度持续上升。",
        "market_heat_score": 0.78,
        "brand_fit_score": 0.80,
        "audience_fit_score": 0.82,
        "cost_feasibility_score": 0.55,
    },
    {
        "name": "低温慢煮牛排",
        "category": "new_cooking_method",
        "source": "行业展会",
        "description": "Sous vide低温慢煮技术应用于中餐，牛排嫩度和一致性好。"
                       "设备投入不大，但需要厨师培训。",
        "market_heat_score": 0.65,
        "brand_fit_score": 0.50,
        "audience_fit_score": 0.60,
        "cost_feasibility_score": 0.75,
    },
    {
        "name": "鲜花饼",
        "category": "regional_specialty",
        "source": "消费者反馈",
        "description": "鲜花饼从云南特产变为全国网红甜点，"
                       "适合作为餐后甜点或伴手礼，提升客单价。",
        "market_heat_score": 0.60,
        "brand_fit_score": 0.45,
        "audience_fit_score": 0.65,
        "cost_feasibility_score": 0.90,
    },
    {
        "name": "小龙虾新做法",
        "category": "fusion_innovation",
        "source": "社交媒体趋势",
        "description": "小龙虾+各地风味（酸汤小龙虾、椰香小龙虾、冬阴功小龙虾），"
                       "季节性爆品，5-9月旺季。湘式口味虾是强项可延伸。",
        "market_heat_score": 0.82,
        "brand_fit_score": 0.88,
        "audience_fit_score": 0.90,
        "cost_feasibility_score": 0.70,
    },
    {
        "name": "预制菜升级版",
        "category": "fusion_innovation",
        "source": "行业趋势",
        "description": "消费者对预制菜排斥情绪上升，但'高端预制菜'和'厨师现制+预制辅助'模式"
                       "被接受度高。可用于外卖和零售渠道。",
        "market_heat_score": 0.55,
        "brand_fit_score": 0.60,
        "audience_fit_score": 0.50,
        "cost_feasibility_score": 0.85,
    },
    {
        "name": "分子料理甜品",
        "category": "dessert_innovation",
        "source": "行业展会",
        "description": "分子料理技术应用于甜品，视觉效果惊艳，适合社交媒体传播。"
                       "技术门槛高，但差异化明显。",
        "market_heat_score": 0.70,
        "brand_fit_score": 0.35,
        "audience_fit_score": 0.72,
        "cost_feasibility_score": 0.40,
    },
]


# ─── 数据模型 ───

@dataclass
class Opportunity:
    """新品/新原料机会"""
    opportunity_id: str
    name: str
    category: str
    source: str
    description: str
    status: str = "discovered"
    market_heat_score: float = 0.0
    brand_fit_score: float = 0.0
    audience_fit_score: float = 0.0
    cost_feasibility_score: float = 0.0
    supply_stability_score: float = 0.5
    overall_score: float = 0.0
    created_at: str = ""
    updated_at: str = ""


@dataclass
class PilotPlan:
    """试点计划"""
    plan_id: str
    opportunity_id: str
    stores: list[str]
    period_days: int
    metrics: list[str]
    status: str = "planned"
    start_date: str = ""
    results: dict = field(default_factory=dict)
    created_at: str = ""


class NewProductRadar:
    """新品/新原料雷达 — 帮助菜研从拍脑袋到有情报有适配有试点"""

    # 评分权重
    SCORE_WEIGHTS = {
        "market_heat": 0.25,
        "brand_fit": 0.25,
        "audience_fit": 0.20,
        "cost_feasibility": 0.15,
        "supply_stability": 0.15,
    }

    def __init__(self) -> None:
        self._opportunities: dict[str, Opportunity] = {}
        self._pilot_plans: dict[str, PilotPlan] = {}
        self._load_seed_data()

    def _load_seed_data(self) -> None:
        for seed in _SEED_OPPORTUNITIES:
            self.register_opportunity(
                name=seed["name"],
                category=seed["category"],
                source=seed["source"],
                description=seed["description"],
                market_heat_score=seed["market_heat_score"],
                brand_fit_score=seed["brand_fit_score"],
                audience_fit_score=seed["audience_fit_score"],
                cost_feasibility_score=seed["cost_feasibility_score"],
            )
        logger.info("new_product_radar_seed_loaded", opportunities=len(self._opportunities))

    # ─── 机会管理 ───

    def register_opportunity(
        self,
        name: str,
        category: str,
        source: str,
        description: str,
        market_heat_score: float = 0.0,
        brand_fit_score: float = 0.0,
        audience_fit_score: float = 0.0,
        cost_feasibility_score: float = 0.0,
    ) -> dict:
        """注册新品/新原料机会"""
        oid = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc).isoformat()
        opp = Opportunity(
            opportunity_id=oid,
            name=name,
            category=category,
            source=source,
            description=description,
            market_heat_score=market_heat_score,
            brand_fit_score=brand_fit_score,
            audience_fit_score=audience_fit_score,
            cost_feasibility_score=cost_feasibility_score,
            created_at=now,
            updated_at=now,
        )
        opp.overall_score = self._compute_score(opp)
        self._opportunities[oid] = opp
        return {
            "opportunity_id": oid,
            "name": name,
            "overall_score": opp.overall_score,
            "status": "discovered",
        }

    def list_opportunities(
        self,
        status: Optional[str] = None,
        category: Optional[str] = None,
        sort_by: str = "score",
    ) -> list[dict]:
        """列出机会"""
        results = []
        for o in self._opportunities.values():
            if status and o.status != status:
                continue
            if category and o.category != category:
                continue
            results.append({
                "opportunity_id": o.opportunity_id,
                "name": o.name,
                "category": o.category,
                "status": o.status,
                "overall_score": o.overall_score,
                "market_heat_score": o.market_heat_score,
                "brand_fit_score": o.brand_fit_score,
                "source": o.source,
            })

        if sort_by == "score":
            results.sort(key=lambda x: x["overall_score"], reverse=True)
        elif sort_by == "market_heat":
            results.sort(key=lambda x: x["market_heat_score"], reverse=True)
        return results

    def get_opportunity_detail(self, opportunity_id: str) -> dict:
        """获取机会详情"""
        o = self._opportunities.get(opportunity_id)
        if not o:
            raise KeyError(f"Opportunity not found: {opportunity_id}")
        pilots = [p for p in self._pilot_plans.values() if p.opportunity_id == opportunity_id]
        return {
            "opportunity_id": o.opportunity_id,
            "name": o.name,
            "category": o.category,
            "source": o.source,
            "description": o.description,
            "status": o.status,
            "scores": {
                "market_heat": o.market_heat_score,
                "brand_fit": o.brand_fit_score,
                "audience_fit": o.audience_fit_score,
                "cost_feasibility": o.cost_feasibility_score,
                "supply_stability": o.supply_stability_score,
                "overall": o.overall_score,
            },
            "pilot_plans": [
                {"plan_id": p.plan_id, "status": p.status, "stores": p.stores}
                for p in pilots
            ],
            "created_at": o.created_at,
        }

    # ─── 评分 ───

    def _compute_score(self, opp: Opportunity) -> float:
        """计算综合评分"""
        w = self.SCORE_WEIGHTS
        score = (
            opp.market_heat_score * w["market_heat"]
            + opp.brand_fit_score * w["brand_fit"]
            + opp.audience_fit_score * w["audience_fit"]
            + opp.cost_feasibility_score * w["cost_feasibility"]
            + opp.supply_stability_score * w["supply_stability"]
        )
        return round(score, 3)

    def score_opportunity(self, opportunity_id: str) -> dict:
        """计算/更新机会评分"""
        o = self._opportunities.get(opportunity_id)
        if not o:
            raise KeyError(f"Opportunity not found: {opportunity_id}")
        o.overall_score = self._compute_score(o)
        o.updated_at = datetime.now(timezone.utc).isoformat()

        recommendation = "强烈推荐试点" if o.overall_score >= 0.75 else (
            "建议评估" if o.overall_score >= 0.55 else "暂不推荐"
        )

        return {
            "opportunity_id": opportunity_id,
            "name": o.name,
            "scores": {
                "market_heat": o.market_heat_score,
                "brand_fit": o.brand_fit_score,
                "audience_fit": o.audience_fit_score,
                "cost_feasibility": o.cost_feasibility_score,
                "supply_stability": o.supply_stability_score,
                "overall": o.overall_score,
            },
            "weights": self.SCORE_WEIGHTS,
            "recommendation": recommendation,
        }

    # ─── 试点推荐 ───

    def recommend_pilot_stores(self, opportunity_id: str) -> list[dict]:
        """推荐试点门店"""
        o = self._opportunities.get(opportunity_id)
        if not o:
            raise KeyError(f"Opportunity not found: {opportunity_id}")

        scored_stores = []
        for store in _STORE_POOL:
            # 旗舰店和创新分数高的优先
            fit_score = store["innovation_score"] * 0.4 + (store["monthly_traffic"] / 15000) * 0.3
            if store["type"] == "flagship":
                fit_score += 0.2
            if store["type"] == "premium" and o.market_heat_score > 0.8:
                fit_score += 0.1
            scored_stores.append({
                "store_id": store["store_id"],
                "store_name": store["name"],
                "city": store["city"],
                "store_type": store["type"],
                "monthly_traffic": store["monthly_traffic"],
                "fit_score": round(fit_score, 2),
                "reason": self._pilot_reason(store, o),
            })

        scored_stores.sort(key=lambda x: x["fit_score"], reverse=True)
        return scored_stores[:3]

    def _pilot_reason(self, store: dict, opp: Opportunity) -> str:
        """生成试点推荐理由"""
        reasons = []
        if store["type"] == "flagship":
            reasons.append("旗舰店影响力大")
        if store["innovation_score"] >= 0.8:
            reasons.append("创新接受度高")
        if store["monthly_traffic"] >= 10000:
            reasons.append("客流量充足有数据基础")
        if not reasons:
            reasons.append("运营稳定适合验证")
        return "，".join(reasons)

    # ─── 试点计划 ───

    def create_pilot_plan(
        self,
        opportunity_id: str,
        stores: list[str],
        period_days: int,
        metrics: list[str],
    ) -> dict:
        """创建试点计划"""
        o = self._opportunities.get(opportunity_id)
        if not o:
            raise KeyError(f"Opportunity not found: {opportunity_id}")

        plan_id = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc)
        plan = PilotPlan(
            plan_id=plan_id,
            opportunity_id=opportunity_id,
            stores=stores,
            period_days=period_days,
            metrics=metrics,
            status="planned",
            start_date=(now + timedelta(days=3)).strftime("%Y-%m-%d"),
            created_at=now.isoformat(),
        )
        self._pilot_plans[plan_id] = plan
        o.status = "piloting"
        o.updated_at = now.isoformat()

        return {
            "plan_id": plan_id,
            "opportunity_name": o.name,
            "stores": stores,
            "period_days": period_days,
            "metrics": metrics,
            "start_date": plan.start_date,
            "status": "planned",
        }

    # ─── 食材趋势 ───

    def track_ingredient_trends(self, days: int = 90) -> list[dict]:
        """追踪食材趋势"""
        trends = [
            {"ingredient": "贵州红酸汤", "category": "调味料", "trend": "rising",
             "heat_score": 0.92, "note": "酸汤火锅/酸汤鱼带动，工业化生产成熟"},
            {"ingredient": "云南松茸", "category": "菌菇", "trend": "seasonal_peak",
             "heat_score": 0.85, "note": "7-9月应季，高端餐饮标配"},
            {"ingredient": "湘西腊肉", "category": "腌腊制品", "trend": "stable",
             "heat_score": 0.70, "note": "传统食材，品质升级需求增加"},
            {"ingredient": "紫苏", "category": "香料", "trend": "rising",
             "heat_score": 0.68, "note": "紫苏系列菜品在社交媒体走红"},
            {"ingredient": "藤椒", "category": "调味料", "trend": "rising",
             "heat_score": 0.80, "note": "藤椒味型持续流行，年轻消费者偏好"},
            {"ingredient": "黑松露", "category": "高端食材", "trend": "stable",
             "heat_score": 0.55, "note": "高端菜品点缀，国产替代价格下降"},
            {"ingredient": "螺蛳粉调味", "category": "调味料", "trend": "declining",
             "heat_score": 0.45, "note": "螺蛳粉热度回落，但臭味调料仍有一定市场"},
            {"ingredient": "椰子水/椰浆", "category": "饮品原料", "trend": "rising",
             "heat_score": 0.75, "note": "椰子鸡、椰香系列菜品持续增长"},
        ]
        return [t for t in trends if t["heat_score"] >= 0.3]

    # ─── 新口味检测 ───

    def detect_new_flavors(self) -> list[dict]:
        """自动检测新兴口味趋势"""
        return [
            {"flavor": "酸汤味", "heat_score": 0.95, "trend": "rising",
             "description": "贵州酸汤为基底，融合各地食材，2025-2026最热味型",
             "recommendation": "强烈建议开发酸汤系列"},
            {"flavor": "椰香味", "heat_score": 0.78, "trend": "rising",
             "description": "东南亚风味融合，椰香鸡、椰子冻等持续走红",
             "recommendation": "可开发椰香湘菜融合菜"},
            {"flavor": "藤椒味", "heat_score": 0.80, "trend": "rising",
             "description": "藤椒清麻口感受年轻人追捧，与传统花椒差异化",
             "recommendation": "建议在凉菜/小吃系列增加藤椒味选项"},
            {"flavor": "话梅味", "heat_score": 0.60, "trend": "emerging",
             "description": "话梅排骨、话梅小番茄等甜酸口味在华东流行",
             "recommendation": "可在甜品或小吃品类试水"},
            {"flavor": "柠檬酸辣味", "heat_score": 0.72, "trend": "rising",
             "description": "泰式酸辣+柠檬清爽，在夏季尤其受欢迎",
             "recommendation": "建议夏季限定推出柠檬酸辣系列"},
        ]

    # ─── 供应可行性评估 ───

    def assess_supply_feasibility(self, ingredient_name: str) -> dict:
        """评估食材供应可行性"""
        feasibility_db = {
            "贵州红酸汤": {
                "availability": "充足",
                "suppliers_count": 12,
                "price_stability": "稳定",
                "price_range_fen_per_kg": (3500, 5000),
                "shelf_life_days": 180,
                "cold_chain_required": False,
                "seasonal": False,
                "supply_risk": "low",
                "recommendation": "供应链成熟，可直接大批量采购",
            },
            "云南菌菇": {
                "availability": "季节性",
                "suppliers_count": 5,
                "price_stability": "波动大",
                "price_range_fen_per_kg": (15000, 80000),
                "shelf_life_days": 3,
                "cold_chain_required": True,
                "seasonal": True,
                "supply_risk": "high",
                "recommendation": "仅限6-9月应季供应，需冷链物流，建议与产地直供合作",
            },
            "松茸": {
                "availability": "稀缺",
                "suppliers_count": 3,
                "price_stability": "波动大",
                "price_range_fen_per_kg": (50000, 200000),
                "shelf_life_days": 2,
                "cold_chain_required": True,
                "seasonal": True,
                "supply_risk": "high",
                "recommendation": "高端食材限量供应，建议仅在旗舰店推出",
            },
            "藤椒": {
                "availability": "充足",
                "suppliers_count": 8,
                "price_stability": "稳定",
                "price_range_fen_per_kg": (4000, 6000),
                "shelf_life_days": 365,
                "cold_chain_required": False,
                "seasonal": False,
                "supply_risk": "low",
                "recommendation": "四川产区稳定供应，干藤椒和藤椒油均可采购",
            },
        }

        info = feasibility_db.get(ingredient_name)
        if not info:
            return {
                "ingredient": ingredient_name,
                "status": "no_data",
                "message": f"暂无{ingredient_name}的供应链数据，建议联系采购部门调研",
            }

        return {
            "ingredient": ingredient_name,
            "status": "assessed",
            **info,
        }
