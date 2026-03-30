"""营销活动引擎 — 活动创建/执行/触发/奖励全链路

活动状态机: draft -> active -> paused -> ended
触发引擎: 消费/注册/生日/时间/累计
奖励引擎: 券/积分/储值/实物

AB测试集成：活动若设置了 ab_test_id，在发送内容前自动通过 ABTestService
分配变体，并使用对应变体的 content 替换默认 content。

金额单位: 分(fen)
"""
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# ApprovalService 延迟单例（避免循环导入）
# ---------------------------------------------------------------------------

_approval_service_instance = None


def _get_approval_service():
    """获取 ApprovalService 单例（延迟初始化，避免循环依赖）。"""
    global _approval_service_instance
    if _approval_service_instance is None:
        from services.approval_service import ApprovalService  # noqa: PLC0415
        _approval_service_instance = ApprovalService()
    return _approval_service_instance


# ---------------------------------------------------------------------------
# 内存存储
# ---------------------------------------------------------------------------

_campaigns: dict[str, dict] = {}
_campaign_participants: dict[str, list[dict]] = {}  # campaign_id -> [participant]
_campaign_rewards: dict[str, list[dict]] = {}  # campaign_id -> [reward_log]

# 合法状态转换
_VALID_TRANSITIONS: dict[str, list[str]] = {
    "draft": ["active"],
    "active": ["paused", "ended"],
    "paused": ["active", "ended"],
    "ended": [],
}


# ---------------------------------------------------------------------------
# CampaignEngine
# ---------------------------------------------------------------------------

