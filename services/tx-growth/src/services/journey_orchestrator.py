"""触发式营销编排引擎 — 事件驱动，不做粗暴群发

基于用户行为事件触发个性化营销旅程，每个旅程由多个节点组成，
节点可以是内容推送、优惠发放、等待、条件分支等。

金额单位：分(fen)
"""
import uuid
from datetime import datetime, timezone
from typing import Any, Optional


# ---------------------------------------------------------------------------
# 内存存储
# ---------------------------------------------------------------------------

_journeys: dict[str, dict] = {}
_journey_executions: dict[str, list[dict]] = {}  # journey_id -> [execution_log]


# ---------------------------------------------------------------------------
# JourneyOrchestratorService
# ---------------------------------------------------------------------------

class JourneyOrchestratorService:
    """触发式营销编排引擎 — 事件驱动，不做粗暴群发"""

    TRIGGER_TYPES = {
        "first_visit_no_repeat_48h": "首次到店后48小时未复购",
        "no_visit_7d": "7天未到店",
        "no_visit_15d": "15天未到店",
        "no_visit_30d": "30天未到店",
        "birthday_approaching": "生日/纪念日临近",
        "dish_repurchase_cycle": "招牌菜复购周期到期",
        "reservation_abandoned": "预订咨询后未下单",
        "banquet_lead_no_close": "宴会线索未成交",
        "review_improved": "门店评分改善",
        "new_dish_launch": "新品上线",
        "weather_change": "天气变化触发",
    }

    # 节点类型
    NODE_TYPES = {
        "send_content": "推送内容",
        "send_offer": "发放优惠",
        "wait": "等待",
        "condition": "条件分支",
        "tag_user": "打标签",
        "notify_staff": "通知门店人员",
    }

    def create_journey(
        self,
        name: str,
        journey_type: str,
        trigger: dict,
        nodes: list[dict],
        target_segment_id: str,
    ) -> dict:
        """创建营销旅程

        Args:
            name: 旅程名称
            journey_type: 旅程类型 "retention" | "activation" | "conversion" | "reactivation"
            trigger: 触发条件 {"type": "no_visit_7d", "params": {}}
            nodes: 节点列表
                [{"node_id": "n1", "type": "send_content", "content_type": "wecom_chat",
                  "content_params": {...}, "next": "n2"},
                 {"node_id": "n2", "type": "wait", "wait_hours": 24, "next": "n3"},
                 {"node_id": "n3", "type": "condition", "condition": {...},
                  "true_next": "n4", "false_next": "n5"}]
            target_segment_id: 目标分群ID
        """
        journey_id = str(uuid.uuid4())[:8]
        now = datetime.now(timezone.utc).isoformat()

        journey = {
            "journey_id": journey_id,
            "name": name,
            "journey_type": journey_type,
            "trigger": trigger,
            "nodes": nodes,
            "target_segment_id": target_segment_id,
            "status": "draft",
            "created_at": now,
            "updated_at": now,
            "stats": {
                "estimated_audience": 0,
                "executed_count": 0,
                "converted_count": 0,
            },
        }
        _journeys[journey_id] = journey
        return journey

    def update_journey(self, journey_id: str, updates: dict) -> dict:
        """更新旅程（仅 draft/paused 状态可更新）"""
        journey = _journeys.get(journey_id)
        if not journey:
            return {"error": f"旅程不存在: {journey_id}"}

        if journey["status"] not in ("draft", "paused"):
            return {"error": f"旅程状态为 {journey['status']}，不可编辑"}

        allowed_fields = {"name", "trigger", "nodes", "target_segment_id", "journey_type"}
        for key, value in updates.items():
            if key in allowed_fields:
                journey[key] = value

        journey["updated_at"] = datetime.now(timezone.utc).isoformat()
        _journeys[journey_id] = journey
        return journey

    def publish_journey(self, journey_id: str) -> dict:
        """发布旅程（draft/paused → published）"""
        journey = _journeys.get(journey_id)
        if not journey:
            return {"error": f"旅程不存在: {journey_id}"}

        if journey["status"] not in ("draft", "paused"):
            return {"error": f"旅程状态为 {journey['status']}，不可发布"}

        # 校验旅程完整性
        nodes = journey.get("nodes", [])
        if not nodes:
            return {"error": "旅程无节点，不可发布"}

        trigger = journey.get("trigger", {})
        if not trigger.get("type"):
            return {"error": "旅程无触发条件，不可发布"}

        journey["status"] = "published"
        journey["published_at"] = datetime.now(timezone.utc).isoformat()
        journey["updated_at"] = journey["published_at"]
        _journeys[journey_id] = journey
        return journey

    def pause_journey(self, journey_id: str) -> dict:
        """暂停旅程"""
        journey = _journeys.get(journey_id)
        if not journey:
            return {"error": f"旅程不存在: {journey_id}"}

        if journey["status"] != "published":
            return {"error": f"旅程状态为 {journey['status']}，不可暂停"}

        journey["status"] = "paused"
        journey["updated_at"] = datetime.now(timezone.utc).isoformat()
        _journeys[journey_id] = journey
        return journey

    def get_journey_detail(self, journey_id: str) -> dict:
        """获取旅程详情"""
        journey = _journeys.get(journey_id)
        if not journey:
            return {"error": f"旅程不存在: {journey_id}"}
        return journey

    def list_journeys(self, status: Optional[str] = None) -> list[dict]:
        """列出旅程（可按状态筛选）"""
        journeys = list(_journeys.values())
        if status:
            journeys = [j for j in journeys if j["status"] == status]
        return journeys

    def evaluate_trigger(self, trigger_type: str, user_data: dict) -> bool:
        """评估触发条件是否满足

        Args:
            trigger_type: 触发类型
            user_data: 用户数据

        Returns:
            是否触发
        """
        if trigger_type not in self.TRIGGER_TYPES:
            return False

        recency_days = user_data.get("recency_days", 0)
        order_count = user_data.get("order_count", 0)
        birthday = user_data.get("birthday_in_days")
        last_signature_dish_days = user_data.get("last_signature_dish_days", 0)
        has_pending_reservation = user_data.get("has_pending_reservation", False)
        has_banquet_lead = user_data.get("has_banquet_lead", False)

        evaluators = {
            "first_visit_no_repeat_48h": lambda: order_count == 1 and recency_days >= 2,
            "no_visit_7d": lambda: recency_days >= 7 and recency_days < 15,
            "no_visit_15d": lambda: recency_days >= 15 and recency_days < 30,
            "no_visit_30d": lambda: recency_days >= 30,
            "birthday_approaching": lambda: birthday is not None and 0 <= birthday <= 7,
            "dish_repurchase_cycle": lambda: last_signature_dish_days >= 14,
            "reservation_abandoned": lambda: has_pending_reservation and recency_days >= 1,
            "new_dish_launch": lambda: True,  # 新品上线对所有人触发
            "weather_change": lambda: user_data.get("weather_trigger", False),
            "banquet_lead_no_close": lambda: has_banquet_lead and user_data.get("banquet_lead_days", 0) >= 3,
            "review_improved": lambda: user_data.get("store_rating_improved", False),
        }

        evaluator = evaluators.get(trigger_type)
        if evaluator:
            return evaluator()
        return False

    def execute_node(self, journey_id: str, node_id: str, user_id: str) -> dict:
        """执行旅程中的单个节点

        Args:
            journey_id: 旅程ID
            node_id: 节点ID
            user_id: 用户ID

        Returns:
            执行结果，包含下一节点ID
        """
        journey = _journeys.get(journey_id)
        if not journey:
            return {"error": f"旅程不存在: {journey_id}"}

        if journey["status"] != "published":
            return {"error": f"旅程未发布，当前状态: {journey['status']}"}

        node = None
        for n in journey.get("nodes", []):
            if n.get("node_id") == node_id:
                node = n
                break

        if not node:
            return {"error": f"节点不存在: {node_id}"}

        now = datetime.now(timezone.utc).isoformat()
        node_type = node.get("type", "")

        result: dict[str, Any] = {
            "journey_id": journey_id,
            "node_id": node_id,
            "user_id": user_id,
            "node_type": node_type,
            "executed_at": now,
            "success": True,
        }

        if node_type == "send_content":
            result["action"] = "content_sent"
            result["content_type"] = node.get("content_type", "wecom_chat")
            result["next_node"] = node.get("next")

        elif node_type == "send_offer":
            result["action"] = "offer_sent"
            result["offer_type"] = node.get("offer_type", "")
            result["next_node"] = node.get("next")

        elif node_type == "wait":
            wait_hours = node.get("wait_hours", 24)
            result["action"] = "waiting"
            result["wait_hours"] = wait_hours
            result["next_node"] = node.get("next")

        elif node_type == "condition":
            # 简化：随机选择分支，实际应评估条件
            condition = node.get("condition", {})
            condition_met = self._evaluate_node_condition(condition, user_id)
            result["action"] = "condition_evaluated"
            result["condition_met"] = condition_met
            result["next_node"] = node.get("true_next") if condition_met else node.get("false_next")

        elif node_type == "tag_user":
            result["action"] = "user_tagged"
            result["tags"] = node.get("tags", [])
            result["next_node"] = node.get("next")

        elif node_type == "notify_staff":
            result["action"] = "staff_notified"
            result["staff_role"] = node.get("staff_role", "store_manager")
            result["next_node"] = node.get("next")

        else:
            result["success"] = False
            result["error"] = f"未知节点类型: {node_type}"

        # 记录执行日志
        if journey_id not in _journey_executions:
            _journey_executions[journey_id] = []
        _journey_executions[journey_id].append(result)

        # 更新统计
        journey["stats"]["executed_count"] += 1
        _journeys[journey_id] = journey

        return result

    def get_journey_stats(self, journey_id: str) -> dict:
        """获取旅程执行统计"""
        journey = _journeys.get(journey_id)
        if not journey:
            return {"error": f"旅程不存在: {journey_id}"}

        executions = _journey_executions.get(journey_id, [])
        unique_users = set(e.get("user_id", "") for e in executions)
        converted = sum(1 for e in executions if e.get("action") == "offer_sent")

        stats = journey.get("stats", {})
        executed_count = len(executions)
        converted_count = converted

        return {
            "journey_id": journey_id,
            "journey_name": journey.get("name", ""),
            "status": journey.get("status", ""),
            "estimated_audience": stats.get("estimated_audience", 0),
            "executed_count": executed_count,
            "unique_users_reached": len(unique_users),
            "converted_count": converted_count,
            "conversion_rate": round(converted_count / max(1, len(unique_users)), 4),
        }

    def simulate_journey(self, journey_id: str) -> dict:
        """模拟旅程执行，预估触达和效果

        不实际发送任何消息，仅计算预估数据。
        """
        journey = _journeys.get(journey_id)
        if not journey:
            return {"error": f"旅程不存在: {journey_id}"}

        nodes = journey.get("nodes", [])
        trigger = journey.get("trigger", {})
        trigger_type = trigger.get("type", "")

        # 预估触达人数（基于触发类型的经验值）
        estimated_reach = {
            "first_visit_no_repeat_48h": 150,
            "no_visit_7d": 320,
            "no_visit_15d": 250,
            "no_visit_30d": 180,
            "birthday_approaching": 45,
            "dish_repurchase_cycle": 200,
            "reservation_abandoned": 30,
            "banquet_lead_no_close": 15,
            "new_dish_launch": 800,
            "weather_change": 500,
            "review_improved": 600,
        }

        reach = estimated_reach.get(trigger_type, 100)

        # 预估各节点转化
        node_simulations: list[dict] = []
        remaining = reach
        for node in nodes:
            node_type = node.get("type", "")
            if node_type == "send_content":
                open_rate = 0.35
                click_rate = 0.12
                node_simulations.append({
                    "node_id": node.get("node_id"),
                    "type": node_type,
                    "estimated_reach": remaining,
                    "estimated_open": int(remaining * open_rate),
                    "estimated_click": int(remaining * click_rate),
                })
                remaining = int(remaining * click_rate)
            elif node_type == "send_offer":
                redemption_rate = 0.25
                node_simulations.append({
                    "node_id": node.get("node_id"),
                    "type": node_type,
                    "estimated_reach": remaining,
                    "estimated_redemption": int(remaining * redemption_rate),
                })
                remaining = int(remaining * redemption_rate)
            elif node_type == "condition":
                true_rate = 0.6
                node_simulations.append({
                    "node_id": node.get("node_id"),
                    "type": node_type,
                    "estimated_true": int(remaining * true_rate),
                    "estimated_false": int(remaining * (1 - true_rate)),
                })
                remaining = int(remaining * true_rate)
            elif node_type == "wait":
                drop_off = 0.1
                remaining = int(remaining * (1 - drop_off))
                node_simulations.append({
                    "node_id": node.get("node_id"),
                    "type": node_type,
                    "wait_hours": node.get("wait_hours", 24),
                    "estimated_continue": remaining,
                })

        return {
            "journey_id": journey_id,
            "simulation": True,
            "estimated_total_reach": reach,
            "estimated_final_conversion": remaining,
            "estimated_conversion_rate": round(remaining / max(1, reach), 4),
            "node_simulations": node_simulations,
        }

    @staticmethod
    def _evaluate_node_condition(condition: dict, user_id: str) -> bool:
        """评估节点条件（简化实现）"""
        condition_type = condition.get("type", "")
        if condition_type == "opened_content":
            return True  # 模拟：假定已打开
        elif condition_type == "clicked_link":
            return False  # 模拟：假定未点击
        elif condition_type == "redeemed_offer":
            return False
        return True


def clear_all_journeys() -> None:
    """辅助函数：清空所有旅程（仅测试用）"""
    _journeys.clear()
    _journey_executions.clear()
