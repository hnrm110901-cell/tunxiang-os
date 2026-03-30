"""智能预订 Agent — P0 | 边缘+云端

对标: SevenRooms (Guest CRM) + Anolla (No-Show -24%) + OpenTable (Yield Management)

六大能力:
  1. predict_no_show     — No-Show 概率预测 (8维度模型)
  2. calculate_overbooking — 智能超订策略
  3. enrich_guest_profile — Guest Profile 画像关联 (SevenRooms)
  4. optimize_time_slots  — 动态时段优化 (OpenTable)
  5. generate_confirmation_chain — 预订确认提醒链
  6. attribute_revenue    — 预订渠道营收归因
"""
import math
from datetime import date, timedelta
from typing import Any

import structlog

from ..base import AgentResult, SkillAgent

logger = structlog.get_logger(__name__)

# ── No-Show 风险因子权重 ──
NO_SHOW_BASE_RATE = 0.15  # 基准爽约率 15%

NO_SHOW_INCREASE_FACTORS = {
    "no_deposit":         0.12,  # 未付押金 +12%
    "advance_days_gt_7":  0.08,  # 提前7天以上 +8%
    "party_size_gt_6":    0.05,  # 6人以上大桌 +5%
    "bad_weather":        0.06,  # 恶劣天气 +6%
    "weekday_lunch":      0.04,  # 工作日午餐 +4%
    "history_no_show_2":  0.15,  # 历史爽约≥2次 +15%
    "history_no_show_1":  0.08,  # 历史爽约1次 +8%
    "non_member":         0.08,  # 非会员 +8%
}

NO_SHOW_DECREASE_FACTORS = {
    "deposit_paid":      -0.10,  # 已付押金 -10%
    "member_gold":       -0.08,  # 金卡/钻石会员 -8%
    "member_silver":     -0.04,  # 银卡会员 -4%
    "advance_days_le_1": -0.05,  # 当天/次日预订 -5%
    "weekend_dinner":    -0.03,  # 周末晚餐 -3%
    "has_preorder":      -0.06,  # 已预点菜品 -6%
}

# ── 模拟 Guest Profile 数据 ──
MOCK_PROFILES = {
    "138****6789": {
        "customer_id": "C001", "name": "张总", "member_level": "diamond",
        "visit_count": 42, "total_spend_yuan": 86500, "avg_ticket_yuan": 2060,
        "favorite_dishes": ["招牌剁椒鱼头", "茶油土鸡汤", "口味虾"],
        "dietary_restrictions": ["忌辣（轻度）"], "preferred_seating": "国宾厅/牡丹厅",
        "last_visit_date": "2026-03-20", "birthday": "06-15", "anniversary": "10-01",
        "service_notes": "常客，商务宴请为主，偏好包厢靠窗位。每次必点鱼头。茅台飞天常备。",
    },
    "139****1234": {
        "customer_id": "C002", "name": "李女士", "member_level": "gold",
        "visit_count": 15, "total_spend_yuan": 12800, "avg_ticket_yuan": 853,
        "favorite_dishes": ["农家小炒肉", "凉拌黄瓜", "酸梅汤"],
        "dietary_restrictions": ["素食偏好", "花生过敏"],
        "preferred_seating": "大厅靠窗", "last_visit_date": "2026-03-18",
        "birthday": "03-28", "anniversary": None,
        "service_notes": "带小孩来，需要儿童椅。花生过敏务必告知后厨。",
    },
    "136****5678": {
        "customer_id": "C003", "name": "王经理", "member_level": "gold",
        "visit_count": 28, "total_spend_yuan": 45200, "avg_ticket_yuan": 1614,
        "favorite_dishes": ["小炒黄牛肉", "辣椒炒肉", "土鸡汤"],
        "dietary_restrictions": ["忌海鲜"], "preferred_seating": "芙蓉厅",
        "last_visit_date": "2026-03-25", "birthday": "11-20", "anniversary": None,
        "service_notes": "商务接待常客，喜欢提前摆台。偏好安静包厢。忌海鲜严格执行。",
    },
}