class CampaignEngine:
    """营销活动引擎 — 活动全生命周期管理"""

    CAMPAIGN_TYPES = [
        "stored_value_gift",    # 储值套餐
        "register_welcome",     # 开卡有礼
        "referral",             # 裂变拉新
        "scan_coupon",          # 扫码领券
        "spend_reward",         # 消费满额送
        "cumulative_amount",    # 累计金额送券
        "cumulative_count",     # 累计次数赠券
        "recharge_coupon",      # 储值赠券
        "fixed_dish",           # 定食营销
        "precision_marketing",  # 精准营销
        "paid_coupon_pack",     # 付费券包
        "points_exchange",      # 积分兑换
        "paid_privilege",       # 付费权益卡
        "birthday",             # 生日营销
        "churn_recovery",       # 挽回流失
        "upgrade_gift",         # 升级送礼
        "profile_reward",       # 完善资料送礼
        "coupon_return",        # 消费券返券
        "sign_in",              # 签到送礼
        "lottery",              # 抽奖
        "red_packet",           # 红包雨
        "report_draw",          # 报名抽奖
    ]

    async def create_campaign(
        self,
        campaign_type: str,
        config: dict,
        tenant_id: str,
        db: Any = None,
    ) -> dict:
        """创建营销活动

        Args:
            campaign_type: 活动类型 (CAMPAIGN_TYPES 之一)
            config: 活动配置 (名称/时间/规则/奖励等)
            tenant_id: 租户ID
            db: 数据库连接 (内存模式下可为 None)
        """
        if campaign_type not in self.CAMPAIGN_TYPES:
            return {"error": f"不支持的活动类型: {campaign_type}"}

        campaign_id = str(uuid.uuid4())[:8]
        now = datetime.now(timezone.utc).isoformat()

        campaign = {
            "campaign_id": campaign_id,
            "campaign_type": campaign_type,
            "tenant_id": tenant_id,
            "name": config.get("name", f"{campaign_type}活动"),
            "description": config.get("description", ""),
            "status": "draft",
            "config": config,
            "start_time": config.get("start_time"),
            "end_time": config.get("end_time"),
            "target_stores": config.get("target_stores", []),
            "target_segments": config.get("target_segments", []),
            "budget_fen": config.get("budget_fen", 0),
            "spent_fen": 0,
            "created_at": now,
            "updated_at": now,
            "stats": {
                "participant_count": 0,
                "reward_count": 0,
                "total_cost_fen": 0,
                "conversion_count": 0,
            },
        }
        _campaigns[campaign_id] = campaign
        _campaign_participants[campaign_id] = []
        _campaign_rewards[campaign_id] = []

        log.info(
            "campaign.created",
            campaign_id=campaign_id,
            campaign_type=campaign_type,
            tenant_id=tenant_id,
        )
        return campaign

    async def start_campaign(
        self, campaign_id: str, tenant_id: str, db: Any = None
    ) -> dict:
        """启动活动 (draft -> active)"""
        campaign = _campaigns.get(campaign_id)
        if not campaign:
            return {"error": f"活动不存在: {campaign_id}"}
        if campaign["tenant_id"] != tenant_id:
            return {"error": "无权操作此活动"}

        current = campaign["status"]
        if "active" not in _VALID_TRANSITIONS.get(current, []):
            return {"error": f"活动状态 {current} 不允许启动"}

        campaign["status"] = "active"
        campaign["updated_at"] = datetime.now(timezone.utc).isoformat()
        log.info("campaign.started", campaign_id=campaign_id, tenant_id=tenant_id)
        return campaign

    async def activate_campaign(
        self,
        campaign_id: str,
        operator_id: str,
        operator_name: str,
        tenant_id: str,
        db: Any = None,
    ) -> dict:
        """激活活动 — 带审批流拦截（draft -> active 或 pending_approval）。

        流程：
            1. 检查活动是否需要审批（审批流触发条件匹配）
            2. 若需要审批：创建审批单，活动保持 draft，返回 pending_approval
            3. 若无需审批：直接调用 _do_activate 激活活动

        Args:
            campaign_id:   活动ID
            operator_id:   操作人员工ID（申请人）
            operator_name: 操作人姓名（冗余存储）
            tenant_id:     租户ID
            db:            数据库会话（AsyncSession，内存模式下可为 None）
        """
        campaign = _campaigns.get(campaign_id)
        if not campaign:
            return {"error": f"活动不存在: {campaign_id}"}
        if campaign["tenant_id"] != tenant_id:
            return {"error": "无权操作此活动"}

        current = campaign["status"]
        if "active" not in _VALID_TRANSITIONS.get(current, []):
            return {"error": f"活动状态 {current} 不允许激活"}

        if db is not None:
            # 构造审批触发数据（字段名与审批流模板的 trigger_conditions 对齐）
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
                log.warning(
                    "campaign.activate_approval_check_failed",
                    campaign_id=campaign_id,
                    error=str(exc),
                )
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
                    log.error(
                        "campaign.activate_create_request_failed",
                        campaign_id=campaign_id,
                        error=str(exc),
                    )
                    # 审批单创建失败时降级直接激活，保证业务连续性，并告警
                    log.warning(
                        "campaign.activate_fallback_direct",
                        campaign_id=campaign_id,
                    )

        return await self._do_activate(campaign_id, tenant_id)

    async def _do_activate(self, campaign_id: str, tenant_id: str) -> dict:
        """直接激活活动（跳过审批，内部调用）。"""
        campaign = _campaigns.get(campaign_id)
        if not campaign:
            return {"error": f"活动不存在: {campaign_id}"}

        campaign["status"] = "active"
        campaign["updated_at"] = datetime.now(timezone.utc).isoformat()
        log.info("campaign.activated", campaign_id=campaign_id, tenant_id=tenant_id)
        return campaign

    async def pause_campaign(
        self, campaign_id: str, tenant_id: str, db: Any = None
    ) -> dict:
        """暂停活动 (active -> paused)"""
        campaign = _campaigns.get(campaign_id)
        if not campaign:
            return {"error": f"活动不存在: {campaign_id}"}
        if campaign["tenant_id"] != tenant_id:
            return {"error": "无权操作此活动"}

        current = campaign["status"]
        if "paused" not in _VALID_TRANSITIONS.get(current, []):
            return {"error": f"活动状态 {current} 不允许暂停"}

        campaign["status"] = "paused"
        campaign["updated_at"] = datetime.now(timezone.utc).isoformat()
        log.info("campaign.paused", campaign_id=campaign_id, tenant_id=tenant_id)
        return campaign

    async def end_campaign(
        self, campaign_id: str, tenant_id: str, db: Any = None
    ) -> dict:
        """结束活动 (active/paused -> ended)"""
        campaign = _campaigns.get(campaign_id)
        if not campaign:
            return {"error": f"活动不存在: {campaign_id}"}
        if campaign["tenant_id"] != tenant_id:
            return {"error": "无权操作此活动"}

        current = campaign["status"]
        if "ended" not in _VALID_TRANSITIONS.get(current, []):
            return {"error": f"活动状态 {current} 不允许结束"}

        campaign["status"] = "ended"
        campaign["updated_at"] = datetime.now(timezone.utc).isoformat()
        log.info("campaign.ended", campaign_id=campaign_id, tenant_id=tenant_id)
        return campaign

    async def check_eligibility(
        self,
        customer_id: str,
        campaign_id: str,
        tenant_id: str,
        db: Any = None,
    ) -> dict:
        """检查客户是否有资格参加活动"""
        campaign = _campaigns.get(campaign_id)
        if not campaign:
            return {"eligible": False, "reason": f"活动不存在: {campaign_id}"}
        if campaign["tenant_id"] != tenant_id:
            return {"eligible": False, "reason": "租户不匹配"}
        if campaign["status"] != "active":
            return {"eligible": False, "reason": f"活动未在进行中(当前: {campaign['status']})"}

        # 预算检查
        budget = campaign.get("budget_fen", 0)
        if budget > 0 and campaign["spent_fen"] >= budget:
            return {"eligible": False, "reason": "活动预算已用完"}

        # 参与次数限制
        config = campaign.get("config", {})
        max_per_customer = config.get("max_per_customer", 1)
        participants = _campaign_participants.get(campaign_id, [])
        customer_participations = [
            p for p in participants if p.get("customer_id") == customer_id
        ]
        if len(customer_participations) >= max_per_customer:
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
        """触发奖励发放

        Args:
            customer_id: 客户ID
            campaign_id: 活动ID
            trigger_event: 触发事件数据
            tenant_id: 租户ID
            db: 数据库连接（AB测试分组需要 AsyncSession；内存模式下可为 None）
            customer_data: 客户属性（用于AB测试分流），例如 {"rfm_level": "S1", "store_id": "s1"}
        """
        eligibility = await self.check_eligibility(
            customer_id, campaign_id, tenant_id, db
        )
        if not eligibility.get("eligible"):
            return {"rewarded": False, "reason": eligibility.get("reason", "不符合条件")}

        campaign = _campaigns[campaign_id]
        config = campaign.get("config", {})

        # ── AB测试集成 ──────────────────────────────────────────────────
        # 若活动关联了 AB 测试，按测试分组选择变体内容
        ab_test_id: Optional[str] = campaign.get("ab_test_id")
        variant_used: Optional[str] = None

        if ab_test_id and db is not None:
            try:
                from services.ab_test_service import ABTestService
                ab_svc = ABTestService()
                customer_uuid = (
                    customer_id
                    if isinstance(customer_id, uuid.UUID)
                    else uuid.UUID(str(customer_id))
                )
                tenant_uuid = (
                    tenant_id
                    if isinstance(tenant_id, uuid.UUID)
                    else uuid.UUID(str(tenant_id))
                )
                test_uuid = uuid.UUID(str(ab_test_id))
                variant_used = await ab_svc.assign_variant(
                    test_id=test_uuid,
                    customer_id=customer_uuid,
                    customer_data=customer_data or {},
                    tenant_id=tenant_uuid,
                    db=db,
                )
                # 从变体列表中找到对应 content，覆盖活动默认 content
                variants: list[dict] = campaign.get("variants", [])
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
                # AB测试分组失败不阻断主流程，降级使用默认 content
                log.warning(
                    "campaign.ab_test_assign_failed",
                    campaign_id=campaign_id,
                    ab_test_id=ab_test_id,
                    customer_id=str(customer_id),
                    error=str(exc),
                )

        reward_config = config.get("reward", {})

        # 调用奖励引擎发放
        reward_engine = RewardEngine()
        reward_result = await reward_engine.grant_reward(
            customer_id, reward_config, tenant_id, db
        )

        # 记录参与
        now = datetime.now(timezone.utc).isoformat()
        participation = {
            "customer_id": customer_id,
            "campaign_id": campaign_id,
            "trigger_event": trigger_event,
            "reward": reward_result,
            "participated_at": now,
            "ab_variant": variant_used,  # None 表示未参与 AB 测试
        }
        _campaign_participants[campaign_id].append(participation)
        _campaign_rewards[campaign_id].append(reward_result)

        # 更新统计
        campaign["stats"]["participant_count"] += 1
        campaign["stats"]["reward_count"] += 1
        reward_cost = reward_result.get("cost_fen", 0)
        campaign["stats"]["total_cost_fen"] += reward_cost
        campaign["spent_fen"] += reward_cost

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

    async def get_campaign_analytics(
        self, campaign_id: str, tenant_id: str, db: Any = None
    ) -> dict:
        """获取活动效果分析"""
        campaign = _campaigns.get(campaign_id)
        if not campaign:
            return {"error": f"活动不存在: {campaign_id}"}
        if campaign["tenant_id"] != tenant_id:
            return {"error": "无权查看此活动"}

        stats = campaign.get("stats", {})
        participants = _campaign_participants.get(campaign_id, [])
        rewards = _campaign_rewards.get(campaign_id, [])

        total_cost_fen = stats.get("total_cost_fen", 0)
        participant_count = stats.get("participant_count", 0)
        budget_fen = campaign.get("budget_fen", 0)
        budget_usage = (
            round(campaign["spent_fen"] / budget_fen, 4)
            if budget_fen > 0
            else 0
        )

        # 按奖励类型分组统计
        reward_breakdown: dict[str, int] = {}
        for r in rewards:
            rtype = r.get("reward_type", "unknown")
            reward_breakdown[rtype] = reward_breakdown.get(rtype, 0) + 1

        return {
            "campaign_id": campaign_id,
            "campaign_name": campaign.get("name", ""),
            "campaign_type": campaign["campaign_type"],
            "status": campaign["status"],
            "participant_count": participant_count,
            "reward_count": stats.get("reward_count", 0),
            "total_cost_fen": total_cost_fen,
            "total_cost_yuan": round(total_cost_fen / 100, 2),
            "budget_fen": budget_fen,
            "budget_usage": budget_usage,
            "reward_breakdown": reward_breakdown,
            "avg_cost_per_participant_fen": (
                total_cost_fen // max(1, participant_count)
            ),
        }


