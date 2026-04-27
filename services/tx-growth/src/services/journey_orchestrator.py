"""触发式营销编排引擎 — 事件驱动，不做粗暴群发

基于用户行为事件触发个性化营销旅程，每个旅程由多个节点组成，
节点可以是内容推送、优惠发放、等待、条件分支等。

金额单位：分(fen)
存储层：PostgreSQL journeys + journey_executions 表（v162 迁移创建）
"""

import json
from typing import Any, Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


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

    async def create_journey(
        self,
        name: str,
        journey_type: str,
        trigger: dict,
        nodes: list[dict],
        target_segment_id: str,
        *,
        tenant_id: str,
        db: AsyncSession,
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
            tenant_id: 租户ID
            db: 数据库会话
        """
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )
        initial_stats = {
            "estimated_audience": 0,
            "executed_count": 0,
            "converted_count": 0,
        }
        result = await db.execute(
            text("""
                INSERT INTO journeys
                    (tenant_id, name, journey_type, trigger, nodes,
                     target_segment_id, status, stats)
                VALUES
                    (:tenant_id, :name, :journey_type, :trigger::jsonb,
                     :nodes::jsonb, :target_segment_id, 'draft', :stats::jsonb)
                RETURNING id, tenant_id, name, journey_type, trigger, nodes,
                          target_segment_id, status, stats, created_at, updated_at
            """),
            {
                "tenant_id": tenant_id,
                "name": name,
                "journey_type": journey_type,
                "trigger": json.dumps(trigger, ensure_ascii=False),
                "nodes": json.dumps(nodes, ensure_ascii=False),
                "target_segment_id": target_segment_id,
                "stats": json.dumps(initial_stats, ensure_ascii=False),
            },
        )
        row = result.mappings().one()
        await db.commit()

        journey = dict(row)
        journey["id"] = str(journey["id"])
        journey["tenant_id"] = str(journey["tenant_id"])
        if journey.get("created_at"):
            journey["created_at"] = journey["created_at"].isoformat()
        if journey.get("updated_at"):
            journey["updated_at"] = journey["updated_at"].isoformat()

        logger.info("journey.created", journey_id=journey["id"], name=name, tenant_id=tenant_id)
        return journey

    async def list_journeys(
        self,
        status: Optional[str] = None,
        journey_type: Optional[str] = None,
        *,
        tenant_id: str,
        db: AsyncSession,
    ) -> list[dict]:
        """列出旅程（可按状态/类型筛选）

        Args:
            status: 筛选状态 draft/active/paused/archived
            journey_type: 筛选类型
            tenant_id: 租户ID
            db: 数据库会话
        """
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

        conditions = ["tenant_id = :tenant_id", "is_deleted = FALSE"]
        params: dict[str, Any] = {"tenant_id": tenant_id}

        if status:
            conditions.append("status = :status")
            params["status"] = status
        if journey_type:
            conditions.append("journey_type = :journey_type")
            params["journey_type"] = journey_type

        where = " AND ".join(conditions)
        result = await db.execute(
            text(f"""
                SELECT id, name, journey_type, trigger, nodes, target_segment_id,
                       status, stats, created_at, updated_at
                FROM journeys
                WHERE {where}
                ORDER BY updated_at DESC
            """),
            params,
        )
        rows = result.mappings().all()

        journeys = []
        for row in rows:
            j = dict(row)
            j["id"] = str(j["id"])
            if j.get("created_at"):
                j["created_at"] = j["created_at"].isoformat()
            if j.get("updated_at"):
                j["updated_at"] = j["updated_at"].isoformat()
            journeys.append(j)
        return journeys

    async def get_journey(
        self,
        journey_id: str,
        *,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict:
        """获取旅程详情"""
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )
        result = await db.execute(
            text("""
                SELECT id, name, journey_type, trigger, nodes, target_segment_id,
                       status, stats, created_at, updated_at
                FROM journeys
                WHERE id = :journey_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = FALSE
            """),
            {"journey_id": journey_id, "tenant_id": tenant_id},
        )
        row = result.mappings().one_or_none()
        if row is None:
            return {"error": f"旅程不存在: {journey_id}"}

        j = dict(row)
        j["id"] = str(j["id"])
        if j.get("created_at"):
            j["created_at"] = j["created_at"].isoformat()
        if j.get("updated_at"):
            j["updated_at"] = j["updated_at"].isoformat()
        return j

    async def activate_journey(
        self,
        journey_id: str,
        *,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict:
        """激活旅程（status → active）"""
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )
        result = await db.execute(
            text("""
                UPDATE journeys
                SET status = 'active', updated_at = NOW()
                WHERE id = :journey_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = FALSE
                  AND status IN ('draft', 'paused')
                RETURNING id, name, status, updated_at
            """),
            {"journey_id": journey_id, "tenant_id": tenant_id},
        )
        row = result.mappings().one_or_none()
        if row is None:
            return {"error": f"旅程不存在或状态不允许激活: {journey_id}"}
        await db.commit()

        logger.info("journey.activated", journey_id=journey_id, tenant_id=tenant_id)
        return {"id": str(row["id"]), "name": row["name"], "status": row["status"]}

    async def pause_journey(
        self,
        journey_id: str,
        *,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict:
        """暂停旅程（status → paused）"""
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )
        result = await db.execute(
            text("""
                UPDATE journeys
                SET status = 'paused', updated_at = NOW()
                WHERE id = :journey_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = FALSE
                  AND status = 'active'
                RETURNING id, name, status, updated_at
            """),
            {"journey_id": journey_id, "tenant_id": tenant_id},
        )
        row = result.mappings().one_or_none()
        if row is None:
            return {"error": f"旅程不存在或当前非激活状态: {journey_id}"}
        await db.commit()

        logger.info("journey.paused", journey_id=journey_id, tenant_id=tenant_id)
        return {"id": str(row["id"]), "name": row["name"], "status": row["status"]}

    async def trigger_journey(
        self,
        journey_id: str,
        member_id: str,
        trigger_event: str,
        *,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict:
        """触发旅程执行 — 在 journey_executions 插入一条记录

        Args:
            journey_id: 旅程ID
            member_id: 会员ID
            trigger_event: 触发事件类型
            tenant_id: 租户ID
            db: 数据库会话
        """
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

        # 校验旅程是否存在且激活
        check = await db.execute(
            text("""
                SELECT id, nodes FROM journeys
                WHERE id = :journey_id
                  AND tenant_id = :tenant_id
                  AND status = 'active'
                  AND is_deleted = FALSE
            """),
            {"journey_id": journey_id, "tenant_id": tenant_id},
        )
        journey_row = check.mappings().one_or_none()
        if journey_row is None:
            return {"error": f"旅程不存在或未激活: {journey_id}"}

        # 获取起始节点（nodes 列表第一个）
        nodes = journey_row["nodes"] or []
        first_node_id = nodes[0].get("node_id") if nodes else None

        result = await db.execute(
            text("""
                INSERT INTO journey_executions
                    (tenant_id, journey_id, member_id, trigger_event,
                     current_node_id, status)
                VALUES
                    (:tenant_id, :journey_id, :member_id, :trigger_event,
                     :current_node_id, 'running')
                RETURNING id, journey_id, member_id, trigger_event,
                          current_node_id, status, started_at
            """),
            {
                "tenant_id": tenant_id,
                "journey_id": journey_id,
                "member_id": member_id,
                "trigger_event": trigger_event,
                "current_node_id": first_node_id,
            },
        )
        row = result.mappings().one()
        await db.commit()

        execution = dict(row)
        execution["id"] = str(execution["id"])
        execution["journey_id"] = str(execution["journey_id"])
        if execution.get("started_at"):
            execution["started_at"] = execution["started_at"].isoformat()

        logger.info(
            "journey.triggered",
            journey_id=journey_id,
            member_id=member_id,
            execution_id=execution["id"],
            tenant_id=tenant_id,
        )
        return execution

    async def get_journey_stats(
        self,
        journey_id: str,
        *,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict:
        """获取旅程执行统计（聚合 journey_executions）

        Args:
            journey_id: 旅程ID
            tenant_id: 租户ID
            db: 数据库会话
        """
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

        # 获取旅程基础信息
        j_result = await db.execute(
            text("""
                SELECT id, name, status, stats
                FROM journeys
                WHERE id = :journey_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = FALSE
            """),
            {"journey_id": journey_id, "tenant_id": tenant_id},
        )
        j_row = j_result.mappings().one_or_none()
        if j_row is None:
            return {"error": f"旅程不存在: {journey_id}"}

        # 聚合执行记录
        agg_result = await db.execute(
            text("""
                SELECT
                    COUNT(*)                                              AS total_executions,
                    COUNT(DISTINCT member_id)                            AS unique_members,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed_count,
                    SUM(CASE WHEN status = 'failed'    THEN 1 ELSE 0 END) AS failed_count,
                    SUM(CASE WHEN status = 'running'   THEN 1 ELSE 0 END) AS running_count
                FROM journey_executions
                WHERE journey_id = :journey_id
                  AND tenant_id = :tenant_id
                  AND is_deleted = FALSE
            """),
            {"journey_id": journey_id, "tenant_id": tenant_id},
        )
        agg = agg_result.mappings().one()

        total = agg["total_executions"] or 0
        unique_members = agg["unique_members"] or 0
        completed = agg["completed_count"] or 0

        return {
            "journey_id": journey_id,
            "journey_name": j_row["name"],
            "status": j_row["status"],
            "total_executions": total,
            "unique_members_reached": unique_members,
            "completed_count": completed,
            "failed_count": agg["failed_count"] or 0,
            "running_count": agg["running_count"] or 0,
            "completion_rate": round(completed / max(total, 1), 4),
        }

    def evaluate_trigger(self, trigger_type: str, user_data: dict) -> bool:
        """评估触发条件是否满足（纯业务逻辑，不涉及DB）

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

    def simulate_journey(self, journey: dict) -> dict:
        """模拟旅程执行，预估触达和效果（纯业务逻辑，不涉及DB）

        不实际发送任何消息，仅计算预估数据。
        Args:
            journey: 旅程定义 dict（已从 DB 读取）
        """
        journey_id = str(journey.get("id", ""))
        nodes = journey.get("nodes") or []
        trigger = journey.get("trigger") or {}
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
                node_simulations.append(
                    {
                        "node_id": node.get("node_id"),
                        "type": node_type,
                        "estimated_reach": remaining,
                        "estimated_open": int(remaining * open_rate),
                        "estimated_click": int(remaining * click_rate),
                    }
                )
                remaining = int(remaining * click_rate)
            elif node_type == "send_offer":
                redemption_rate = 0.25
                node_simulations.append(
                    {
                        "node_id": node.get("node_id"),
                        "type": node_type,
                        "estimated_reach": remaining,
                        "estimated_redemption": int(remaining * redemption_rate),
                    }
                )
                remaining = int(remaining * redemption_rate)
            elif node_type == "condition":
                true_rate = 0.6
                node_simulations.append(
                    {
                        "node_id": node.get("node_id"),
                        "type": node_type,
                        "estimated_true": int(remaining * true_rate),
                        "estimated_false": int(remaining * (1 - true_rate)),
                    }
                )
                remaining = int(remaining * true_rate)
            elif node_type == "wait":
                drop_off = 0.1
                remaining = int(remaining * (1 - drop_off))
                node_simulations.append(
                    {
                        "node_id": node.get("node_id"),
                        "type": node_type,
                        "wait_hours": node.get("wait_hours", 24),
                        "estimated_continue": remaining,
                    }
                )

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