class ReservationIntelligenceAgent(SkillAgent):
    """智能预订 Agent — 对标 SevenRooms + Anolla + OpenTable"""

    agent_id = "reservation_intelligence"
    agent_name = "智能预订"
    description = "No-Show预测、智能超订、Guest Profile画像、时段优化、确认链、营收归因"
    priority = "P0"
    run_location = "edge+cloud"

    def get_supported_actions(self) -> list[str]:
        return [
            "predict_no_show",
            "calculate_overbooking",
            "enrich_guest_profile",
            "optimize_time_slots",
            "generate_confirmation_chain",
            "attribute_revenue",
        ]

    async def execute(self, action: str, params: dict[str, Any]) -> AgentResult:
        dispatch = {
            "predict_no_show": self._predict_no_show,
            "calculate_overbooking": self._calculate_overbooking,
            "enrich_guest_profile": self._enrich_guest_profile,
            "optimize_time_slots": self._optimize_time_slots,
            "generate_confirmation_chain": self._generate_confirmation_chain,
            "attribute_revenue": self._attribute_revenue,
        }
        handler = dispatch.get(action)
        if handler:
            return await handler(params)
        return AgentResult(success=False, action=action, error=f"不支持的操作: {action}")

    # ─────────────────────────────────────────────
    # 1. No-Show 概率预测
    # ─────────────────────────────────────────────

    async def _predict_no_show(self, params: dict[str, Any]) -> AgentResult:
        """基于8个维度计算预订爽约概率"""
        is_deposit_paid = params.get("is_deposit_paid", False)
        advance_days = params.get("advance_days", 3)
        party_size = params.get("party_size", 2)
        weather = params.get("weather", "normal")  # normal/rain/storm
        day_of_week = params.get("day_of_week", 5)  # 0=Mon, 6=Sun
        member_level = params.get("member_level", "none")  # none/silver/gold/diamond
        historical_no_show = params.get("historical_no_show_count", 0)
        has_preorder = params.get("has_preorder", False)
        meal_period = params.get("meal_period", "dinner")  # lunch/dinner

        probability = NO_SHOW_BASE_RATE
        factors_applied: list[str] = []

        # 增加风险因子
        if not is_deposit_paid:
            probability += NO_SHOW_INCREASE_FACTORS["no_deposit"]
            factors_applied.append("未付押金 +12%")
        if advance_days > 7:
            probability += NO_SHOW_INCREASE_FACTORS["advance_days_gt_7"]
            factors_applied.append(f"提前{advance_days}天 +8%")
        if party_size > 6:
            probability += NO_SHOW_INCREASE_FACTORS["party_size_gt_6"]
            factors_applied.append(f"{party_size}人大桌 +5%")
        if weather in ("rain", "storm"):
            probability += NO_SHOW_INCREASE_FACTORS["bad_weather"]
            factors_applied.append(f"天气{weather} +6%")
        if day_of_week < 5 and meal_period == "lunch":
            probability += NO_SHOW_INCREASE_FACTORS["weekday_lunch"]
            factors_applied.append("工作日午餐 +4%")
        if historical_no_show >= 2:
            probability += NO_SHOW_INCREASE_FACTORS["history_no_show_2"]
            factors_applied.append(f"历史爽约{historical_no_show}次 +15%")
        elif historical_no_show == 1:
            probability += NO_SHOW_INCREASE_FACTORS["history_no_show_1"]
            factors_applied.append("历史爽约1次 +8%")
        if member_level == "none":
            probability += NO_SHOW_INCREASE_FACTORS["non_member"]
            factors_applied.append("非会员 +8%")

        # 降低风险因子
        if is_deposit_paid:
            probability += NO_SHOW_DECREASE_FACTORS["deposit_paid"]
            factors_applied.append("已付押金 -10%")
        if member_level in ("gold", "diamond"):
            probability += NO_SHOW_DECREASE_FACTORS["member_gold"]
            factors_applied.append(f"{member_level}会员 -8%")
        elif member_level == "silver":
            probability += NO_SHOW_DECREASE_FACTORS["member_silver"]
            factors_applied.append("银卡会员 -4%")
        if advance_days <= 1:
            probability += NO_SHOW_DECREASE_FACTORS["advance_days_le_1"]
            factors_applied.append("当日/次日 -5%")
        if day_of_week >= 5 and meal_period == "dinner":
            probability += NO_SHOW_DECREASE_FACTORS["weekend_dinner"]
            factors_applied.append("周末晚餐 -3%")
        if has_preorder:
            probability += NO_SHOW_DECREASE_FACTORS["has_preorder"]
            factors_applied.append("已预点菜品 -6%")

        # 限制范围 0-95%
        probability = max(0.0, min(0.95, probability))
        probability_pct = round(probability * 100, 1)

        # 风险等级
        if probability < 0.20:
            risk_level = "low"
        elif probability < 0.50:
            risk_level = "medium"
        else:
            risk_level = "high"

        # 推荐动作
        actions: list[str] = []
        if risk_level == "high":
            if not is_deposit_paid:
                actions.append("建议收取预订押金（¥50-100/人）")
            actions.append("T-2h 发送确认提醒，未回复自动释放")
            actions.append("建议准备候补桌位（超订补位）")
            actions.append("标记高风险，前台重点跟进")
        elif risk_level == "medium":
            actions.append("T-24h 发送预订确认提醒")
            if not is_deposit_paid:
                actions.append("建议引导顾客预付押金")
        else:
            actions.append("常规 T-2h 到店提醒即可")

        logger.info(
            "reservation.no_show_predicted",
            probability=probability_pct, risk_level=risk_level,
            factors=len(factors_applied),
        )

        return AgentResult(
            success=True, action="predict_no_show",
            data={
                "no_show_probability": probability_pct,
                "risk_level": risk_level,
                "factors_applied": factors_applied,
                "recommended_actions": actions,
                "model_version": "v1.0_8factors",
            },
            reasoning=f"No-Show概率 {probability_pct}% ({risk_level})，"
                      f"应用 {len(factors_applied)} 个因子",
            confidence=0.82,
        )

    # ─────────────────────────────────────────────
    # 2. 智能超订策略
    # ─────────────────────────────────────────────

    async def _calculate_overbooking(self, params: dict[str, Any]) -> AgentResult:
        """根据每笔预订的No-Show概率计算安全超订量"""
        total_capacity = params.get("total_capacity", 20)
        current_bookings = params.get("current_bookings", 18)
        reservations = params.get("reservations", [])

        # 计算预期爽约数
        if reservations:
            expected_no_shows = sum(
                r.get("no_show_probability", 15) / 100 for r in reservations
            )
        else:
            avg_rate = params.get("avg_no_show_rate", 0.15)
            expected_no_shows = current_bookings * avg_rate

        # 安全超订 = 预期爽约 × 0.7（保守策略）
        safe_count = math.floor(expected_no_shows * 0.7)
        # 绝对上限 = 容量 × 15%
        max_cap = math.ceil(total_capacity * 0.15)
        overbooking_slots = min(safe_count, max_cap)

        current_utilization = current_bookings / total_capacity if total_capacity > 0 else 0
        projected_utilization = (current_bookings + overbooking_slots) / total_capacity if total_capacity > 0 else 0

        risk = "low" if overbooking_slots <= 1 else ("medium" if overbooking_slots <= 3 else "high")

        logger.info(
            "reservation.overbooking_calculated",
            slots=overbooking_slots, expected_no_shows=round(expected_no_shows, 1),
        )

        return AgentResult(
            success=True, action="calculate_overbooking",
            data={
                "overbooking_slots": overbooking_slots,
                "expected_no_shows": round(expected_no_shows, 1),
                "safe_count": safe_count,
                "max_cap": max_cap,
                "current_utilization": round(current_utilization * 100, 1),
                "projected_utilization": round(projected_utilization * 100, 1),
                "risk_assessment": risk,
                "total_capacity": total_capacity,
                "current_bookings": current_bookings,
            },
            reasoning=f"预期爽约 {expected_no_shows:.1f} 桌，建议超订 {overbooking_slots} 桌 ({risk}风险)",
            confidence=0.78,
        )

    # ─────────────────────────────────────────────
    # 3. Guest Profile 画像关联 (SevenRooms)
    # ─────────────────────────────────────────────

    async def _enrich_guest_profile(self, params: dict[str, Any]) -> AgentResult:
        """预订时自动关联会员画像，注入就餐偏好"""
        phone = params.get("customer_phone", "")
        reservation_id = params.get("reservation_id", "")

        profile = MOCK_PROFILES.get(phone)

        if profile is None:
            return AgentResult(
                success=True, action="enrich_guest_profile",
                data={
                    "matched": False,
                    "phone": phone,
                    "suggestion": "新客户，建议引导注册会员",
                },
                reasoning=f"手机号 {phone} 未匹配到会员画像",
                confidence=0.95,
            )

        # 检查是否有近期特殊日期
        today = date.today()
        special_occasions: list[str] = []
        if profile.get("birthday"):
            bm, bd = profile["birthday"].split("-")
            if abs(today.month - int(bm)) <= 1 and abs(today.day - int(bd)) <= 7:
                special_occasions.append(f"生日将至 ({profile['birthday']})")
        if profile.get("anniversary"):
            am, ad = profile["anniversary"].split("-")
            if abs(today.month - int(am)) <= 1 and abs(today.day - int(ad)) <= 7:
                special_occasions.append(f"纪念日将至 ({profile['anniversary']})")

        logger.info(
            "reservation.guest_profile_enriched",
            customer_id=profile["customer_id"], member_level=profile["member_level"],
            visit_count=profile["visit_count"],
        )

        return AgentResult(
            success=True, action="enrich_guest_profile",
            data={
                "matched": True,
                "customer_id": profile["customer_id"],
                "name": profile["name"],
                "member_level": profile["member_level"],
                "visit_count": profile["visit_count"],
                "total_spend_yuan": profile["total_spend_yuan"],
                "avg_ticket_yuan": profile["avg_ticket_yuan"],
                "favorite_dishes": profile["favorite_dishes"],
                "dietary_restrictions": profile["dietary_restrictions"],
                "preferred_seating": profile["preferred_seating"],
                "last_visit_date": profile["last_visit_date"],
                "service_notes": profile["service_notes"],
                "special_occasions": special_occasions,
                "reservation_id": reservation_id,
            },
            reasoning=f"匹配到 {profile['member_level']} 会员 {profile['name']}，"
                      f"来店 {profile['visit_count']} 次，客单价 ¥{profile['avg_ticket_yuan']}",
            confidence=0.95,
        )

    # ─────────────────────────────────────────────
    # 4. 动态时段优化 (OpenTable Yield Management)
    # ─────────────────────────────────────────────

    async def _optimize_time_slots(self, params: dict[str, Any]) -> AgentResult:
        """分析历史数据，识别高峰/低谷时段并给出优化建议"""
        store_id = params.get("store_id", "")
        target_date = params.get("date", str(date.today()))

        # 模拟历史4周平均数据
        historical = params.get("historical_bookings", [
            {"time_slot": "11:00", "avg_booking": 2, "capacity": 8},
            {"time_slot": "11:30", "avg_booking": 5, "capacity": 8},
            {"time_slot": "12:00", "avg_booking": 8, "capacity": 8},
            {"time_slot": "12:30", "avg_booking": 7, "capacity": 8},
            {"time_slot": "13:00", "avg_booking": 3, "capacity": 8},
            {"time_slot": "17:00", "avg_booking": 2, "capacity": 10},
            {"time_slot": "17:30", "avg_booking": 4, "capacity": 10},
            {"time_slot": "18:00", "avg_booking": 9, "capacity": 10},
            {"time_slot": "18:30", "avg_booking": 10, "capacity": 10},
            {"time_slot": "19:00", "avg_booking": 8, "capacity": 10},
            {"time_slot": "19:30", "avg_booking": 6, "capacity": 10},
            {"time_slot": "20:00", "avg_booking": 3, "capacity": 10},
        ])

        recommendations: list[dict[str, Any]] = []
        peak_slots: list[str] = []
        valley_slots: list[str] = []

        for slot in historical:
            ts = slot["time_slot"]
            util = slot["avg_booking"] / slot["capacity"] if slot["capacity"] > 0 else 0
            demand_level = "peak" if util > 0.80 else ("normal" if util >= 0.40 else "valley")

            rec: dict[str, Any] = {
                "time_slot": ts,
                "avg_booking": slot["avg_booking"],
                "capacity": slot["capacity"],
                "utilization_pct": round(util * 100, 1),
                "demand_level": demand_level,
            }

            if demand_level == "peak":
                peak_slots.append(ts)
                rec["recommendations"] = [
                    "缩短用餐窗口至90分钟",
                    "提高包厢最低消费",
                    "启用超订策略",
                ]
            elif demand_level == "valley":
                valley_slots.append(ts)
                rec["recommendations"] = [
                    "推送时段优惠券（9折/满减）",
                    "延长用餐窗口，提升体验",
                    "开放散座免预约",
                ]
            else:
                rec["recommendations"] = ["维持现有策略"]

            recommendations.append(rec)

        return AgentResult(
            success=True, action="optimize_time_slots",
            data={
                "store_id": store_id,
                "date": target_date,
                "slot_analysis": recommendations,
                "peak_slots": peak_slots,
                "valley_slots": valley_slots,
                "overall_suggestion": (
                    f"高峰 {', '.join(peak_slots)}; "
                    f"低谷 {', '.join(valley_slots)}。"
                    f"建议低谷时段推送'下午茶套餐¥68'或'早鸟优惠9折'引流。"
                ),
            },
            reasoning=f"分析 {len(historical)} 个时段，{len(peak_slots)} 个高峰，{len(valley_slots)} 个低谷",
            confidence=0.80,
        )

    # ─────────────────────────────────────────────
    # 5. 预订确认提醒链
    # ─────────────────────────────────────────────

    async def _generate_confirmation_chain(self, params: dict[str, Any]) -> AgentResult:
        """生成自动确认提醒链"""
        reservation_date = params.get("reservation_date", str(date.today() + timedelta(days=2)))
        reservation_time = params.get("reservation_time", "18:00")
        customer_name = params.get("customer_name", "客人")
        party_size = params.get("party_size", 2)
        is_deposit_paid = params.get("is_deposit_paid", False)
        no_show_risk = params.get("no_show_risk", "medium")
        room_or_table = params.get("room_or_table", "")

        chain: list[dict[str, Any]] = []

        # 高风险且未付押金: T-48h 请求押金
        if no_show_risk == "high" and not is_deposit_paid:
            chain.append({
                "trigger": "T-48h",
                "action": "deposit_request",
                "channel": "wechat",
                "message": (
                    f"【屯象餐厅】{customer_name}您好，您预订了{reservation_date} "
                    f"{reservation_time} {party_size}位{room_or_table}。"
                    f"为确保座位保留，请支付预订押金（¥{party_size * 50}），"
                    f"到店后可抵扣消费。点击支付→"
                ),
                "auto_execute": True,
                "fallback": "T-36h 电话确认",
            })

        # T-24h: 确认提醒
        chain.append({
            "trigger": "T-24h",
            "action": "confirmation_reminder",
            "channel": "sms+wechat",
            "message": (
                f"【屯象餐厅】{customer_name}您好，温馨提醒您明日 "
                f"{reservation_time} {party_size}位{room_or_table}的预订。"
                f"回复'1'确认到店，回复'2'取消预订。"
            ),
            "auto_execute": True,
            "timeout_action": "如24h内未回复，标记为高风险",
        })

        # T-2h: 最终确认 + 导航
        chain.append({
            "trigger": "T-2h",
            "action": "final_confirmation",
            "channel": "wechat",
            "message": (
                f"【屯象餐厅】{customer_name}您好，{reservation_time}的预订已为您保留。"
                f"📍 导航: [门店地址] | 🅿 停车场B2层。"
                f"如需更改请致电: 0731-XXXXXXXX"
            ),
            "auto_execute": True,
        })

        # T+15min: 超时释放
        chain.append({
            "trigger": "T+15min",
            "action": "no_show_release",
            "channel": "system",
            "message": (
                f"{customer_name}的预订已超时15分钟未到店。"
                f"座位自动释放，通知排队候补。"
            ),
            "auto_execute": no_show_risk == "high",
            "manual_confirm": no_show_risk != "high",
        })

        return AgentResult(
            success=True, action="generate_confirmation_chain",
            data={
                "confirmation_chain": chain,
                "chain_length": len(chain),
                "has_deposit_request": not is_deposit_paid and no_show_risk == "high",
                "reservation_summary": {
                    "date": reservation_date,
                    "time": reservation_time,
                    "party_size": party_size,
                    "room_or_table": room_or_table,
                    "risk_level": no_show_risk,
                },
            },
            reasoning=f"生成 {len(chain)} 步确认链，风险等级 {no_show_risk}",
            confidence=0.90,
        )

    # ─────────────────────────────────────────────
    # 6. 预订渠道营收归因
    # ─────────────────────────────────────────────

    async def _attribute_revenue(self, params: dict[str, Any]) -> AgentResult:
        """按渠道统计预订量、营收、爽约率、ROI"""
        reservations = params.get("reservations", [])

        # 如果没传数据，使用模拟数据
        if not reservations:
            reservations = [
                {"channel": "phone", "revenue_yuan": 2800, "no_show": False},
                {"channel": "phone", "revenue_yuan": 1560, "no_show": False},
                {"channel": "phone", "revenue_yuan": 0, "no_show": True},
                {"channel": "wechat", "revenue_yuan": 980, "no_show": False},
                {"channel": "wechat", "revenue_yuan": 1200, "no_show": False},
                {"channel": "wechat", "revenue_yuan": 2100, "no_show": False},
                {"channel": "wechat", "revenue_yuan": 0, "no_show": True},
                {"channel": "meituan", "revenue_yuan": 680, "no_show": False},
                {"channel": "meituan", "revenue_yuan": 750, "no_show": False},
                {"channel": "meituan", "revenue_yuan": 0, "no_show": True},
                {"channel": "meituan", "revenue_yuan": 620, "no_show": False},
                {"channel": "walk_in", "revenue_yuan": 450, "no_show": False},
                {"channel": "walk_in", "revenue_yuan": 380, "no_show": False},
                {"channel": "douyin", "revenue_yuan": 520, "no_show": False},
                {"channel": "douyin", "revenue_yuan": 0, "no_show": True},
            ]

        channel_data: dict[str, dict[str, Any]] = {}
        for r in reservations:
            ch = r.get("channel", "unknown")
            if ch not in channel_data:
                channel_data[ch] = {"count": 0, "revenue": 0, "no_show": 0, "arrived": 0}
            channel_data[ch]["count"] += 1
            channel_data[ch]["revenue"] += r.get("revenue_yuan", 0)
            if r.get("no_show"):
                channel_data[ch]["no_show"] += 1
            else:
                channel_data[ch]["arrived"] += 1

        attribution: list[dict[str, Any]] = []
        for ch, data in channel_data.items():
            no_show_rate = data["no_show"] / data["count"] if data["count"] > 0 else 0
            avg_ticket = data["revenue"] / data["arrived"] if data["arrived"] > 0 else 0
            attribution.append({
                "channel": ch,
                "reservation_count": data["count"],
                "arrived_count": data["arrived"],
                "total_revenue_yuan": data["revenue"],
                "avg_ticket_yuan": round(avg_ticket, 0),
                "no_show_rate_pct": round(no_show_rate * 100, 1),
                "no_show_count": data["no_show"],
            })

        attribution.sort(key=lambda x: x["total_revenue_yuan"], reverse=True)
        top_channel = attribution[0]["channel"] if attribution else "N/A"

        recommendations: list[str] = []
        for a in attribution:
            if a["no_show_rate_pct"] > 30:
                recommendations.append(
                    f"{a['channel']} 爽约率 {a['no_show_rate_pct']}% 偏高，建议强制押金"
                )
            if a["avg_ticket_yuan"] > 1500:
                recommendations.append(
                    f"{a['channel']} 客单价 ¥{a['avg_ticket_yuan']:.0f} 最高，建议加大投放"
                )

        return AgentResult(
            success=True, action="attribute_revenue",
            data={
                "channel_attribution": attribution,
                "top_channel": top_channel,
                "total_reservations": len(reservations),
                "total_revenue_yuan": sum(a["total_revenue_yuan"] for a in attribution),
                "overall_no_show_rate_pct": round(
                    sum(r.get("no_show", False) for r in reservations) / len(reservations) * 100, 1
                ) if reservations else 0,
                "recommendations": recommendations,
            },
            reasoning=f"{len(attribution)} 个渠道，Top渠道 {top_channel}，"
                      f"总营收 ¥{sum(a['total_revenue_yuan'] for a in attribution)}",
            confidence=0.85,
        )