# ---------------------------------------------------------------------------
# TriggerEngine — 触发引擎
# ---------------------------------------------------------------------------

class TriggerEngine:
    """触发引擎: 消费/注册/生日/时间/累计

    根据业务事件自动匹配活动并触发奖励。
    """

    def __init__(self) -> None:
        self._campaign_engine = CampaignEngine()

    async def on_consume(
        self, order: dict, tenant_id: str, db: Any = None
    ) -> list[dict]:
        """消费触发 — 订单完成后检查所有消费类活动

        匹配: spend_reward / cumulative_amount / cumulative_count / coupon_return / fixed_dish
        """
        results: list[dict] = []
        customer_id = order.get("customer_id", "")
        if not customer_id:
            return results

        consume_types = {
            "spend_reward", "cumulative_amount", "cumulative_count",
            "coupon_return", "fixed_dish",
        }
        active_campaigns = [
            c for c in _campaigns.values()
            if c["tenant_id"] == tenant_id
            and c["status"] == "active"
            and c["campaign_type"] in consume_types
        ]

        for campaign in active_campaigns:
            config = campaign.get("config", {})
            campaign_type = campaign["campaign_type"]
            triggered = False

            if campaign_type == "spend_reward":
                threshold_fen = config.get("threshold_fen", 0)
                if order.get("total_fen", 0) >= threshold_fen:
                    triggered = True

            elif campaign_type == "cumulative_amount":
                # 累计金额检查（简化：仅看当单）
                threshold_fen = config.get("cumulative_threshold_fen", 0)
                if order.get("total_fen", 0) >= threshold_fen:
                    triggered = True

            elif campaign_type == "cumulative_count":
                # 累计次数检查
                threshold_count = config.get("cumulative_threshold_count", 0)
                order_count = order.get("order_count", 1)
                if order_count >= threshold_count:
                    triggered = True

            elif campaign_type == "coupon_return":
                # 消费后返券
                triggered = True

            elif campaign_type == "fixed_dish":
                # 检查是否点了指定菜品
                target_dishes = config.get("target_dish_ids", [])
                order_dishes = order.get("dish_ids", [])
                if set(target_dishes) & set(order_dishes):
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
                    "trigger.consume",
                    campaign_id=campaign["campaign_id"],
                    customer_id=customer_id,
                    tenant_id=tenant_id,
                )

        return results

    async def on_register(
        self, customer: dict, tenant_id: str, db: Any = None
    ) -> list[dict]:
        """注册触发 — 新会员开卡后检查注册类活动

        匹配: register_welcome / referral(被邀请人)
        """
        results: list[dict] = []
        customer_id = customer.get("customer_id", "")
        if not customer_id:
            return results

        register_types = {"register_welcome", "referral"}
        active_campaigns = [
            c for c in _campaigns.values()
            if c["tenant_id"] == tenant_id
            and c["status"] == "active"
            and c["campaign_type"] in register_types
        ]

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
                "trigger.register",
                campaign_id=campaign["campaign_id"],
                customer_id=customer_id,
                tenant_id=tenant_id,
            )

        return results

    async def on_birthday(
        self, customer: dict, tenant_id: str, db: Any = None
    ) -> list[dict]:
        """生日触发 — 生日当天/提前N天触发

        匹配: birthday
        """
        results: list[dict] = []
        customer_id = customer.get("customer_id", "")
        if not customer_id:
            return results

        active_campaigns = [
            c for c in _campaigns.values()
            if c["tenant_id"] == tenant_id
            and c["status"] == "active"
            and c["campaign_type"] == "birthday"
        ]

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
                "trigger.birthday",
                campaign_id=campaign["campaign_id"],
                customer_id=customer_id,
                tenant_id=tenant_id,
            )

        return results

    async def on_schedule(
        self, tenant_id: str, db: Any = None
    ) -> list[dict]:
        """定时触发 — 按 cron 规则检查定时类活动

        匹配: precision_marketing (每周几/每月几号自动循环发送)
        """
        results: list[dict] = []
        now = datetime.now(timezone.utc)
        weekday = now.isoweekday()  # 1=周一 ... 7=周日
        day_of_month = now.day

        active_campaigns = [
            c for c in _campaigns.values()
            if c["tenant_id"] == tenant_id
            and c["status"] == "active"
            and c["campaign_type"] == "precision_marketing"
        ]

        for campaign in active_campaigns:
            config = campaign.get("config", {})
            schedule = config.get("schedule", {})
            schedule_type = schedule.get("type", "")

            should_run = False
            if schedule_type == "weekly":
                run_on_weekdays = schedule.get("weekdays", [])
                if weekday in run_on_weekdays:
                    should_run = True
            elif schedule_type == "monthly":
                run_on_days = schedule.get("days_of_month", [])
                if day_of_month in run_on_days:
                    should_run = True
            elif schedule_type == "daily":
                should_run = True

            if should_run:
                # 精准营销：给目标标签人群发送
                target_segments = campaign.get("target_segments", [])
                results.append({
                    "campaign_id": campaign["campaign_id"],
                    "campaign_type": "precision_marketing",
                    "action": "send_to_segments",
                    "target_segments": target_segments,
                    "triggered_at": now.isoformat(),
                })
                log.info(
                    "trigger.schedule",
                    campaign_id=campaign["campaign_id"],
                    schedule_type=schedule_type,
                    tenant_id=tenant_id,
                )

        return results


