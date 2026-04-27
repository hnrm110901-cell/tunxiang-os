"""竞对监测引擎 — 持续跟踪同品类/同价格带/同商圈竞对

跟踪维度：新品上线、菜单变动、价格调整、营销活动、开店/关店、
评分变化、爆款单品、差评突增、外卖表现。

所有金额单位：分（fen）。
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog

logger = structlog.get_logger()


# ─── 常量 ───

MONITOR_DIMENSIONS = [
    "new_product",
    "menu_change",
    "price_change",
    "campaign",
    "store_open",
    "store_close",
    "rating_change",
    "hot_selling_item",
    "negative_review_spike",
    "delivery_performance",
]

IMPACT_LEVELS = ["low", "medium", "high", "critical"]

PRICE_TIERS = ["economy", "mid_range", "mid_premium", "premium", "luxury"]

MONITOR_LEVELS = ["basic", "standard", "intensive"]


# ─── 数据模型 ───


@dataclass
class Competitor:
    """竞对信息"""

    competitor_id: str
    name: str
    category: str
    price_tier: str
    cities: list[str]
    stores_count: int
    monitor_level: str
    tags: list[str] = field(default_factory=list)
    avg_rating: float = 0.0
    avg_spend_fen: int = 0
    registered_at: str = ""
    notes: str = ""


@dataclass
class CompetitorAction:
    """竞对动态"""

    action_id: str
    competitor_id: str
    action_type: str
    title: str
    detail: str
    impact_level: str
    source: str
    city: str = ""
    recorded_at: str = ""
    our_response: str = ""
    response_status: str = "pending"


# ─── 种子数据 ───

_SEED_COMPETITORS: list[dict] = [
    {
        "name": "海底捞",
        "category": "火锅",
        "price_tier": "premium",
        "cities": ["北京", "上海", "深圳", "成都", "长沙", "武汉", "广州", "杭州"],
        "stores_count": 1380,
        "monitor_level": "intensive",
        "tags": ["服务标杆", "全国连锁", "上市公司"],
        "avg_rating": 4.3,
        "avg_spend_fen": 12800,
        "notes": "服务体验标杆，社区营销能力强，近期推低价子品牌",
    },
    {
        "name": "西贝莜面村",
        "category": "西北菜",
        "price_tier": "mid_premium",
        "cities": ["北京", "上海", "深圳", "广州", "杭州", "南京"],
        "stores_count": 380,
        "monitor_level": "standard",
        "tags": ["家庭聚餐", "品质定位", "供应链强"],
        "avg_rating": 4.1,
        "avg_spend_fen": 10500,
        "notes": "家庭聚餐场景领先，'闭着眼睛点每道都好吃'定位清晰",
    },
    {
        "name": "太二酸菜鱼",
        "category": "酸菜鱼",
        "price_tier": "mid_range",
        "cities": ["广州", "深圳", "上海", "北京", "成都", "长沙"],
        "stores_count": 520,
        "monitor_level": "standard",
        "tags": ["单品爆款", "年轻客群", "社交媒体强"],
        "avg_rating": 4.2,
        "avg_spend_fen": 7800,
        "notes": "单品策略极致，'太二'IP运营强，限4人用餐的营销策略独特",
    },
    {
        "name": "费大厨辣椒炒肉",
        "category": "湘菜",
        "price_tier": "mid_range",
        "cities": ["长沙", "深圳", "广州", "上海", "北京"],
        "stores_count": 180,
        "monitor_level": "intensive",
        "tags": ["同品类直接竞对", "湘菜头部", "单品突破"],
        "avg_rating": 4.4,
        "avg_spend_fen": 7200,
        "notes": "辣椒炒肉大单品策略成功，长沙排队王，深圳扩张迅猛",
    },
    {
        "name": "望湘园",
        "category": "湘菜",
        "price_tier": "mid_range",
        "cities": ["上海", "北京", "杭州", "南京", "苏州"],
        "stores_count": 210,
        "monitor_level": "intensive",
        "tags": ["同品类直接竞对", "商务湘菜", "华东布局"],
        "avg_rating": 4.0,
        "avg_spend_fen": 8500,
        "notes": "商务宴请场景湘菜领先，华东地区深耕，菜品偏改良",
    },
]

_SEED_ACTIONS: list[dict] = [
    {
        "competitor_name": "海底捞",
        "action_type": "campaign",
        "title": "海底捞推出'小嗨火锅'子品牌",
        "detail": "人均60-80元定位，主打社区小火锅，首批30家店在成都试水。直接下探中端价格带。",
        "impact_level": "high",
        "source": "行业媒体",
        "city": "成都",
        "days_ago": 3,
    },
    {
        "competitor_name": "费大厨辣椒炒肉",
        "action_type": "store_open",
        "title": "费大厨深圳新开5家门店",
        "detail": "集中在南山区和福田区，月租均超30万，采用200平+大店策略。",
        "impact_level": "high",
        "source": "大众点评",
        "city": "深圳",
        "days_ago": 5,
    },
    {
        "competitor_name": "费大厨辣椒炒肉",
        "action_type": "new_product",
        "title": "费大厨上线酸汤肥牛系列",
        "detail": "新增3道酸汤系列菜品，定价48-68元，明显蹭酸汤火锅热度。",
        "impact_level": "medium",
        "source": "美团",
        "city": "长沙",
        "days_ago": 7,
    },
    {
        "competitor_name": "太二酸菜鱼",
        "action_type": "price_change",
        "title": "太二午市套餐降价15%",
        "detail": "工作日午市推出单人套餐39.9元（原价48元），含酸菜鱼+米饭+饮料。",
        "impact_level": "medium",
        "source": "大众点评",
        "city": "上海",
        "days_ago": 2,
    },
    {
        "competitor_name": "望湘园",
        "action_type": "menu_change",
        "title": "望湘园菜单全面升级",
        "detail": "精简SKU从120+降至80，聚焦招牌菜，增加湘西土菜系列。",
        "impact_level": "medium",
        "source": "行业调研",
        "city": "上海",
        "days_ago": 10,
    },
    {
        "competitor_name": "西贝莜面村",
        "action_type": "campaign",
        "title": "西贝亲子餐升级'宝贝厨房'",
        "detail": "全国门店推出儿童烘焙DIY体验，周末场次预约已排满。强化家庭场景。",
        "impact_level": "medium",
        "source": "社交媒体",
        "city": "北京",
        "days_ago": 4,
    },
    {
        "competitor_name": "海底捞",
        "action_type": "negative_review_spike",
        "title": "海底捞长沙3店差评突增",
        "detail": "近7天差评率从5%升至12%，主要集中在等位时间过长和服务态度下降。",
        "impact_level": "low",
        "source": "大众点评",
        "city": "长沙",
        "days_ago": 1,
    },
    {
        "competitor_name": "费大厨辣椒炒肉",
        "action_type": "hot_selling_item",
        "title": "费大厨'现炒黄牛肉'成新爆品",
        "detail": "上线2周单店日均销量80+份，抖音话题播放量超5000万。",
        "impact_level": "medium",
        "source": "抖音/美团",
        "city": "长沙",
        "days_ago": 6,
    },
]


# ─── 我方基准指标（用于对比） ───

_OUR_BRAND_METRICS = {
    "category": "湘菜",
    "price_tier": "mid_range",
    "stores_count": 85,
    "avg_rating": 4.2,
    "avg_spend_fen": 7500,
    "cities": ["长沙", "深圳", "广州", "武汉"],
    "monthly_revenue_fen": 680_000_00,
    "delivery_score": 4.5,
    "repeat_rate": 0.32,
    "new_product_per_quarter": 6,
}


class CompetitorMonitorService:
    """竞对监测引擎 — 持续跟踪同品类/同价格带/同商圈竞对"""

    def __init__(self) -> None:
        self._competitors: dict[str, Competitor] = {}
        self._actions: list[CompetitorAction] = []
        self._load_seed_data()

    # ─── 种子数据加载 ───

    def _load_seed_data(self) -> None:
        """加载种子竞对和动态"""
        name_to_id: dict[str, str] = {}
        for seed in _SEED_COMPETITORS:
            result = self.register_competitor(
                name=seed["name"],
                category=seed["category"],
                price_tier=seed["price_tier"],
                cities=seed["cities"],
                stores_count=seed["stores_count"],
                monitor_level=seed["monitor_level"],
                tags=seed.get("tags", []),
                avg_rating=seed.get("avg_rating", 0.0),
                avg_spend_fen=seed.get("avg_spend_fen", 0),
                notes=seed.get("notes", ""),
            )
            name_to_id[seed["name"]] = result["competitor_id"]

        now = datetime.now(timezone.utc)
        for seed_action in _SEED_ACTIONS:
            cid = name_to_id.get(seed_action["competitor_name"], "")
            if not cid:
                continue
            days_ago = seed_action.get("days_ago", 0)
            action_time = now - timedelta(days=days_ago)
            action = CompetitorAction(
                action_id=uuid.uuid4().hex[:12],
                competitor_id=cid,
                action_type=seed_action["action_type"],
                title=seed_action["title"],
                detail=seed_action["detail"],
                impact_level=seed_action["impact_level"],
                source=seed_action["source"],
                city=seed_action.get("city", ""),
                recorded_at=action_time.isoformat(),
            )
            self._actions.append(action)

        logger.info("seed_data_loaded", competitors=len(self._competitors), actions=len(self._actions))

    # ─── 竞对管理 ───

    def register_competitor(
        self,
        name: str,
        category: str,
        price_tier: str,
        cities: list[str],
        stores_count: int,
        monitor_level: str,
        tags: Optional[list[str]] = None,
        avg_rating: float = 0.0,
        avg_spend_fen: int = 0,
        notes: str = "",
    ) -> dict:
        """注册竞对品牌"""
        if price_tier not in PRICE_TIERS:
            raise ValueError(f"Invalid price_tier: {price_tier}, must be one of {PRICE_TIERS}")
        if monitor_level not in MONITOR_LEVELS:
            raise ValueError(f"Invalid monitor_level: {monitor_level}, must be one of {MONITOR_LEVELS}")

        cid = uuid.uuid4().hex[:12]
        competitor = Competitor(
            competitor_id=cid,
            name=name,
            category=category,
            price_tier=price_tier,
            cities=cities,
            stores_count=stores_count,
            monitor_level=monitor_level,
            tags=tags or [],
            avg_rating=avg_rating,
            avg_spend_fen=avg_spend_fen,
            registered_at=datetime.now(timezone.utc).isoformat(),
            notes=notes,
        )
        self._competitors[cid] = competitor
        logger.info("competitor_registered", name=name, competitor_id=cid)
        return {"competitor_id": cid, "name": name, "status": "registered"}

    def list_competitors(self, category: Optional[str] = None, city: Optional[str] = None) -> list[dict]:
        """列出竞对品牌，可按品类/城市过滤"""
        results = []
        for c in self._competitors.values():
            if category and c.category != category:
                continue
            if city and city not in c.cities:
                continue
            results.append(
                {
                    "competitor_id": c.competitor_id,
                    "name": c.name,
                    "category": c.category,
                    "price_tier": c.price_tier,
                    "cities": c.cities,
                    "stores_count": c.stores_count,
                    "monitor_level": c.monitor_level,
                    "avg_rating": c.avg_rating,
                    "tags": c.tags,
                }
            )
        return results

    def get_competitor_detail(self, competitor_id: str) -> dict:
        """获取竞对详情"""
        c = self._competitors.get(competitor_id)
        if not c:
            raise KeyError(f"Competitor not found: {competitor_id}")
        recent_actions = [a for a in self._actions if a.competitor_id == competitor_id][-10:]
        return {
            "competitor_id": c.competitor_id,
            "name": c.name,
            "category": c.category,
            "price_tier": c.price_tier,
            "cities": c.cities,
            "stores_count": c.stores_count,
            "monitor_level": c.monitor_level,
            "tags": c.tags,
            "avg_rating": c.avg_rating,
            "avg_spend_fen": c.avg_spend_fen,
            "registered_at": c.registered_at,
            "notes": c.notes,
            "recent_actions_count": len(recent_actions),
            "recent_actions": [
                {
                    "action_id": a.action_id,
                    "title": a.title,
                    "action_type": a.action_type,
                    "impact_level": a.impact_level,
                    "recorded_at": a.recorded_at,
                }
                for a in recent_actions
            ],
        }

    # ─── 动态记录 ───

    def record_competitor_action(
        self,
        competitor_id: str,
        action_type: str,
        title: str,
        detail: str,
        impact_level: str,
        source: str,
        city: str = "",
    ) -> dict:
        """记录竞对动态"""
        if competitor_id not in self._competitors:
            raise KeyError(f"Competitor not found: {competitor_id}")
        if action_type not in MONITOR_DIMENSIONS:
            raise ValueError(f"Invalid action_type: {action_type}, must be one of {MONITOR_DIMENSIONS}")
        if impact_level not in IMPACT_LEVELS:
            raise ValueError(f"Invalid impact_level: {impact_level}, must be one of {IMPACT_LEVELS}")

        action = CompetitorAction(
            action_id=uuid.uuid4().hex[:12],
            competitor_id=competitor_id,
            action_type=action_type,
            title=title,
            detail=detail,
            impact_level=impact_level,
            source=source,
            city=city,
            recorded_at=datetime.now(timezone.utc).isoformat(),
        )
        self._actions.append(action)
        logger.info(
            "competitor_action_recorded",
            action_id=action.action_id,
            competitor=self._competitors[competitor_id].name,
            action_type=action_type,
        )
        return {
            "action_id": action.action_id,
            "competitor_name": self._competitors[competitor_id].name,
            "action_type": action_type,
            "impact_level": impact_level,
            "status": "recorded",
        }

    def get_recent_actions(
        self,
        days: int = 7,
        competitor_id: Optional[str] = None,
        action_type: Optional[str] = None,
    ) -> list[dict]:
        """获取近期竞对动态"""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        results = []
        for a in self._actions:
            if a.recorded_at and datetime.fromisoformat(a.recorded_at) < cutoff:
                continue
            if competitor_id and a.competitor_id != competitor_id:
                continue
            if action_type and a.action_type != action_type:
                continue
            comp = self._competitors.get(a.competitor_id)
            results.append(
                {
                    "action_id": a.action_id,
                    "competitor_id": a.competitor_id,
                    "competitor_name": comp.name if comp else "未知",
                    "action_type": a.action_type,
                    "title": a.title,
                    "detail": a.detail,
                    "impact_level": a.impact_level,
                    "source": a.source,
                    "city": a.city,
                    "recorded_at": a.recorded_at,
                }
            )
        results.sort(key=lambda x: x["recorded_at"], reverse=True)
        return results

    # ─── 对比分析 ───

    def compare_with_self(self, competitor_id: str, metrics: list[str]) -> dict:
        """与我方品牌对比关键指标"""
        c = self._competitors.get(competitor_id)
        if not c:
            raise KeyError(f"Competitor not found: {competitor_id}")

        comparison: dict[str, dict] = {}
        metric_map = {
            "stores_count": ("门店数", c.stores_count, _OUR_BRAND_METRICS["stores_count"]),
            "avg_rating": ("平均评分", c.avg_rating, _OUR_BRAND_METRICS["avg_rating"]),
            "avg_spend_fen": ("客单价(分)", c.avg_spend_fen, _OUR_BRAND_METRICS["avg_spend_fen"]),
            "city_coverage": ("覆盖城市数", len(c.cities), len(_OUR_BRAND_METRICS["cities"])),
            "price_tier": ("价格带", c.price_tier, _OUR_BRAND_METRICS["price_tier"]),
        }

        for m in metrics:
            if m in metric_map:
                label, their_val, our_val = metric_map[m]
                if isinstance(their_val, (int, float)) and isinstance(our_val, (int, float)):
                    diff = their_val - our_val
                    pct = (diff / our_val * 100) if our_val != 0 else 0
                    comparison[m] = {
                        "label": label,
                        "competitor_value": their_val,
                        "our_value": our_val,
                        "diff": diff,
                        "diff_pct": round(pct, 1),
                        "assessment": "领先" if diff > 0 else ("落后" if diff < 0 else "持平"),
                    }
                else:
                    comparison[m] = {
                        "label": label,
                        "competitor_value": their_val,
                        "our_value": our_val,
                    }

        return {
            "competitor_name": c.name,
            "our_brand": "屯象旗下品牌",
            "metrics_compared": len(comparison),
            "comparison": comparison,
        }

    def get_competitor_timeline(self, competitor_id: str, days: int = 90) -> list[dict]:
        """获取竞对动态时间线"""
        if competitor_id not in self._competitors:
            raise KeyError(f"Competitor not found: {competitor_id}")
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        timeline = []
        for a in self._actions:
            if a.competitor_id != competitor_id:
                continue
            if a.recorded_at and datetime.fromisoformat(a.recorded_at) < cutoff:
                continue
            timeline.append(
                {
                    "action_id": a.action_id,
                    "action_type": a.action_type,
                    "title": a.title,
                    "impact_level": a.impact_level,
                    "recorded_at": a.recorded_at,
                }
            )
        timeline.sort(key=lambda x: x["recorded_at"])
        return timeline

    # ─── 威胁检测 ───

    def detect_threats(self) -> list[dict]:
        """自动检测竞对威胁信号"""
        threats: list[dict] = []
        now = datetime.now(timezone.utc)
        recent_cutoff = now - timedelta(days=14)

        for cid, comp in self._competitors.items():
            recent = [
                a
                for a in self._actions
                if a.competitor_id == cid and a.recorded_at and datetime.fromisoformat(a.recorded_at) >= recent_cutoff
            ]
            if not recent:
                continue

            # 威胁1：同品类竞对开店扩张
            open_actions = [a for a in recent if a.action_type == "store_open"]
            if open_actions and comp.category == _OUR_BRAND_METRICS["category"]:
                for oa in open_actions:
                    overlap_cities = set(comp.cities) & set(_OUR_BRAND_METRICS["cities"])
                    if overlap_cities:
                        threats.append(
                            {
                                "threat_type": "同品类扩张",
                                "competitor_name": comp.name,
                                "severity": "high",
                                "description": f"{comp.name}在重叠城市{', '.join(overlap_cities)}开新店",
                                "source_action_id": oa.action_id,
                                "recommended_response": "关注新店选址位置，评估对周边门店客流影响",
                                "detected_at": now.isoformat(),
                            }
                        )

            # 威胁2：竞对降价
            price_actions = [a for a in recent if a.action_type == "price_change"]
            for pa in price_actions:
                threats.append(
                    {
                        "threat_type": "价格竞争",
                        "competitor_name": comp.name,
                        "severity": "medium",
                        "description": pa.title,
                        "source_action_id": pa.action_id,
                        "recommended_response": "分析降价对客流影响，评估是否需要调整套餐策略",
                        "detected_at": now.isoformat(),
                    }
                )

            # 威胁3：竞对爆品冲击
            hot_items = [a for a in recent if a.action_type == "hot_selling_item"]
            for hi in hot_items:
                if comp.category == _OUR_BRAND_METRICS["category"]:
                    threats.append(
                        {
                            "threat_type": "爆品冲击",
                            "competitor_name": comp.name,
                            "severity": "high",
                            "description": hi.title,
                            "source_action_id": hi.action_id,
                            "recommended_response": "研究爆品卖点，评估是否需要开发类似产品或差异化应对",
                            "detected_at": now.isoformat(),
                        }
                    )

            # 威胁4：高频动作 = 竞对在发力
            high_impact = [a for a in recent if a.impact_level in ("high", "critical")]
            if len(high_impact) >= 3:
                threats.append(
                    {
                        "threat_type": "竞对加速",
                        "competitor_name": comp.name,
                        "severity": "critical",
                        "description": f"{comp.name}近14天有{len(high_impact)}个高影响力动作，可能在发起战略攻势",
                        "source_action_id": high_impact[0].action_id,
                        "recommended_response": "召开竞对分析专题会，制定应对方案",
                        "detected_at": now.isoformat(),
                    }
                )

        threats.sort(key=lambda t: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(t["severity"], 9))
        return threats

    # ─── 竞对摘要 ───

    def generate_competitor_summary(self, competitor_id: str) -> dict:
        """生成竞对近期动态一段话总结"""
        c = self._competitors.get(competitor_id)
        if not c:
            raise KeyError(f"Competitor not found: {competitor_id}")

        recent_actions = self.get_recent_actions(days=30, competitor_id=competitor_id)
        if not recent_actions:
            summary_text = f"{c.name}近30天无显著动态。"
        else:
            action_types_cn = {
                "new_product": "新品上线",
                "menu_change": "菜单调整",
                "price_change": "价格变动",
                "campaign": "营销活动",
                "store_open": "新开门店",
                "store_close": "关闭门店",
                "rating_change": "评分变化",
                "hot_selling_item": "爆款单品",
                "negative_review_spike": "差评突增",
                "delivery_performance": "外卖变化",
            }
            action_counts: dict[str, int] = {}
            titles: list[str] = []
            for a in recent_actions:
                cn = action_types_cn.get(a["action_type"], a["action_type"])
                action_counts[cn] = action_counts.get(cn, 0) + 1
                titles.append(a["title"])

            count_str = "、".join(f"{k}{v}次" for k, v in action_counts.items())
            highlights = "；".join(titles[:3])
            high_impact_count = sum(1 for a in recent_actions if a["impact_level"] in ("high", "critical"))

            summary_text = f"{c.name}近30天共{len(recent_actions)}条动态（{count_str}）。重点事件：{highlights}。"
            if high_impact_count > 0:
                summary_text += f"其中{high_impact_count}条为高影响力事件，需重点关注。"

        return {
            "competitor_id": competitor_id,
            "competitor_name": c.name,
            "period": "近30天",
            "summary": summary_text,
            "total_actions": len(recent_actions) if recent_actions else 0,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
