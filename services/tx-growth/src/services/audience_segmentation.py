"""客户分群引擎 — 从会员列表升级到经营人群池

基于 RFM、行为特征、消费偏好等多维度规则，将会员划分为
系统预设 + 自定义人群包，支持动态计算与 AI 推荐。

金额单位：分(fen)
"""
import uuid
from datetime import datetime, timezone
from typing import Any, Optional


# ---------------------------------------------------------------------------
# 内存存储
# ---------------------------------------------------------------------------

_segments: dict[str, dict] = {}
_segment_users: dict[str, list[dict]] = {}  # segment_id -> [user_data]


# ---------------------------------------------------------------------------
# AudienceSegmentationService
# ---------------------------------------------------------------------------

class AudienceSegmentationService:
    """客户分群引擎 — 从会员列表升级到经营人群池"""

    SYSTEM_SEGMENTS = {
        "new_customer": "新客",
        "first_no_repeat": "首单未复购",
        "high_potential_new": "高潜新客",
        "dormant": "沉睡客",
        "high_frequency": "高频复购客",
        "high_value_banquet": "高价值宴请客",
        "family_dining": "家庭聚餐客",
        "price_sensitive": "价格敏感客",
        "health_oriented": "健康导向客",
        "festival_consumer": "节日消费客",
        "stored_value": "会员储值倾向客",
    }

    # 系统分群的默认规则
    _SYSTEM_RULES: dict[str, dict] = {
        "new_customer": {
            "conditions": [{"field": "first_order_days", "op": "<=", "value": 30}],
            "description": "首次消费在30天内",
        },
        "first_no_repeat": {
            "conditions": [
                {"field": "order_count", "op": "==", "value": 1},
                {"field": "first_order_days", "op": ">=", "value": 3},
            ],
            "description": "仅消费1次且首单超过3天",
        },
        "high_potential_new": {
            "conditions": [
                {"field": "order_count", "op": "<=", "value": 2},
                {"field": "avg_order_fen", "op": ">=", "value": 15000},
            ],
            "description": "消费不超过2次但客单价≥150元",
        },
        "dormant": {
            "conditions": [
                {"field": "recency_days", "op": ">=", "value": 60},
                {"field": "order_count", "op": ">=", "value": 2},
            ],
            "description": "60天未消费且有过2次以上消费",
        },
        "high_frequency": {
            "conditions": [
                {"field": "monthly_frequency", "op": ">=", "value": 4},
            ],
            "description": "月均消费≥4次",
        },
        "high_value_banquet": {
            "conditions": [
                {"field": "avg_order_fen", "op": ">=", "value": 50000},
                {"field": "avg_party_size", "op": ">=", "value": 6},
            ],
            "description": "客单价≥500元且平均就餐人数≥6人",
        },
        "family_dining": {
            "conditions": [
                {"field": "avg_party_size", "op": ">=", "value": 3},
                {"field": "weekend_ratio", "op": ">=", "value": 0.6},
            ],
            "description": "平均就餐≥3人且周末消费占比≥60%",
        },
        "price_sensitive": {
            "conditions": [
                {"field": "coupon_usage_rate", "op": ">=", "value": 0.7},
                {"field": "avg_order_fen", "op": "<=", "value": 8000},
            ],
            "description": "优惠券使用率≥70%且客单价≤80元",
        },
        "health_oriented": {
            "conditions": [
                {"field": "health_dish_ratio", "op": ">=", "value": 0.4},
            ],
            "description": "健康菜品点单占比≥40%",
        },
        "festival_consumer": {
            "conditions": [
                {"field": "festival_order_ratio", "op": ">=", "value": 0.5},
            ],
            "description": "节假日消费占比≥50%",
        },
        "stored_value": {
            "conditions": [
                {"field": "has_stored_value", "op": "==", "value": True},
                {"field": "stored_value_balance_fen", "op": ">=", "value": 10000},
            ],
            "description": "有储值且余额≥100元",
        },
    }

    def __init__(self) -> None:
        self._ensure_system_segments()

    def _ensure_system_segments(self) -> None:
        """初始化系统预设分群"""
        for seg_key, seg_name in self.SYSTEM_SEGMENTS.items():
            if seg_key not in _segments:
                rules = self._SYSTEM_RULES.get(seg_key, {"conditions": []})
                _segments[seg_key] = {
                    "segment_id": seg_key,
                    "name": seg_name,
                    "segment_type": "system",
                    "rules": rules,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }

    def create_segment(
        self,
        name: str,
        rules: dict,
        segment_type: str = "custom",
    ) -> dict:
        """创建自定义分群

        Args:
            name: 分群名称
            rules: 分群规则
                {"conditions": [{"field": "recency_days", "op": ">=", "value": 90}],
                 "logic": "and", "description": "..."}
            segment_type: 分群类型 "system" | "custom" | "ai_recommended"
        """
        segment_id = str(uuid.uuid4())[:8]
        now = datetime.now(timezone.utc).isoformat()
        segment = {
            "segment_id": segment_id,
            "name": name,
            "segment_type": segment_type,
            "rules": rules,
            "created_at": now,
            "updated_at": now,
        }
        _segments[segment_id] = segment
        return segment

    def list_segments(self) -> list[dict]:
        """列出所有分群"""
        return list(_segments.values())

    def get_segment_detail(self, segment_id: str) -> dict:
        """获取分群详情"""
        segment = _segments.get(segment_id)
        if not segment:
            return {"error": f"分群不存在: {segment_id}"}
        return segment

    def get_segment_users(
        self,
        segment_id: str,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """获取分群下的用户列表（分页）"""
        if segment_id not in _segments:
            return {"error": f"分群不存在: {segment_id}"}

        users = _segment_users.get(segment_id, [])
        total = len(users)
        start = (page - 1) * size
        end = start + size
        return {
            "segment_id": segment_id,
            "items": users[start:end],
            "total": total,
            "page": page,
            "size": size,
        }

    def compute_segment_stats(self, segment_id: str) -> dict:
        """计算分群统计指标"""
        if segment_id not in _segments:
            return {"error": f"分群不存在: {segment_id}"}

        users = _segment_users.get(segment_id, [])
        count = len(users)

        if count == 0:
            return {
                "segment_id": segment_id,
                "count": 0,
                "revenue_contribution_fen": 0,
                "avg_order_value_fen": 0,
                "avg_frequency": 0.0,
                "repeat_probability": 0.0,
            }

        total_revenue_fen = sum(u.get("total_spent_fen", 0) for u in users)
        total_orders = sum(u.get("order_count", 0) for u in users)
        avg_order_fen = total_revenue_fen // total_orders if total_orders > 0 else 0
        avg_frequency = total_orders / count if count > 0 else 0.0
        repeat_users = sum(1 for u in users if u.get("order_count", 0) >= 2)
        repeat_probability = repeat_users / count if count > 0 else 0.0

        return {
            "segment_id": segment_id,
            "count": count,
            "revenue_contribution_fen": total_revenue_fen,
            "avg_order_value_fen": avg_order_fen,
            "avg_frequency": round(avg_frequency, 2),
            "repeat_probability": round(repeat_probability, 3),
        }

    def classify_user(self, user_data: dict) -> list[str]:
        """将用户分类到匹配的分群

        Args:
            user_data: 用户数据字典，包含各维度指标

        Returns:
            匹配的 segment_id 列表
        """
        matched: list[str] = []
        for segment_id, segment in _segments.items():
            rules = segment.get("rules", {})
            conditions = rules.get("conditions", [])
            logic = rules.get("logic", "and")

            if not conditions:
                continue

            results = [
                self._evaluate_condition(cond, user_data)
                for cond in conditions
            ]

            if logic == "or":
                if any(results):
                    matched.append(segment_id)
            else:  # and
                if all(results):
                    matched.append(segment_id)

        return matched

    def ai_recommend_segments(self, brand_id: str) -> list[dict]:
        """AI 推荐分群（基于数据模式分析）

        返回 AI 建议的分群定义，由运营人员确认后创建。
        """
        # 基于常见餐饮业务模式的推荐
        recommendations = [
            {
                "name": "午市工作餐常客",
                "description": "工作日午间高频消费，客单价60-100元，偏好快出餐品",
                "rules": {
                    "conditions": [
                        {"field": "weekday_lunch_ratio", "op": ">=", "value": 0.6},
                        {"field": "monthly_frequency", "op": ">=", "value": 6},
                        {"field": "avg_order_fen", "op": "<=", "value": 10000},
                    ],
                    "logic": "and",
                },
                "estimated_count": 320,
                "marketing_suggestion": "推午市套餐+储值卡，提高锁客率",
                "confidence": 0.82,
            },
            {
                "name": "晚市社交聚餐客",
                "description": "周末晚间消费为主，4人以上聚餐，客单价偏高",
                "rules": {
                    "conditions": [
                        {"field": "weekend_dinner_ratio", "op": ">=", "value": 0.5},
                        {"field": "avg_party_size", "op": ">=", "value": 4},
                        {"field": "avg_order_fen", "op": ">=", "value": 20000},
                    ],
                    "logic": "and",
                },
                "estimated_count": 185,
                "marketing_suggestion": "推包间预订+宴会套餐，提升桌均消费",
                "confidence": 0.78,
            },
            {
                "name": "外卖偏好客",
                "description": "外卖订单占比超过50%，可能未到过门店",
                "rules": {
                    "conditions": [
                        {"field": "delivery_order_ratio", "op": ">=", "value": 0.5},
                    ],
                    "logic": "and",
                },
                "estimated_count": 540,
                "marketing_suggestion": "到店首单奖励，引导到店体验",
                "confidence": 0.85,
            },
            {
                "name": "新品尝鲜客",
                "description": "新品上线30天内必点，乐于尝试新菜",
                "rules": {
                    "conditions": [
                        {"field": "new_dish_trial_ratio", "op": ">=", "value": 0.3},
                        {"field": "dish_variety_count", "op": ">=", "value": 15},
                    ],
                    "logic": "and",
                },
                "estimated_count": 210,
                "marketing_suggestion": "新品优先内测+口碑传播激励",
                "confidence": 0.75,
            },
        ]

        return recommendations

    def get_lifecycle_distribution(self) -> dict:
        """获取客户生命周期分布

        new → active → loyal → dormant → churned
        """
        # 汇总所有分群用户的生命周期阶段
        lifecycle = {
            "new": {"count": 0, "label": "新客", "description": "首次消费30天内"},
            "active": {"count": 0, "label": "活跃客", "description": "30天内有消费"},
            "loyal": {"count": 0, "label": "忠诚客", "description": "月均消费≥3次"},
            "dormant": {"count": 0, "label": "沉睡客", "description": "30-90天未消费"},
            "churned": {"count": 0, "label": "流失客", "description": "90天以上未消费"},
        }

        # 聚合已分类用户
        seen_users: set[str] = set()
        for seg_id, users in _segment_users.items():
            for u in users:
                uid = u.get("user_id", "")
                if uid in seen_users:
                    continue
                seen_users.add(uid)

                recency = u.get("recency_days", 999)
                frequency = u.get("monthly_frequency", 0)
                first_order_days = u.get("first_order_days", 999)

                if first_order_days <= 30:
                    lifecycle["new"]["count"] += 1
                elif frequency >= 3 and recency <= 30:
                    lifecycle["loyal"]["count"] += 1
                elif recency <= 30:
                    lifecycle["active"]["count"] += 1
                elif recency <= 90:
                    lifecycle["dormant"]["count"] += 1
                else:
                    lifecycle["churned"]["count"] += 1

        total = sum(stage["count"] for stage in lifecycle.values())
        for stage in lifecycle.values():
            stage["pct"] = round(stage["count"] / total * 100, 1) if total > 0 else 0.0

        return {"total": total, "stages": lifecycle}

    @staticmethod
    def _evaluate_condition(condition: dict, user_data: dict) -> bool:
        """评估单个条件"""
        field = condition.get("field", "")
        op = condition.get("op", "==")
        target = condition.get("value")
        actual = user_data.get(field)

        if actual is None:
            return False

        if op == "==":
            return actual == target
        elif op == "!=":
            return actual != target
        elif op == ">=":
            return actual >= target
        elif op == "<=":
            return actual <= target
        elif op == ">":
            return actual > target
        elif op == "<":
            return actual < target
        elif op == "in":
            return actual in target
        elif op == "not_in":
            return actual not in target
        return False


def add_users_to_segment(segment_id: str, users: list[dict]) -> None:
    """辅助函数：向分群添加用户数据（用于测试和数据导入）"""
    if segment_id not in _segment_users:
        _segment_users[segment_id] = []
    _segment_users[segment_id].extend(users)


def clear_all_segments() -> None:
    """辅助函数：清空所有分群数据（仅测试用）"""
    _segments.clear()
    _segment_users.clear()