# ---------------------------------------------------------------------------
# RewardEngine — 奖励引擎
# ---------------------------------------------------------------------------

class RewardEngine:
    """奖励引擎: 券/积分/储值/实物

    统一奖励发放入口, 返回标准化奖励记录。
    """

    REWARD_TYPES = ["coupon", "points", "stored_value", "physical", "privilege"]

    async def grant_reward(
        self,
        customer_id: str,
        reward_config: dict,
        tenant_id: str,
        db: Any = None,
    ) -> dict:
        """发放奖励

        Args:
            customer_id: 客户ID
            reward_config: 奖励配置
                {"type": "coupon", "coupon_id": "...", "amount_fen": 2000}
                {"type": "points", "points": 500}
                {"type": "stored_value", "amount_fen": 5000}
                {"type": "physical", "gift_name": "..."}
                {"type": "privilege", "privilege_id": "...", "days": 30}
            tenant_id: 租户ID
        """
        reward_type = reward_config.get("type", "coupon")
        reward_id = str(uuid.uuid4())[:8]
        now = datetime.now(timezone.utc).isoformat()

        reward = {
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
            # 积分成本: 假设 100积分 = 1元
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
            "reward.granted",
            reward_id=reward_id,
            customer_id=customer_id,
            reward_type=reward_type,
            tenant_id=tenant_id,
        )
        return reward


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def get_campaign(campaign_id: str) -> Optional[dict]:
    """获取活动详情"""
    return _campaigns.get(campaign_id)


def list_campaigns(tenant_id: str, status: Optional[str] = None) -> list[dict]:
    """列出活动"""
    result = [
        c for c in _campaigns.values()
        if c["tenant_id"] == tenant_id
    ]
    if status:
        result = [c for c in result if c["status"] == status]
    return result


def clear_all_campaigns() -> None:
    """清空所有活动数据 (仅测试用)"""
    _campaigns.clear()
    _campaign_participants.clear()
    _campaign_rewards.clear()
