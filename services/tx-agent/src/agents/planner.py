"""日计划 Agent — 每日06:00自动生成经营计划

调用多个 Skill Agent 协同分析，生成5维经营计划：
排菜建议 + 采购清单 + 排班微调 + 营销触发 + 风险预警
"""
import uuid
from datetime import datetime, timezone


class DailyPlannerAgent:
    """每日经营计划 Agent"""

    def __init__(self, tenant_id: str, store_id: str):
        self.tenant_id = tenant_id
        self.store_id = store_id

    async def generate_daily_plan(self, date: str = "today") -> dict:
        """生成完整日计划"""
        reservations = await self._analyze_reservations()
        inventory = await self._check_inventory()
        traffic = await self._forecast_traffic()
        history = await self._analyze_history()

        menu = self._generate_menu_suggestions(inventory, traffic, history)
        procurement = self._generate_procurement_list(inventory, reservations)
        staffing = self._generate_staffing_adjustments(traffic)
        marketing = self._generate_marketing_triggers(history)
        risks = self._generate_risk_alerts(inventory, reservations)

        total_saving = sum(i.get("expected_impact_fen", 0) for i in menu)
        total_saving += sum(i.get("estimated_cost_fen", 0) for i in procurement) // 10

        return {
            "plan_id": f"PLAN_{date}_{self.store_id}_{uuid.uuid4().hex[:6]}",
            "store_id": self.store_id,
            "plan_date": date,
            "status": "pending_approval",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "menu_suggestions": menu,
            "procurement_list": procurement,
            "staffing_adjustments": staffing,
            "marketing_triggers": marketing,
            "risk_alerts": risks,
            "summary": {
                "total_items": len(menu) + len(procurement) + len(staffing) + len(marketing) + len(risks),
                "menu_count": len(menu),
                "procurement_count": len(procurement),
                "staffing_count": len(staffing),
                "marketing_count": len(marketing),
                "risk_count": len(risks),
                "expected_saving_fen": total_saving,
            },
        }

    async def _analyze_reservations(self) -> dict:
        return {"total_tables": 12, "vip_count": 2, "banquet_count": 1, "total_guests": 86}

    async def _check_inventory(self) -> dict:
        return {
            "surplus": [{"id": "i1", "name": "鲈鱼", "surplus_pct": 40}],
            "shortage": [{"id": "i2", "name": "虾仁", "days_left": 1.5}],
            "normal": [{"id": "i3", "name": "青菜", "days_left": 5}],
        }

    async def _forecast_traffic(self) -> dict:
        return {"predicted_guests": 150, "change_pct": 15, "is_weekend": False, "weather": "sunny"}

    async def _analyze_history(self) -> dict:
        return {
            "same_day_last_week": {"revenue_fen": 820000, "orders": 78},
            "avg_daily": {"revenue_fen": 780000, "orders": 72},
            "inactive_members_3d": 45,
            "birthday_members": 3,
        }

    def _generate_menu_suggestions(self, inventory: dict, traffic: dict, history: dict) -> list:
        suggestions = []
        for item in inventory.get("surplus", []):
            suggestions.append({
                "dish_id": item["id"], "dish_name": f"{item['name']}系列",
                "action": "push", "reason": f"{item['name']}库存充足+{item['surplus_pct']}%",
                "confidence": 0.88, "expected_impact_fen": 80000,
            })
        for item in inventory.get("shortage", []):
            suggestions.append({
                "dish_id": item["id"], "dish_name": f"{item['name']}相关",
                "action": "reduce", "reason": f"{item['name']}库存仅够{item['days_left']}天",
                "confidence": 0.92, "expected_impact_fen": 0,
            })
        return suggestions

    def _generate_procurement_list(self, inventory: dict, reservations: dict) -> list:
        items = []
        for item in inventory.get("shortage", []):
            qty = max(10, reservations.get("total_guests", 0) // 10)
            items.append({
                "ingredient_id": item["id"], "name": item["name"],
                "quantity": qty, "unit": "kg",
                "urgency": "urgent" if item["days_left"] < 2 else "normal",
                "reason": f"库存仅够{item['days_left']}天，今日{reservations.get('total_guests',0)}人预订",
                "estimated_cost_fen": qty * 3500,
            })
        return items

    def _generate_staffing_adjustments(self, traffic: dict) -> list:
        adjustments = []
        if traffic.get("change_pct", 0) > 10:
            adjustments.append({
                "action": "add", "role": "waiter", "count": 1, "shift": "lunch",
                "reason": f"预测客流+{traffic['change_pct']}%（{traffic.get('weather','')}）",
            })
        return adjustments

    def _generate_marketing_triggers(self, history: dict) -> list:
        triggers = []
        inactive = history.get("inactive_members_3d", 0)
        if inactive > 20:
            triggers.append({
                "target": "S2_inactive_3d", "action": "send_coupon",
                "content": "午餐8折优惠券", "target_count": inactive,
                "reason": f"{inactive}位S2会员3天未到店",
            })
        birthday = history.get("birthday_members", 0)
        if birthday > 0:
            triggers.append({
                "target": "birthday_today", "action": "send_blessing",
                "content": "生日祝福+赠菜券", "target_count": birthday,
                "reason": f"今日{birthday}位会员生日",
            })
        return triggers

    def _generate_risk_alerts(self, inventory: dict, reservations: dict) -> list:
        alerts = []
        for item in inventory.get("shortage", []):
            if item["days_left"] < 1:
                alerts.append({
                    "type": "inventory_critical", "severity": "critical",
                    "detail": f"{item['name']}今日可能断货",
                    "suggested_action": "紧急采购或临时替换菜品",
                })
        if reservations.get("banquet_count", 0) > 0:
            alerts.append({
                "type": "banquet_prep", "severity": "info",
                "detail": f"今日{reservations['banquet_count']}场宴会，请提前备料",
                "suggested_action": "确认宴会菜单+食材到位",
            })
        return alerts

    @staticmethod
    def approve_plan(plan: dict, approved_items: list, rejected_items: list, notes: str = "") -> dict:
        """审批计划"""
        total = plan["summary"]["total_items"]
        approved_count = len(approved_items)
        status = "approved" if approved_count == total else "partial" if approved_count > 0 else "rejected"
        return {
            **plan,
            "status": status,
            "approved_items": approved_items,
            "rejected_items": rejected_items,
            "approval_notes": notes,
            "approved_at": datetime.now(timezone.utc).isoformat(),
        }
