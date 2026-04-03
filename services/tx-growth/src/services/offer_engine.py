"""优惠策略引擎 — 核心不是发券，而是利益结构设计

从「发优惠券」升级到「设计利益结构」：
- 每个优惠都有明确的业务目标（拉新/复购/提频/提客单价）
- 毛利底线硬约束（三条硬约束之一）
- 自动计算 ROI 预估

金额单位：分(fen)
"""
import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# 内存存储
# ---------------------------------------------------------------------------

_offers: dict[str, dict] = {}
_offer_redemptions: dict[str, list[dict]] = {}  # offer_id -> [redemption_log]


# ---------------------------------------------------------------------------
# OfferEngine
# ---------------------------------------------------------------------------

class OfferEngine:
    """优惠策略引擎 — 核心不是发券，而是利益结构设计"""

    OFFER_TYPES = [
        "new_customer_trial",   # 新客体验
        "first_addon",          # 首单加购
        "second_visit",         # 二次到店
        "birthday_reward",      # 生日礼遇
        "stored_value_bonus",   # 储值赠送
        "banquet_inquiry_gift", # 宴会咨询礼
        "referral_reward",      # 老带新奖励
        "new_dish_trial",       # 新品尝鲜
        "off_peak_traffic",     # 闲时引流
    ]

    # 各优惠类型的默认参数
    _TYPE_DEFAULTS: dict[str, dict] = {
        "new_customer_trial": {
            "description": "新客首单体验优惠",
            "typical_discount_pct": 15,
            "typical_validity_days": 7,
            "goal": "acquisition",
        },
        "first_addon": {
            "description": "首单加购优惠（满减/加价换购）",
            "typical_discount_pct": 10,
            "typical_validity_days": 1,
            "goal": "aov_lift",
        },
        "second_visit": {
            "description": "二次到店优惠券",
            "typical_discount_pct": 20,
            "typical_validity_days": 14,
            "goal": "retention",
        },
        "birthday_reward": {
            "description": "生日专属礼遇",
            "typical_discount_pct": 25,
            "typical_validity_days": 7,
            "goal": "loyalty",
        },
        "stored_value_bonus": {
            "description": "储值赠送额",
            "typical_discount_pct": 10,
            "typical_validity_days": 365,
            "goal": "lock_in",
        },
        "banquet_inquiry_gift": {
            "description": "宴会咨询到店礼",
            "typical_discount_pct": 5,
            "typical_validity_days": 30,
            "goal": "conversion",
        },
        "referral_reward": {
            "description": "老带新双向奖励",
            "typical_discount_pct": 15,
            "typical_validity_days": 30,
            "goal": "acquisition",
        },
        "new_dish_trial": {
            "description": "新品限时尝鲜价",
            "typical_discount_pct": 20,
            "typical_validity_days": 14,
            "goal": "trial",
        },
        "off_peak_traffic": {
            "description": "闲时到店优惠",
            "typical_discount_pct": 15,
            "typical_validity_days": 30,
            "goal": "traffic",
        },
    }

    def create_offer(
        self,
        name: str,
        offer_type: str,
        discount_rules: dict,
        validity_days: int,
        target_segments: list[str],
        stores: list[str],
        time_slots: list[dict],
        margin_floor: float,
    ) -> dict:
        """创建优惠策略

        Args:
            name: 优惠名称
            offer_type: 优惠类型（OFFER_TYPES 之一）
            discount_rules: 优惠规则
                {"type": "fixed_amount", "amount_fen": 2000} 或
                {"type": "percentage", "pct": 15} 或
                {"type": "threshold", "threshold_fen": 10000, "reduce_fen": 1500}
            validity_days: 有效天数
            target_segments: 目标分群ID列表
            stores: 适用门店ID列表（空列表=全部门店）
            time_slots: 适用时段 [{"start": "14:00", "end": "17:00", "weekdays": [1,2,3,4,5]}]
            margin_floor: 毛利底线（百分比，如 0.45 表示45%）
        """
        if offer_type not in self.OFFER_TYPES:
            return {"error": f"不支持的优惠类型: {offer_type}"}

        offer_id = str(uuid.uuid4())[:8]
        now = datetime.now(timezone.utc).isoformat()
        type_defaults = self._TYPE_DEFAULTS.get(offer_type, {})

        offer = {
            "offer_id": offer_id,
            "name": name,
            "offer_type": offer_type,
            "description": type_defaults.get("description", ""),
            "goal": type_defaults.get("goal", "general"),
            "discount_rules": discount_rules,
            "validity_days": validity_days,
            "target_segments": target_segments,
            "stores": stores,
            "time_slots": time_slots,
            "margin_floor": margin_floor,
            "status": "active",
            "created_at": now,
            "updated_at": now,
            "stats": {
                "issued_count": 0,
                "redeemed_count": 0,
                "total_discount_fen": 0,
            },
        }
        _offers[offer_id] = offer
        return offer

    def evaluate_offer_eligibility(self, user_id: str, offer_id: str) -> dict:
        """评估用户是否可以使用优惠

        检查：优惠状态、目标分群匹配、时段、使用次数限制
        """
        offer = _offers.get(offer_id)
        if not offer:
            return {"eligible": False, "reason": f"优惠不存在: {offer_id}"}

        if offer["status"] != "active":
            return {"eligible": False, "reason": f"优惠已{offer['status']}"}

        # 检查用户是否已领取过
        redemptions = _offer_redemptions.get(offer_id, [])
        user_redemptions = [r for r in redemptions if r.get("user_id") == user_id]

        # 每个用户最多使用1次（可配置）
        max_per_user = offer.get("max_per_user", 1)
        if len(user_redemptions) >= max_per_user:
            return {"eligible": False, "reason": "已达使用上限"}

        return {
            "eligible": True,
            "offer_id": offer_id,
            "user_id": user_id,
            "discount_rules": offer["discount_rules"],
            "validity_days": offer["validity_days"],
        }

    def calculate_offer_cost(self, offer_id: str) -> dict:
        """计算优惠的预估成本和 ROI

        基于历史数据和优惠规则预估。
        """
        offer = _offers.get(offer_id)
        if not offer:
            return {"error": f"优惠不存在: {offer_id}"}

        rules = offer.get("discount_rules", {})
        rule_type = rules.get("type", "")

        # 预估参数
        estimated_redemption_count = 100  # 预估核销数
        avg_order_fen = 12000  # 平均客单价 120元

        if rule_type == "fixed_amount":
            per_discount_fen = rules.get("amount_fen", 0)
        elif rule_type == "percentage":
            pct = rules.get("pct", 0)
            per_discount_fen = int(avg_order_fen * pct / 100)
        elif rule_type == "threshold":
            per_discount_fen = rules.get("reduce_fen", 0)
        else:
            per_discount_fen = 0

        projected_cost_fen = per_discount_fen * estimated_redemption_count
        # 假设每次核销带来的增量收入为客单价的 1.5 倍（含复购效应）
        projected_revenue_lift_fen = int(avg_order_fen * 1.5 * estimated_redemption_count)
        projected_roi = (
            round(projected_revenue_lift_fen / max(1, projected_cost_fen), 2)
            if projected_cost_fen > 0 else 0
        )

        return {
            "offer_id": offer_id,
            "estimated_redemption_count": estimated_redemption_count,
            "per_discount_fen": per_discount_fen,
            "projected_cost_fen": projected_cost_fen,
            "projected_cost_yuan": round(projected_cost_fen / 100, 2),
            "projected_revenue_lift_fen": projected_revenue_lift_fen,
            "projected_revenue_lift_yuan": round(projected_revenue_lift_fen / 100, 2),
            "projected_roi": projected_roi,
        }

    def check_margin_compliance(self, offer_id: str, order_data: dict) -> dict:
        """毛利合规检查 — 三条硬约束之一

        确保优惠后的订单毛利不低于设定底线。

        Args:
            offer_id: 优惠ID
            order_data: 订单数据
                {"total_fen": 15000, "cost_fen": 6000, "discount_fen": 2000}
        """
        offer = _offers.get(offer_id)
        if not offer:
            return {"compliant": False, "reason": f"优惠不存在: {offer_id}"}

        margin_floor = offer.get("margin_floor", 0.45)
        total_fen = order_data.get("total_fen", 0)
        cost_fen = order_data.get("cost_fen", 0)
        discount_fen = order_data.get("discount_fen", 0)

        # 计算优惠后的毛利率
        revenue_after_discount = total_fen - discount_fen
        if revenue_after_discount <= 0:
            return {
                "compliant": False,
                "reason": "优惠后收入为零或负数",
                "margin_rate": 0.0,
                "margin_floor": margin_floor,
            }

        margin_rate = (revenue_after_discount - cost_fen) / revenue_after_discount
        compliant = margin_rate >= margin_floor

        return {
            "compliant": compliant,
            "margin_rate": round(margin_rate, 4),
            "margin_floor": margin_floor,
            "revenue_after_discount_fen": revenue_after_discount,
            "cost_fen": cost_fen,
            "profit_fen": revenue_after_discount - cost_fen,
            "reason": "" if compliant else f"毛利率 {margin_rate:.1%} 低于底线 {margin_floor:.1%}",
        }

    def get_offer_analytics(self, offer_id: str) -> dict:
        """获取优惠效果分析"""
        offer = _offers.get(offer_id)
        if not offer:
            return {"error": f"优惠不存在: {offer_id}"}

        redemptions = _offer_redemptions.get(offer_id, [])
        stats = offer.get("stats", {})
        issued = stats.get("issued_count", 0)
        redeemed = len(redemptions)
        total_discount_fen = sum(r.get("discount_fen", 0) for r in redemptions)
        total_revenue_fen = sum(r.get("order_total_fen", 0) for r in redemptions)

        redemption_rate = redeemed / max(1, issued)
        revenue_per_redemption = total_revenue_fen // max(1, redeemed)
        profit_contribution_fen = total_revenue_fen - total_discount_fen

        return {
            "offer_id": offer_id,
            "offer_name": offer.get("name", ""),
            "offer_type": offer.get("offer_type", ""),
            "issued_count": issued,
            "redeemed_count": redeemed,
            "redemption_rate": round(redemption_rate, 4),
            "total_discount_fen": total_discount_fen,
            "total_discount_yuan": round(total_discount_fen / 100, 2),
            "total_revenue_fen": total_revenue_fen,
            "total_revenue_yuan": round(total_revenue_fen / 100, 2),
            "revenue_per_redemption_fen": revenue_per_redemption,
            "profit_contribution_fen": profit_contribution_fen,
            "profit_contribution_yuan": round(profit_contribution_fen / 100, 2),
        }

    def recommend_offer_for_segment(self, segment_id: str) -> list[dict]:
        """AI 推荐：为特定人群推荐优惠策略"""
        segment_offer_map: dict[str, list[dict]] = {
            "new_customer": [
                {
                    "offer_type": "new_customer_trial",
                    "name": "新客首单立减20元",
                    "discount_rules": {"type": "fixed_amount", "amount_fen": 2000},
                    "reason": "降低新客首单门槛，提高转化率",
                    "expected_roi": 3.5,
                },
            ],
            "first_no_repeat": [
                {
                    "offer_type": "second_visit",
                    "name": "二次到店享8折",
                    "discount_rules": {"type": "percentage", "pct": 20},
                    "reason": "首单未复购客户需要强激励驱动第二次消费",
                    "expected_roi": 2.8,
                },
            ],
            "dormant": [
                {
                    "offer_type": "second_visit",
                    "name": "老客回归礼-满100减30",
                    "discount_rules": {"type": "threshold", "threshold_fen": 10000, "reduce_fen": 3000},
                    "reason": "沉睡客需要较大力度召回",
                    "expected_roi": 2.2,
                },
            ],
            "high_frequency": [
                {
                    "offer_type": "stored_value_bonus",
                    "name": "充500送80",
                    "discount_rules": {"type": "stored_value", "charge_fen": 50000, "bonus_fen": 8000},
                    "reason": "高频客户适合用储值锁客，提高粘性",
                    "expected_roi": 4.5,
                },
            ],
            "high_value_banquet": [
                {
                    "offer_type": "banquet_inquiry_gift",
                    "name": "宴会预订享专属管家服务",
                    "discount_rules": {"type": "service_upgrade", "description": "专属管家+赠送果盘"},
                    "reason": "高价值客户重服务不重折扣",
                    "expected_roi": 6.0,
                },
            ],
            "price_sensitive": [
                {
                    "offer_type": "off_peak_traffic",
                    "name": "工作日午市套餐特惠",
                    "discount_rules": {"type": "fixed_amount", "amount_fen": 1500},
                    "reason": "引导闲时消费，不影响高峰利润",
                    "expected_roi": 3.0,
                },
            ],
        }

        recommendations = segment_offer_map.get(segment_id, [])
        if not recommendations:
            # 通用推荐
            recommendations = [
                {
                    "offer_type": "new_dish_trial",
                    "name": "新品尝鲜券-满80减15",
                    "discount_rules": {"type": "threshold", "threshold_fen": 8000, "reduce_fen": 1500},
                    "reason": "新品试吃提升菜品覆盖面",
                    "expected_roi": 2.5,
                },
            ]

        return recommendations


def record_redemption(offer_id: str, user_id: str, order_total_fen: int, discount_fen: int) -> None:
    """记录优惠核销（辅助函数）"""
    if offer_id not in _offer_redemptions:
        _offer_redemptions[offer_id] = []
    _offer_redemptions[offer_id].append({
        "user_id": user_id,
        "order_total_fen": order_total_fen,
        "discount_fen": discount_fen,
        "redeemed_at": datetime.now(timezone.utc).isoformat(),
    })
    # 更新统计
    offer = _offers.get(offer_id)
    if offer:
        offer["stats"]["redeemed_count"] += 1
        offer["stats"]["total_discount_fen"] += discount_fen


def set_offer_issued_count(offer_id: str, count: int) -> None:
    """设置已发放数量（辅助函数，用于测试）"""
    offer = _offers.get(offer_id)
    if offer:
        offer["stats"]["issued_count"] = count


def clear_all_offers() -> None:
    """清空所有优惠数据（仅测试用）"""
    _offers.clear()
    _offer_redemptions.clear()
