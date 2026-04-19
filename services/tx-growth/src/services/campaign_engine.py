"""营销活动引擎 — 活动创建/执行/触发/奖励全链路（v097 DB 化版本）

活动状态机: draft -> active -> paused -> ended
触发引擎: 消费/注册/生日/时间/累计
奖励引擎: 券/积分/储值/实物

AB测试集成：活动若设置了 ab_test_id，在发送内容前自动通过 ABTestService
分配变体，并使用对应变体的 content 替换默认 content。

金额单位: 分(fen)
存储后端: PostgreSQL（通过 CampaignRepository，v097 迁移）
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

from .campaign_repository import CampaignRepository

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# ApprovalService 延迟单例（避免循环导入）
# ---------------------------------------------------------------------------

_approval_service_instance = None


def _get_approval_service():
    global _approval_service_instance
    if _approval_service_instance is None:
        from .approval_service import ApprovalService  # noqa: PLC0415

        _approval_service_instance = ApprovalService()
    return _approval_service_instance


# ---------------------------------------------------------------------------
# CampaignEngine
# ---------------------------------------------------------------------------


class CampaignEngine:
    """营销活动引擎 — 活动全生命周期管理"""

    CAMPAIGN_TYPES = [
        "stored_value_gift",
        "register_welcome",
        "referral",
        "scan_coupon",
        "spend_reward",
        "cumulative_amount",
        "cumulative_count",
        "recharge_coupon",
        "fixed_dish",
        "precision_marketing",
        "paid_coupon_pack",
        "points_exchange",
        "paid_privilege",
        "birthday",
        "churn_recovery",
        "upgrade_gift",
        "profile_reward",
        "coupon_return",
        "sign_in",
        "lottery",
        "red_packet",
        "report_draw",
        "group_buy",
        "stamp_card",
        "consumption_cashback",
        "nth_item_discount",
    ]

    async def create_campaign(
        self,
        campaign_type: str,
        config: dict,
        tenant_id: str,
        db: Any = None,
    ) -> dict:
        """创建营销活动"""
        if campaign_type not in self.CAMPAIGN_TYPES:
            return {"error": f"不支持的活动类型: {campaign_type}"}
        if db is None:
            return {"error": "db 参数不能为空（v097 已切换到 DB 模式）"}

        repo = CampaignRepository(db, tenant_id)
        return await repo.create_campaign(campaign_type, config)

    async def start_campaign(self, campaign_id: str, tenant_id: str, db: Any = None) -> dict:
        """启动活动 (draft -> active)"""
        if db is None:
            return {"error": "db 参数不能为空"}
        repo = CampaignRepository(db, tenant_id)
        try:
            result = await repo.transition_status(campaign_id, "active")
        except ValueError as exc:
            return {"error": str(exc)}
        if result is None:
            return {"error": f"活动不存在: {campaign_id}"}
        log.info("campaign.started", campaign_id=campaign_id, tenant_id=tenant_id)
        return result

    async def activate_campaign(
        self,
        campaign_id: str,
        operator_id: str,
        operator_name: str,
        tenant_id: str,
        db: Any = None,
    ) -> dict:
        """激活活动 — 带审批流拦截（draft -> active 或 pending_approval）"""
        if db is None:
            return {"error": "db 参数不能为空"}

        repo = CampaignRepository(db, tenant_id)
        campaign = await repo.get_campaign(campaign_id)
        if not campaign:
            return {"error": f"活动不存在: {campaign_id}"}

        current = campaign["status"]
        from .campaign_repository import _VALID_TRANSITIONS

        if "active" not in _VALID_TRANSITIONS.get(current, []):
            return {"error": f"活动状态 {current} 不允许激活"}

        config = campaign.get("config", {})
        approval_object_data = {
            "max_discount_fen": config.get("max_discount_fen", 0),
            "target_count": config.get("target_count", 0),
        }

        approval_svc = _get_approval_service()
        try:
            tenant_uuid = uuid.UUID(tenant_id)
            needs_approval, workflow_id = await approval_svc.check_needs_approval(
                object_type="campaign",
                object_data=approval_object_data,
                tenant_id=tenant_uuid,
                db=db,
            )
        except (ValueError, TypeError) as exc:
            log.warning("campaign.activate_approval_check_failed", campaign_id=campaign_id, error=str(exc))
            needs_approval = False
            workflow_id = None

        if needs_approval and workflow_id is not None:
            try:
                request = await approval_svc.create_request(
                    workflow_id=workflow_id,
                    object_type="campaign",
                    object_id=campaign_id,
                    object_summary={
                        "name": campaign.get("name", ""),
                        "type": campaign.get("campaign_type", ""),
                    },
                    requester_id=uuid.UUID(operator_id),
                    requester_name=operator_name,
                    tenant_id=tenant_uuid,
                    db=db,
                )
                log.info(
                    "campaign.activation_pending_approval",
                    campaign_id=campaign_id,
                    request_id=str(request.id),
                    tenant_id=tenant_id,
                )
                return {
                    "status": "pending_approval",
                    "campaign_id": campaign_id,
                    "request_id": str(request.id),
                    "message": "活动已提交审批，等待审批通过后自动激活",
                }
            except (ValueError, TypeError) as exc:
                log.error("campaign.activate_create_request_failed", campaign_id=campaign_id, error=str(exc))
                log.warning("campaign.activate_fallback_direct", campaign_id=campaign_id)

        return await self._do_activate(campaign_id, tenant_id, db)

    async def _do_activate(self, campaign_id: str, tenant_id: str, db: Any) -> dict:
        """直接激活活动（跳过审批，内部调用）"""
        repo = CampaignRepository(db, tenant_id)
        try:
            result = await repo.transition_status(campaign_id, "active")
        except ValueError as exc:
            return {"error": str(exc)}
        if result is None:
            return {"error": f"活动不存在: {campaign_id}"}
        log.info("campaign.activated", campaign_id=campaign_id, tenant_id=tenant_id)
        return result

    async def pause_campaign(self, campaign_id: str, tenant_id: str, db: Any = None) -> dict:
        """暂停活动 (active -> paused)"""
        if db is None:
            return {"error": "db 参数不能为空"}
        repo = CampaignRepository(db, tenant_id)
        try:
            result = await repo.transition_status(campaign_id, "paused")
        except ValueError as exc:
            return {"error": str(exc)}
        if result is None:
            return {"error": f"活动不存在: {campaign_id}"}
        log.info("campaign.paused", campaign_id=campaign_id, tenant_id=tenant_id)
        return result

    async def end_campaign(self, campaign_id: str, tenant_id: str, db: Any = None) -> dict:
        """结束活动 (active/paused -> ended)"""
        if db is None:
            return {"error": "db 参数不能为空"}
        repo = CampaignRepository(db, tenant_id)
        try:
            result = await repo.transition_status(campaign_id, "ended")
        except ValueError as exc:
            return {"error": str(exc)}
        if result is None:
            return {"error": f"活动不存在: {campaign_id}"}
        log.info("campaign.ended", campaign_id=campaign_id, tenant_id=tenant_id)
        return result

    async def check_eligibility(
        self,
        customer_id: str,
        campaign_id: str,
        tenant_id: str,
        db: Any = None,
    ) -> dict:
        """检查客户是否有资格参加活动"""
        if db is None:
            return {"eligible": False, "reason": "db 参数不能为空"}

        repo = CampaignRepository(db, tenant_id)
        campaign = await repo.get_campaign(campaign_id)
        if not campaign:
            return {"eligible": False, "reason": f"活动不存在: {campaign_id}"}
        if campaign["status"] != "active":
            return {"eligible": False, "reason": f"活动未在进行中(当前: {campaign['status']})"}

        budget = campaign.get("budget_fen", 0)
        if budget > 0 and campaign["spent_fen"] >= budget:
            return {"eligible": False, "reason": "活动预算已用完"}

        config = campaign.get("config", {})
        max_per_customer = config.get("max_per_customer", 1)
        participation_count = await repo.count_customer_participations(campaign_id, customer_id)
        if participation_count >= max_per_customer:
            return {"eligible": False, "reason": "已达参与上限"}

        return {
            "eligible": True,
            "campaign_id": campaign_id,
            "customer_id": customer_id,
            "campaign_type": campaign["campaign_type"],
        }

    async def trigger_reward(
        self,
        customer_id: str,
        campaign_id: str,
        trigger_event: dict,
        tenant_id: str,
        db: Any = None,
        customer_data: Optional[dict] = None,
    ) -> dict:
        """触发奖励发放"""
        eligibility = await self.check_eligibility(customer_id, campaign_id, tenant_id, db)
        if not eligibility.get("eligible"):
            return {"rewarded": False, "reason": eligibility.get("reason", "不符合条件")}

        repo = CampaignRepository(db, tenant_id)
        campaign = await repo.get_campaign(campaign_id)
        if not campaign:
            return {"rewarded": False, "reason": "活动不存在"}

        config = dict(campaign.get("config", {}))

        # ── AB测试集成 ──────────────────────────────────────────────────
        ab_test_id: Optional[str] = campaign.get("ab_test_id")
        variant_used: Optional[str] = None

        if ab_test_id and db is not None:
            try:
                from .ab_test_service import ABTestService

                ab_svc = ABTestService()
                customer_uuid = uuid.UUID(str(customer_id))
                tenant_uuid = uuid.UUID(str(tenant_id))
                test_uuid = uuid.UUID(str(ab_test_id))
                variant_used = await ab_svc.assign_variant(
                    test_id=test_uuid,
                    customer_id=customer_uuid,
                    customer_data=customer_data or {},
                    tenant_id=tenant_uuid,
                    db=db,
                )
                variants: list[dict] = campaign.get("variants") or []
                for v in variants:
                    if v.get("variant") == variant_used:
                        config = {**config, **v.get("content", {})}
                        break
                log.info(
                    "campaign.ab_test_variant_selected",
                    campaign_id=campaign_id,
                    ab_test_id=ab_test_id,
                    customer_id=str(customer_id),
                    variant=variant_used,
                )
            except (ValueError, KeyError) as exc:
                log.warning(
                    "campaign.ab_test_assign_failed",
                    campaign_id=campaign_id,
                    ab_test_id=ab_test_id,
                    customer_id=str(customer_id),
                    error=str(exc),
                )

        reward_config = config.get("reward", {})
        reward_engine = RewardEngine()
        reward_result = await reward_engine.grant_reward(customer_id, reward_config, tenant_id, db)
        reward_cost = reward_result.get("cost_fen", 0)

        await repo.add_participation(
            campaign_id=campaign_id,
            customer_id=customer_id,
            trigger_event=trigger_event,
            reward=reward_result,
            ab_variant=variant_used,
            reward_cost_fen=reward_cost,
        )

        log.info(
            "campaign.reward_triggered",
            campaign_id=campaign_id,
            customer_id=customer_id,
            reward_type=reward_config.get("type"),
            tenant_id=tenant_id,
        )
        return {
            "rewarded": True,
            "campaign_id": campaign_id,
            "customer_id": customer_id,
            "reward": reward_result,
            "ab_variant": variant_used,
        }

    async def get_campaign_analytics(self, campaign_id: str, tenant_id: str, db: Any = None) -> dict:
        """获取活动效果分析"""
        if db is None:
            return {"error": "db 参数不能为空"}
        repo = CampaignRepository(db, tenant_id)
        result = await repo.get_analytics(campaign_id)
        if result is None:
            return {"error": f"活动不存在: {campaign_id}"}
        return result


# ---------------------------------------------------------------------------
# TriggerEngine — 触发引擎
# ---------------------------------------------------------------------------


class TriggerEngine:
    """触发引擎: 消费/注册/生日/时间/累计"""

    def __init__(self) -> None:
        self._campaign_engine = CampaignEngine()

    async def on_consume(self, order: dict, tenant_id: str, db: Any = None) -> list[dict]:
        """消费触发"""
        results: list[dict] = []
        customer_id = order.get("customer_id", "")
        if not customer_id or db is None:
            return results

        repo = CampaignRepository(db, tenant_id)
        consume_types = {
            "spend_reward",
            "cumulative_amount",
            "cumulative_count",
            "coupon_return",
            "fixed_dish",
            "consumption_cashback",
            "nth_item_discount",
        }
        active_campaigns = await repo.get_active_by_types(consume_types)

        for campaign in active_campaigns:
            config = campaign.get("config", {})
            campaign_type = campaign["campaign_type"]
            triggered = False

            if campaign_type == "spend_reward":
                if order.get("total_fen", 0) >= config.get("threshold_fen", 0):
                    triggered = True
            elif campaign_type == "cumulative_amount":
                if order.get("total_fen", 0) >= config.get("cumulative_threshold_fen", 0):
                    triggered = True
            elif campaign_type == "cumulative_count":
                if order.get("order_count", 1) >= config.get("cumulative_threshold_count", 0):
                    triggered = True
            elif campaign_type == "coupon_return":
                triggered = True
            elif campaign_type == "fixed_dish":
                target_dishes = config.get("target_dish_ids", [])
                if set(target_dishes) & set(order.get("dish_ids", [])):
                    triggered = True
            elif campaign_type == "consumption_cashback":
                # 消费返现：有消费金额即触发（execute内部做门槛判断）
                if order.get("total_fen", 0) > 0:
                    triggered = True
            elif campaign_type == "nth_item_discount":
                # 第N份M折：有菜品明细即触发（execute内部做匹配判断）
                if order.get("items") or order.get("dish_ids"):
                    triggered = True

            if triggered:
                result = await self._campaign_engine.trigger_reward(
                    customer_id,
                    campaign["campaign_id"],
                    {"type": "consume", "order": order},
                    tenant_id,
                    db,
                )
                results.append(result)
                log.info(
                    "trigger.consume", campaign_id=campaign["campaign_id"], customer_id=customer_id, tenant_id=tenant_id
                )

        return results

    async def on_register(self, customer: dict, tenant_id: str, db: Any = None) -> list[dict]:
        """注册触发"""
        results: list[dict] = []
        customer_id = customer.get("customer_id", "")
        if not customer_id or db is None:
            return results

        repo = CampaignRepository(db, tenant_id)
        active_campaigns = await repo.get_active_by_types({"register_welcome", "referral"})

        for campaign in active_campaigns:
            result = await self._campaign_engine.trigger_reward(
                customer_id,
                campaign["campaign_id"],
                {"type": "register", "customer": customer},
                tenant_id,
                db,
            )
            results.append(result)
            log.info(
                "trigger.register", campaign_id=campaign["campaign_id"], customer_id=customer_id, tenant_id=tenant_id
            )

        return results

    async def on_birthday(self, customer: dict, tenant_id: str, db: Any = None) -> list[dict]:
        """生日触发"""
        results: list[dict] = []
        customer_id = customer.get("customer_id", "")
        if not customer_id or db is None:
            return results

        repo = CampaignRepository(db, tenant_id)
        active_campaigns = await repo.get_active_by_types({"birthday"})

        for campaign in active_campaigns:
            result = await self._campaign_engine.trigger_reward(
                customer_id,
                campaign["campaign_id"],
                {"type": "birthday", "customer": customer},
                tenant_id,
                db,
            )
            results.append(result)
            log.info(
                "trigger.birthday", campaign_id=campaign["campaign_id"], customer_id=customer_id, tenant_id=tenant_id
            )

        return results

    async def on_schedule(self, tenant_id: str, db: Any = None) -> list[dict]:
        """定时触发 — precision_marketing"""
        results: list[dict] = []
        if db is None:
            return results

        now = datetime.now(timezone.utc)
        weekday = now.isoweekday()
        day_of_month = now.day

        repo = CampaignRepository(db, tenant_id)
        active_campaigns = await repo.get_active_by_types({"precision_marketing"})

        for campaign in active_campaigns:
            config = campaign.get("config", {})
            schedule = config.get("schedule", {})
            schedule_type = schedule.get("type", "")

            should_run = False
            if (
                schedule_type == "weekly"
                and weekday in schedule.get("weekdays", [])
                or schedule_type == "monthly"
                and day_of_month in schedule.get("days_of_month", [])
                or schedule_type == "daily"
            ):
                should_run = True

            if should_run:
                results.append(
                    {
                        "campaign_id": campaign["campaign_id"],
                        "campaign_type": "precision_marketing",
                        "action": "send_to_segments",
                        "target_segments": campaign.get("target_segments", []),
                        "triggered_at": now.isoformat(),
                    }
                )
                log.info(
                    "trigger.schedule",
                    campaign_id=campaign["campaign_id"],
                    schedule_type=schedule_type,
                    tenant_id=tenant_id,
                )

        return results


# ---------------------------------------------------------------------------
# RewardEngine — 奖励引擎（无状态，不依赖 DB）
# ---------------------------------------------------------------------------


class RewardEngine:
    """奖励引擎: 券/积分/储值/实物（奖励发放逻辑保持无状态）"""

    REWARD_TYPES = ["coupon", "points", "stored_value", "physical", "privilege"]

    async def grant_reward(
        self,
        customer_id: str,
        reward_config: dict,
        tenant_id: str,
        db: Any = None,
    ) -> dict:
        """发放奖励（返回标准化奖励记录，由 trigger_reward 负责写入 DB）"""
        reward_type = reward_config.get("type", "coupon")
        reward_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        reward: dict = {
            "reward_id": reward_id,
            "customer_id": customer_id,
            "reward_type": reward_type,
            "tenant_id": tenant_id,
            "granted_at": now,
            "status": "granted",
            "cost_fen": 0,
        }

        if reward_type == "coupon":
            reward["coupon_id"] = reward_config.get("coupon_id", "")
            reward["amount_fen"] = reward_config.get("amount_fen", 0)
            reward["cost_fen"] = reward_config.get("amount_fen", 0)
            reward["validity_days"] = reward_config.get("validity_days", 30)
        elif reward_type == "points":
            reward["points"] = reward_config.get("points", 0)
            reward["cost_fen"] = reward_config.get("points", 0)
        elif reward_type == "stored_value":
            reward["amount_fen"] = reward_config.get("amount_fen", 0)
            reward["cost_fen"] = reward_config.get("amount_fen", 0)
        elif reward_type == "physical":
            reward["gift_name"] = reward_config.get("gift_name", "")
            reward["cost_fen"] = reward_config.get("cost_fen", 0)
        elif reward_type == "privilege":
            reward["privilege_id"] = reward_config.get("privilege_id", "")
            reward["days"] = reward_config.get("days", 30)
            reward["cost_fen"] = reward_config.get("cost_fen", 0)

        log.info(
            "reward.granted", reward_id=reward_id, customer_id=customer_id, reward_type=reward_type, tenant_id=tenant_id
        )
        return reward


# ---------------------------------------------------------------------------
# 模块级便捷函数（供 campaign_routes.py 的 get_campaign / list_campaigns 调用）
# 注意：DB 化后这两个函数需要 db + tenant_id 参数，路由层已更新为使用 engine 方法
# ---------------------------------------------------------------------------


def clear_all_campaigns() -> None:
    """已废弃：v097 DB 化后此函数无效（仅保留供旧测试引用）"""
    log.warning("clear_all_campaigns called but campaigns are now stored in DB")
