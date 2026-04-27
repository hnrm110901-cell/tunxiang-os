"""试点建议引擎 — 把情报变成实际动作

从情报洞察生成可执行的试点建议，管理试点生命周期：
建议 → 审批 → 执行 → 跟踪 → 评审 → 推广/终止。
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog

logger = structlog.get_logger()


# ─── 常量 ───

SUGGESTION_STATUSES = [
    "draft",
    "proposed",
    "approved",
    "piloting",
    "reviewing",
    "scale_up",
    "completed",
    "rejected",
    "cancelled",
]

SUGGESTION_TYPES = [
    "new_product",
    "price_adjustment",
    "service_improvement",
    "marketing_campaign",
    "menu_optimization",
    "store_upgrade",
    "competitor_response",
    "trend_capture",
]

SOURCE_TYPES = [
    "competitor_action",
    "consumer_insight",
    "review_analysis",
    "new_product_radar",
    "pricing_insight",
    "manual",
]


# ─── 门店池 ───

_STORE_INFO: dict[str, dict] = {
    "S001": {"name": "芙蓉路旗舰店", "city": "长沙", "type": "flagship"},
    "S002": {"name": "五一广场店", "city": "长沙", "type": "standard"},
    "S003": {"name": "梅溪湖店", "city": "长沙", "type": "standard"},
    "S005": {"name": "南山科技园店", "city": "深圳", "type": "flagship"},
    "S006": {"name": "福田CBD店", "city": "深圳", "type": "premium"},
    "S010": {"name": "天河城店", "city": "广州", "type": "standard"},
    "S015": {"name": "光谷店", "city": "武汉", "type": "standard"},
}


# ─── 数据模型 ───


@dataclass
class PilotSuggestion:
    """试点建议"""

    suggestion_id: str
    source_type: str
    source_id: str
    suggestion_type: str
    title: str
    description: str
    recommended_stores: list[str]
    period_days: int
    success_metrics: list[dict]
    status: str = "proposed"
    approved_stores: list[str] = field(default_factory=list)
    adjusted_metrics: list[dict] = field(default_factory=list)
    pilot_start: str = ""
    pilot_end: str = ""
    results: dict = field(default_factory=dict)
    conclusion: str = ""
    created_at: str = ""
    updated_at: str = ""


class PilotSuggestionService:
    """试点建议引擎 — 把情报变成实际动作"""

    def __init__(self) -> None:
        self._suggestions: dict[str, PilotSuggestion] = {}
        self._load_seed_data()

    def _load_seed_data(self) -> None:
        """创建示例试点建议"""
        self.create_suggestion(
            source_type="new_product_radar",
            source_id="opp_sour_soup_fish",
            suggestion_type="new_product",
            title="酸汤鱼系列试点上线",
            description=(
                "基于新品雷达情报：贵州酸汤鱼品牌适配度90%，市场热度0.85。"
                "费大厨已上线酸汤系列，建议快速跟进。"
                "计划研发2道酸汤鱼菜品（酸汤鲈鱼、酸汤黄辣丁），在3家门店试点。"
            ),
            recommended_stores=["S001", "S005", "S010"],
            period_days=21,
            success_metrics=[
                {"metric": "daily_orders", "target": 30, "unit": "份/天"},
                {"metric": "customer_rating", "target": 4.3, "unit": "分"},
                {"metric": "reorder_rate", "target": 0.15, "unit": "比例"},
                {"metric": "gross_margin", "target": 0.58, "unit": "比例"},
            ],
        )

        self.create_suggestion(
            source_type="consumer_insight",
            source_id="topic_single_meal",
            suggestion_type="menu_optimization",
            title="午市一人食套餐扩充",
            description=(
                "基于消费洞察：一人食套餐需求上升18%，午市白领反馈强烈。"
                "当前仅1个SKU（35元），建议扩充至3个SKU（35/45/55元三档）。"
            ),
            recommended_stores=["S001", "S002", "S005"],
            period_days=14,
            success_metrics=[
                {"metric": "lunch_set_meal_orders", "target": 50, "unit": "份/天"},
                {"metric": "lunch_revenue_increase_pct", "target": 8, "unit": "%"},
                {"metric": "customer_satisfaction", "target": 4.2, "unit": "分"},
            ],
        )

        self.create_suggestion(
            source_type="competitor_action",
            source_id="action_feidachu_shenzhen",
            suggestion_type="competitor_response",
            title="深圳门店防御性营销活动",
            description=(
                "基于竞对监测：费大厨深圳新开5店，直接威胁我方南山/福田门店。"
                "建议在费大厨新店周边1km的我方门店启动防御性营销：会员专属折扣+新品首发。"
            ),
            recommended_stores=["S005", "S006"],
            period_days=30,
            success_metrics=[
                {"metric": "customer_retention_rate", "target": 0.85, "unit": "比例"},
                {"metric": "new_member_sign_up", "target": 200, "unit": "人/月"},
                {"metric": "traffic_change_pct", "target": 0, "unit": "%"},
            ],
        )

        logger.info("pilot_suggestion_seed_loaded", suggestions=len(self._suggestions))

    # ─── 建议管理 ───

    def create_suggestion(
        self,
        source_type: str,
        source_id: str,
        suggestion_type: str,
        title: str,
        description: str,
        recommended_stores: list[str],
        period_days: int,
        success_metrics: list[dict],
    ) -> dict:
        """创建试点建议"""
        if suggestion_type not in SUGGESTION_TYPES:
            raise ValueError(f"Invalid suggestion_type: {suggestion_type}")
        if source_type not in SOURCE_TYPES:
            raise ValueError(f"Invalid source_type: {source_type}")

        sid = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc).isoformat()

        suggestion = PilotSuggestion(
            suggestion_id=sid,
            source_type=source_type,
            source_id=source_id,
            suggestion_type=suggestion_type,
            title=title,
            description=description,
            recommended_stores=recommended_stores,
            period_days=period_days,
            success_metrics=success_metrics,
            status="proposed",
            created_at=now,
            updated_at=now,
        )
        self._suggestions[sid] = suggestion

        return {
            "suggestion_id": sid,
            "title": title,
            "suggestion_type": suggestion_type,
            "recommended_stores": recommended_stores,
            "period_days": period_days,
            "status": "proposed",
        }

    def list_suggestions(
        self,
        status: Optional[str] = None,
        suggestion_type: Optional[str] = None,
    ) -> list[dict]:
        """列出试点建议"""
        results = []
        for s in self._suggestions.values():
            if status and s.status != status:
                continue
            if suggestion_type and s.suggestion_type != suggestion_type:
                continue
            results.append(
                {
                    "suggestion_id": s.suggestion_id,
                    "title": s.title,
                    "suggestion_type": s.suggestion_type,
                    "source_type": s.source_type,
                    "status": s.status,
                    "recommended_stores": s.recommended_stores,
                    "period_days": s.period_days,
                    "created_at": s.created_at,
                }
            )
        results.sort(key=lambda x: x["created_at"], reverse=True)
        return results

    # ─── 审批 ───

    def approve_pilot(
        self,
        suggestion_id: str,
        approved_stores: list[str],
        adjusted_metrics: Optional[list[dict]] = None,
    ) -> dict:
        """审批试点"""
        s = self._suggestions.get(suggestion_id)
        if not s:
            raise KeyError(f"Suggestion not found: {suggestion_id}")
        if s.status != "proposed":
            raise ValueError(f"Cannot approve suggestion in status: {s.status}")

        now = datetime.now(timezone.utc)
        s.status = "approved"
        s.approved_stores = approved_stores
        s.adjusted_metrics = adjusted_metrics or s.success_metrics
        s.pilot_start = (now + timedelta(days=2)).strftime("%Y-%m-%d")
        s.pilot_end = (now + timedelta(days=2 + s.period_days)).strftime("%Y-%m-%d")
        s.updated_at = now.isoformat()

        store_names = [_STORE_INFO.get(sid, {}).get("name", sid) for sid in approved_stores]

        return {
            "suggestion_id": suggestion_id,
            "status": "approved",
            "approved_stores": approved_stores,
            "approved_store_names": store_names,
            "pilot_start": s.pilot_start,
            "pilot_end": s.pilot_end,
            "metrics": s.adjusted_metrics,
        }

    # ─── 试点跟踪 ───

    def track_pilot_progress(self, pilot_id: str) -> dict:
        """跟踪试点进度"""
        s = self._suggestions.get(pilot_id)
        if not s:
            raise KeyError(f"Pilot not found: {pilot_id}")

        if s.status not in ("approved", "piloting"):
            return {
                "pilot_id": pilot_id,
                "status": s.status,
                "message": f"试点当前状态为'{s.status}'，暂无进度数据",
            }

        # 将状态更新为 piloting
        if s.status == "approved":
            s.status = "piloting"
            s.updated_at = datetime.now(timezone.utc).isoformat()

        # 模拟进度数据
        metrics_progress = []
        for metric in s.adjusted_metrics or s.success_metrics:
            target = metric.get("target", 0)
            # 模拟当前进度（70%-110%的达成率）
            achievement_pct = 70 + (hash(metric.get("metric", "")) % 40)
            current = target * achievement_pct / 100

            metrics_progress.append(
                {
                    "metric": metric.get("metric", ""),
                    "target": target,
                    "current": round(current, 2),
                    "achievement_pct": achievement_pct,
                    "unit": metric.get("unit", ""),
                    "status": "on_track" if achievement_pct >= 80 else "at_risk",
                }
            )

        overall_health = (
            "healthy"
            if all(m["achievement_pct"] >= 80 for m in metrics_progress)
            else ("at_risk" if any(m["achievement_pct"] < 60 for m in metrics_progress) else "warning")
        )

        return {
            "pilot_id": pilot_id,
            "title": s.title,
            "status": s.status,
            "stores": s.approved_stores or s.recommended_stores,
            "pilot_start": s.pilot_start,
            "pilot_end": s.pilot_end,
            "metrics_progress": metrics_progress,
            "overall_health": overall_health,
            "days_elapsed": 7,  # 模拟
            "days_remaining": max(0, s.period_days - 7),
        }

    # ─── 试点评审 ───

    def complete_pilot_review(
        self,
        pilot_id: str,
        results: dict,
        conclusion: str,
    ) -> dict:
        """完成试点评审"""
        s = self._suggestions.get(pilot_id)
        if not s:
            raise KeyError(f"Pilot not found: {pilot_id}")

        s.status = "reviewing"
        s.results = results
        s.conclusion = conclusion
        s.updated_at = datetime.now(timezone.utc).isoformat()

        # 自动评估是否建议推广
        metrics_met = results.get("metrics_met", 0)
        metrics_total = results.get("metrics_total", 1)
        success_rate = metrics_met / metrics_total if metrics_total > 0 else 0

        if success_rate >= 0.8:
            recommendation = "strong_scale_up"
            rec_text = "试点效果优秀，强烈建议全面推广"
        elif success_rate >= 0.6:
            recommendation = "conditional_scale_up"
            rec_text = "试点效果达标，建议优化后推广"
        else:
            recommendation = "iterate_or_drop"
            rec_text = "试点效果不理想，建议调整方案后重新试点或终止"

        return {
            "pilot_id": pilot_id,
            "title": s.title,
            "status": "reviewing",
            "results": results,
            "conclusion": conclusion,
            "success_rate": round(success_rate, 2),
            "recommendation": recommendation,
            "recommendation_text": rec_text,
        }

    # ─── 推广建议 ───

    def recommend_scale_up(self, pilot_id: str) -> dict:
        """基于试点结果推荐推广门店"""
        s = self._suggestions.get(pilot_id)
        if not s:
            raise KeyError(f"Pilot not found: {pilot_id}")
        if s.status not in ("reviewing", "scale_up"):
            raise ValueError(f"Cannot recommend scale-up for pilot in status: {s.status}")

        pilot_stores = set(s.approved_stores or s.recommended_stores)
        expansion_stores = []
        for store_id, info in _STORE_INFO.items():
            if store_id in pilot_stores:
                continue
            expansion_stores.append(
                {
                    "store_id": store_id,
                    "store_name": info["name"],
                    "city": info["city"],
                    "store_type": info["type"],
                    "priority": "high" if info["type"] in ("flagship", "premium") else "medium",
                    "reason": self._scale_reason(info, s),
                }
            )

        # 按优先级排序
        expansion_stores.sort(key=lambda x: {"high": 0, "medium": 1, "low": 2}[x["priority"]])

        s.status = "scale_up"
        s.updated_at = datetime.now(timezone.utc).isoformat()

        return {
            "pilot_id": pilot_id,
            "title": s.title,
            "pilot_stores": list(pilot_stores),
            "recommended_expansion": expansion_stores,
            "total_expansion_stores": len(expansion_stores),
            "estimated_rollout_days": 14,
            "rollout_strategy": "分批推广：第1周旗舰店/高端店，第2周标准店",
        }

    def _scale_reason(self, store_info: dict, suggestion: PilotSuggestion) -> str:
        """生成推广理由"""
        if store_info["type"] == "flagship":
            return "旗舰店影响力大，优先推广"
        if store_info["type"] == "premium":
            return "高端店客群匹配度高"
        city = store_info.get("city", "")
        pilot_cities = set()
        for sid in suggestion.approved_stores or suggestion.recommended_stores:
            si = _STORE_INFO.get(sid, {})
            pilot_cities.add(si.get("city", ""))
        if city in pilot_cities:
            return "与试点门店同城，运营经验可复制"
        return "扩展新城市覆盖"

    # ─── 试点组合概览 ───

    def get_pilot_portfolio(self) -> dict:
        """试点组合概览"""
        status_counts: dict[str, int] = {}
        active_pilots: list[dict] = []
        completed_pilots: list[dict] = []

        for s in self._suggestions.values():
            status_counts[s.status] = status_counts.get(s.status, 0) + 1
            if s.status in ("approved", "piloting"):
                active_pilots.append(
                    {
                        "suggestion_id": s.suggestion_id,
                        "title": s.title,
                        "status": s.status,
                        "stores": s.approved_stores or s.recommended_stores,
                        "period_days": s.period_days,
                    }
                )
            elif s.status in ("reviewing", "scale_up", "completed"):
                success_rate = 0
                if s.results:
                    met = s.results.get("metrics_met", 0)
                    total = s.results.get("metrics_total", 1)
                    success_rate = met / total if total > 0 else 0
                completed_pilots.append(
                    {
                        "suggestion_id": s.suggestion_id,
                        "title": s.title,
                        "status": s.status,
                        "conclusion": s.conclusion,
                        "success_rate": round(success_rate, 2),
                    }
                )

        total_completed = len(completed_pilots)
        avg_success = sum(p["success_rate"] for p in completed_pilots) / total_completed if total_completed > 0 else 0

        return {
            "total_suggestions": len(self._suggestions),
            "status_distribution": status_counts,
            "active_pilots": active_pilots,
            "active_count": len(active_pilots),
            "completed_pilots": completed_pilots,
            "completed_count": total_completed,
            "avg_success_rate": round(avg_success, 2),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
