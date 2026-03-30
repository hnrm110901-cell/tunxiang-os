"""
旅程执行引擎 — 驱动已发布旅程的节点逐步执行

运行方式：
    APScheduler 每60秒调用 JourneyExecutor().tick()

节点类型处理：
    wait         → 检查等待时间是否已到，到了则推进
    send_content → 调用 ChannelEngine 发送内容
    send_offer   → 通过 tx-member 发券
    condition    → 查询会员行为，判断是否转化，走 true/false 分支
    tag_user     → 调用 tx-member API 打标签
    notify_staff → 调用 tx-ops 发企微通知

数据模型说明：
    - 旅程定义存储在 journey_orchestrator._journeys（内存 dict）
    - 旅程实例（JourneyInstance）存储在本模块的 _journey_instances（内存 dict）
    - 执行日志追加写入 journey_orchestrator._journey_executions

Journey instance schema：
    {
        "instance_id":     str,          # 唯一标识
        "journey_id":      str,          # 关联旅程
        "customer_id":     str,          # 触达的客户
        "tenant_id":       str,          # 租户 ID（从旅程继承）
        "status":          str,          # "running" | "completed" | "failed" | "paused"
        "current_node_id": str | None,   # 当前待执行节点
        "next_execute_at": str,          # ISO 8601，何时执行下一步
        "created_at":      str,          # 实例创建时间
        "updated_at":      str,          # 最后更新时间
        "retry_count":     int,          # 当前节点重试次数
        "context":         dict,         # 运行时上下文（如条件分支结果）
    }
"""

import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any

import httpx
import structlog

from services.journey_orchestrator import (
    _journeys,
    _journey_executions,
)

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# 内存存储：旅程实例（JourneyInstance）
# ---------------------------------------------------------------------------

_journey_instances: dict[str, dict] = {}
# key: instance_id
# 查询辅助索引：journey_id + customer_id → instance_id（运行中）
_active_instance_index: dict[str, str] = {}
# key: f"{journey_id}:{customer_id}" → instance_id


# ---------------------------------------------------------------------------
# 最大重试次数
# ---------------------------------------------------------------------------

_MAX_RETRY = 3


# ---------------------------------------------------------------------------
# JourneyExecutor
# ---------------------------------------------------------------------------


class JourneyExecutor:
    """
    旅程执行引擎。

    架构选择：
    - 与 journey_orchestrator.py 保持一致，使用内存存储（无 DB 依赖）。
    - 生产化时替换 _journey_instances / _active_instance_index 为数据库查询即可。
    - 外部服务调用均使用 httpx.AsyncClient，timeout=10 秒。
    """

    TX_MEMBER_URL: str = os.getenv("TX_MEMBER_SERVICE_URL", "http://tx-member:8000")
    TX_OPS_URL: str = os.getenv("TX_OPS_SERVICE_URL", "http://tx-ops:8000")

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    async def tick(self) -> dict[str, int]:
        """
        主入口：APScheduler 每60秒调用一次。

        Returns:
            本次 tick 的简要统计：
            {"triggers_created": int, "nodes_advanced": int, "nodes_failed": int}
        """
        log = logger.bind(tick_at=datetime.now(timezone.utc).isoformat())
        log.info("journey_executor_tick_start")

        triggers_created = await self._scan_triggers()
        advanced, failed = await self._advance_pending_nodes()

        log.info(
            "journey_executor_tick_done",
            triggers_created=triggers_created,
            nodes_advanced=advanced,
            nodes_failed=failed,
        )
        return {
            "triggers_created": triggers_created,
            "nodes_advanced": advanced,
            "nodes_failed": failed,
        }

    # ------------------------------------------------------------------
    # 触发器扫描：为符合条件的客户创建旅程实例
    # ------------------------------------------------------------------

    async def _scan_triggers(self) -> int:
        """
        扫描所有 status="published" 的旅程，按触发类型找出匹配客户，
        并为每个尚无运行中实例的客户创建 JourneyInstance。

        当前实现：
          - no_visit_30d       ✅ 实现（查 tx-member 客户列表）
          - birthday_approaching ✅ 实现（查 tx-member 客户列表）
          - 其余触发类型        TODO 预留，结构已对齐

        Returns:
            本次新建的实例数量
        """
        now = datetime.now(timezone.utc)
        created_count = 0

        published_journeys = [
            j for j in _journeys.values() if j.get("status") == "published"
        ]

        for journey in published_journeys:
            journey_id: str = journey["journey_id"]
            trigger_type: str = journey.get("trigger", {}).get("type", "")
            # tenant_id 来自旅程定义，旅程创建时由调用方写入；若无则用空串
            tenant_id: str = journey.get("tenant_id", "")
            nodes: list[dict] = journey.get("nodes", [])

            if not nodes:
                continue

            first_node_id: str = nodes[0].get("node_id", "")

            # 按触发类型拉取候选客户 ID 列表
            candidate_ids: list[str] = await self._fetch_trigger_candidates(
                trigger_type, tenant_id, journey.get("trigger", {})
            )

            for customer_id in candidate_ids:
                index_key = f"{journey_id}:{customer_id}"
                if index_key in _active_instance_index:
                    # 已有运行中实例，跳过
                    continue

                instance = _create_instance(
                    journey_id=journey_id,
                    customer_id=customer_id,
                    tenant_id=tenant_id,
                    first_node_id=first_node_id,
                    now=now,
                )
                _journey_instances[instance["instance_id"]] = instance
                _active_instance_index[index_key] = instance["instance_id"]
                created_count += 1

                logger.info(
                    "journey_instance_created",
                    journey_id=journey_id,
                    customer_id=customer_id,
                    instance_id=instance["instance_id"],
                    trigger_type=trigger_type,
                )

        return created_count

    async def _fetch_trigger_candidates(
        self,
        trigger_type: str,
        tenant_id: str,
        trigger_params: dict,
    ) -> list[str]:
        """
        根据触发类型，从 tx-member 拉取符合条件的 customer_id 列表。

        Args:
            trigger_type:   触发类型字符串
            tenant_id:      租户 ID（用于 X-Tenant-ID header）
            trigger_params: 旅程 trigger 字典（含 params 子键）

        Returns:
            customer_id 列表
        """
        if trigger_type == "no_visit_30d":
            return await self._fetch_no_visit_customers(
                days=30, tenant_id=tenant_id
            )

        elif trigger_type == "no_visit_15d":
            # TODO: 实现 15 天未到店触发
            return []

        elif trigger_type == "no_visit_7d":
            # TODO: 实现 7 天未到店触发
            return []

        elif trigger_type == "birthday_approaching":
            return await self._fetch_birthday_approaching_customers(
                within_days=7, tenant_id=tenant_id
            )

        elif trigger_type == "first_visit_no_repeat_48h":
            # TODO: 查首次到店后48小时无复购
            return []

        elif trigger_type == "dish_repurchase_cycle":
            # TODO: 查招牌菜复购周期到期
            return []

        elif trigger_type == "reservation_abandoned":
            # TODO: 查预订咨询后未下单
            return []

        elif trigger_type == "banquet_lead_no_close":
            # TODO: 查宴会线索未成交3天
            return []

        elif trigger_type == "review_improved":
            # TODO: 查门店评分改善事件
            return []

        elif trigger_type == "new_dish_launch":
            # TODO: 新品上线广播触发，需要从营销活动事件读取
            return []

        elif trigger_type == "weather_change":
            # TODO: 对接天气 API 触发
            return []

        else:
            logger.warning(
                "unknown_trigger_type",
                trigger_type=trigger_type,
            )
            return []

    async def _fetch_no_visit_customers(
        self,
        days: int,
        tenant_id: str,
    ) -> list[str]:
        """
        从 tx-member 查询 last_order_at 超过 {days} 天的客户。

        API: GET /api/v1/member/customers?no_visit_days={days}
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self.TX_MEMBER_URL}/api/v1/member/customers",
                    headers={"X-Tenant-ID": tenant_id},
                    params={"no_visit_days": days, "page": 1, "size": 500},
                )
            resp.raise_for_status()
            payload = resp.json()
            items: list[dict] = payload.get("data", {}).get("items", [])
            return [item["customer_id"] for item in items if item.get("customer_id")]
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "fetch_no_visit_customers_http_error",
                status_code=exc.response.status_code,
                days=days,
            )
            return []
        except httpx.RequestError as exc:
            logger.warning(
                "fetch_no_visit_customers_request_error",
                error=str(exc),
                days=days,
            )
            return []

    async def _fetch_birthday_approaching_customers(
        self,
        within_days: int,
        tenant_id: str,
    ) -> list[str]:
        """
        从 tx-member 查询 {within_days} 天内生日的客户。

        API: GET /api/v1/member/customers?birthday_within_days={within_days}
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self.TX_MEMBER_URL}/api/v1/member/customers",
                    headers={"X-Tenant-ID": tenant_id},
                    params={
                        "birthday_within_days": within_days,
                        "page": 1,
                        "size": 500,
                    },
                )
            resp.raise_for_status()
            payload = resp.json()
            items: list[dict] = payload.get("data", {}).get("items", [])
            return [item["customer_id"] for item in items if item.get("customer_id")]
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "fetch_birthday_customers_http_error",
                status_code=exc.response.status_code,
                within_days=within_days,
            )
            return []
        except httpx.RequestError as exc:
            logger.warning(
                "fetch_birthday_customers_request_error",
                error=str(exc),
                within_days=within_days,
            )
            return []

    # ------------------------------------------------------------------
    # 节点推进：逐步执行待执行节点
    # ------------------------------------------------------------------

    async def _advance_pending_nodes(self) -> tuple[int, int]:
        """
        遍历所有 status="running" 且 next_execute_at <= now 的实例，
        逐个执行当前节点。

        Returns:
            (advanced_count, failed_count)
        """
        now = datetime.now(timezone.utc)
        advanced = 0
        failed = 0

        # 筛选到期实例（遍历内存字典副本，避免遍历中修改）
        pending: list[dict] = [
            inst
            for inst in list(_journey_instances.values())
            if inst.get("status") == "running"
            and _parse_dt(inst.get("next_execute_at", "")) <= now
        ]

        for instance in pending:
            instance_id: str = instance["instance_id"]
            journey_id: str = instance["journey_id"]
            tenant_id: str = instance.get("tenant_id", "")

            journey = _journeys.get(journey_id)
            if not journey:
                logger.warning(
                    "journey_not_found_for_instance",
                    instance_id=instance_id,
                    journey_id=journey_id,
                )
                _mark_instance(instance_id, "failed")
                failed += 1
                continue

            # 旅程已被暂停，实例随之暂停
            if journey.get("status") == "paused":
                _mark_instance(instance_id, "paused")
                continue

            current_node_id: str | None = instance.get("current_node_id")
            if not current_node_id:
                # 无下一节点，旅程完成
                _mark_instance(instance_id, "completed")
                _remove_active_index(journey_id, instance["customer_id"])
                logger.info(
                    "journey_instance_completed",
                    instance_id=instance_id,
                    journey_id=journey_id,
                )
                advanced += 1
                continue

            node = _find_node(journey, current_node_id)
            if not node:
                logger.warning(
                    "node_not_found",
                    instance_id=instance_id,
                    node_id=current_node_id,
                )
                _mark_instance(instance_id, "failed")
                _remove_active_index(journey_id, instance["customer_id"])
                failed += 1
                continue

            try:
                result = await self._execute_node(instance, node, tenant_id)
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "node_execute_http_error",
                    instance_id=instance_id,
                    node_id=current_node_id,
                    status_code=exc.response.status_code,
                )
                result = None
            except httpx.RequestError as exc:
                logger.warning(
                    "node_execute_request_error",
                    instance_id=instance_id,
                    node_id=current_node_id,
                    error=str(exc),
                )
                result = None

            if result is None:
                # 执行失败，重试计数
                _handle_retry(instance_id)
                inst_ref = _journey_instances[instance_id]
                if inst_ref["retry_count"] >= _MAX_RETRY:
                    _mark_instance(instance_id, "failed")
                    _remove_active_index(journey_id, instance["customer_id"])
                    logger.error(
                        "journey_instance_max_retry_exceeded",
                        instance_id=instance_id,
                        node_id=current_node_id,
                    )
                    failed += 1
                continue

            # 执行成功，更新实例状态
            _append_execution_log(journey_id, instance_id, instance["customer_id"], node, result)
            _advance_instance(instance, node, result, now)
            advanced += 1

        return advanced, failed

    # ------------------------------------------------------------------
    # 节点执行分发
    # ------------------------------------------------------------------

    async def _execute_node(
        self,
        instance: dict,
        node: dict,
        tenant_id: str,
    ) -> dict[str, Any]:
        """
        按节点类型分发执行，返回执行结果 dict。
        返回 None 表示失败（由调用方处理重试）。
        """
        node_type: str = node.get("type", "")

        if node_type == "wait":
            wait_hours: int = int(node.get("wait_hours", 24))
            resume_at = (
                datetime.now(timezone.utc) + timedelta(hours=wait_hours)
            ).isoformat()
            return {"action": "wait", "resume_at": resume_at}

        elif node_type == "send_content":
            return await self._send_content(instance, node, tenant_id)

        elif node_type == "send_offer":
            return await self._send_offer(instance, node, tenant_id)

        elif node_type == "condition":
            return await self._check_condition(instance, node, tenant_id)

        elif node_type == "tag_user":
            return await self._tag_user(instance, node, tenant_id)

        elif node_type == "notify_staff":
            return await self._notify_staff(instance, node, tenant_id)

        else:
            logger.warning("unknown_node_type", node_type=node_type)
            return {"action": "skip"}

    # ------------------------------------------------------------------
    # 具体节点处理方法
    # ------------------------------------------------------------------

    async def _send_content(
        self,
        instance: dict,
        node: dict,
        tenant_id: str,
    ) -> dict[str, Any]:
        """
        通过 tx-ops 通知服务推送内容（企微/短信/小程序消息）。

        节点字段：
            content_type:   "wecom_chat" | "sms" | "miniapp"
            content_params: {"title": str, "description": str, "content": str}
        """
        content_type: str = node.get("content_type", "wecom_chat")
        content_params: dict = node.get("content_params", {})

        channel = "wecom" if "wecom" in content_type else content_type

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{self.TX_OPS_URL}/api/v1/ops/notifications",
                headers={"X-Tenant-ID": tenant_id},
                json={
                    "recipient_id": instance["customer_id"],
                    "channel": channel,
                    "title": content_params.get("title", ""),
                    "content": content_params.get(
                        "description",
                        content_params.get("content", ""),
                    ),
                },
            )
        resp.raise_for_status()
        data: dict = resp.json().get("data", {})
        return {"action": "content_sent", "channel": channel, **data}

    async def _send_offer(
        self,
        instance: dict,
        node: dict,
        tenant_id: str,
    ) -> dict[str, Any]:
        """
        通过 tx-member 优惠券接口发放优惠。

        节点字段：
            offer_type:   "coupon" | "points" | "stored_value"
            offer_params: {"coupon_id": str, "amount_fen": int, ...}
        """
        offer_params: dict = node.get("offer_params", {})

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{self.TX_MEMBER_URL}/api/v1/member/coupons/issue",
                headers={"X-Tenant-ID": tenant_id},
                json={
                    "customer_id": instance["customer_id"],
                    "coupon_type": node.get("offer_type", "coupon"),
                    **offer_params,
                },
            )
        resp.raise_for_status()
        data: dict = resp.json().get("data", {})
        return {"action": "offer_sent", "offer_type": node.get("offer_type", "coupon"), **data}

    async def _check_condition(
        self,
        instance: dict,
        node: dict,
        tenant_id: str,
    ) -> dict[str, Any]:
        """
        条件分支节点：查询会员状态，决定走 true_next 还是 false_next。

        支持的条件类型：
            is_converted — 旅程开始后是否有新订单

        节点字段：
            condition:   {"type": "is_converted"}
            true_next:   str (node_id)
            false_next:  str (node_id)
        """
        condition: dict = node.get("condition", {})
        condition_type: str = condition.get("type", "")

        if condition_type == "is_converted":
            is_converted = await self._query_is_converted(instance, tenant_id)
            next_node_id = (
                node.get("true_next") if is_converted else node.get("false_next")
            )
            return {
                "action": "branch",
                "condition_type": condition_type,
                "result": is_converted,
                "next_node_id": next_node_id,
            }

        # TODO: 支持更多条件类型（opened_content / clicked_link / redeemed_offer）
        logger.warning(
            "unknown_condition_type",
            condition_type=condition_type,
            instance_id=instance["instance_id"],
        )
        return {
            "action": "branch",
            "condition_type": condition_type,
            "result": False,
            "next_node_id": node.get("false_next"),
        }

    async def _query_is_converted(
        self,
        instance: dict,
        tenant_id: str,
    ) -> bool:
        """
        查询会员在旅程实例创建后是否产生了新订单（视为转化）。
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self.TX_MEMBER_URL}/api/v1/member/customers/{instance['customer_id']}",
                    headers={"X-Tenant-ID": tenant_id},
                )
            resp.raise_for_status()
            customer: dict = resp.json().get("data", {})
            last_order_at: str | None = customer.get("last_order_at")
            if not last_order_at:
                return False
            last_order_dt = datetime.fromisoformat(
                last_order_at.replace("Z", "+00:00")
            )
            instance_created_at = _parse_dt(instance["created_at"])
            return last_order_dt > instance_created_at
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "query_is_converted_http_error",
                status_code=exc.response.status_code,
                customer_id=instance["customer_id"],
            )
            return False
        except httpx.RequestError as exc:
            logger.warning(
                "query_is_converted_request_error",
                error=str(exc),
                customer_id=instance["customer_id"],
            )
            return False

    async def _tag_user(
        self,
        instance: dict,
        node: dict,
        tenant_id: str,
    ) -> dict[str, Any]:
        """
        给会员打标签。

        节点字段：
            tags: list[str]  如 ["churn_risk", "birthday_7d"]
        """
        tags: list[str] = node.get("tags", [])

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{self.TX_MEMBER_URL}/api/v1/member/customers/{instance['customer_id']}/tags",
                headers={"X-Tenant-ID": tenant_id},
                json={"tags": tags},
            )
        resp.raise_for_status()
        data: dict = resp.json().get("data", {})
        return {"action": "user_tagged", "tags": tags, **data}

    async def _notify_staff(
        self,
        instance: dict,
        node: dict,
        tenant_id: str,
    ) -> dict[str, Any]:
        """
        通知门店人员（通过企微）。

        节点字段：
            staff_id:  str  收件人（staff_id 或 "store_manager"）
            title:     str  通知标题
            content:   str  通知内容（支持占位符 {customer_id}）
        """
        customer_id: str = instance["customer_id"]
        content_template: str = node.get(
            "content",
            f"请跟进客户 {customer_id}",
        )
        content = content_template.replace("{customer_id}", customer_id)

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{self.TX_OPS_URL}/api/v1/ops/notifications",
                headers={"X-Tenant-ID": tenant_id},
                json={
                    "recipient_id": node.get("staff_id", "store_manager"),
                    "channel": "wecom",
                    "title": node.get("title", "旅程任务提醒"),
                    "content": content,
                },
            )
        resp.raise_for_status()
        data: dict = resp.json().get("data", {})
        return {"action": "staff_notified", "staff_id": node.get("staff_id", "store_manager"), **data}


# ---------------------------------------------------------------------------
# 辅助函数（模块级，避免实例方法臃肿）
# ---------------------------------------------------------------------------


def _create_instance(
    journey_id: str,
    customer_id: str,
    tenant_id: str,
    first_node_id: str,
    now: datetime,
) -> dict:
    """构造一个新的旅程实例 dict。"""
    now_iso = now.isoformat()
    return {
        "instance_id": str(uuid.uuid4()),
        "journey_id": journey_id,
        "customer_id": customer_id,
        "tenant_id": tenant_id,
        "status": "running",
        "current_node_id": first_node_id,
        "next_execute_at": now_iso,  # 立即可执行
        "created_at": now_iso,
        "updated_at": now_iso,
        "retry_count": 0,
        "context": {},
    }


def _find_node(journey: dict, node_id: str) -> dict | None:
    """在旅程的 nodes 列表中按 node_id 查找节点。"""
    for node in journey.get("nodes", []):
        if node.get("node_id") == node_id:
            return node
    return None


def _advance_instance(
    instance: dict,
    node: dict,
    result: dict,
    now: datetime,
) -> None:
    """
    执行成功后推进实例状态：
    - 更新 current_node_id 为下一节点
    - 若是 wait 节点，更新 next_execute_at
    - 重置 retry_count
    """
    action = result.get("action", "")

    if action == "wait":
        # wait 节点：不切换 node_id，但更新执行时间
        resume_at: str = result.get("resume_at", now.isoformat())
        instance["next_execute_at"] = resume_at
        instance["current_node_id"] = node.get("next")
    elif action == "branch":
        # condition 节点：走分支指定的 next_node_id
        next_node_id: str | None = result.get("next_node_id")
        instance["current_node_id"] = next_node_id
        instance["next_execute_at"] = now.isoformat()
    else:
        # 其他节点：直接跳到 next
        instance["current_node_id"] = node.get("next")
        instance["next_execute_at"] = now.isoformat()

    instance["retry_count"] = 0
    instance["updated_at"] = now.isoformat()
    _journey_instances[instance["instance_id"]] = instance


def _mark_instance(instance_id: str, status: str) -> None:
    """更新实例 status 字段。"""
    inst = _journey_instances.get(instance_id)
    if inst:
        inst["status"] = status
        inst["updated_at"] = datetime.now(timezone.utc).isoformat()
        _journey_instances[instance_id] = inst


def _handle_retry(instance_id: str) -> None:
    """重试计数 +1，更新 next_execute_at 为30秒后重试。"""
    inst = _journey_instances.get(instance_id)
    if inst:
        inst["retry_count"] = inst.get("retry_count", 0) + 1
        inst["next_execute_at"] = (
            datetime.now(timezone.utc) + timedelta(seconds=30)
        ).isoformat()
        inst["updated_at"] = datetime.now(timezone.utc).isoformat()
        _journey_instances[instance_id] = inst


def _remove_active_index(journey_id: str, customer_id: str) -> None:
    """从活跃实例索引中移除（实例完成/失败后调用）。"""
    key = f"{journey_id}:{customer_id}"
    _active_instance_index.pop(key, None)


def _append_execution_log(
    journey_id: str,
    instance_id: str,
    customer_id: str,
    node: dict,
    result: dict,
) -> None:
    """
    追加执行日志到 _journey_executions（与 journey_orchestrator 共享格式）。
    同时更新旅程统计 executed_count。
    """
    log_entry: dict = {
        "journey_id": journey_id,
        "instance_id": instance_id,
        "node_id": node.get("node_id"),
        "user_id": customer_id,
        "node_type": node.get("type"),
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "success": True,
        **result,
    }

    if journey_id not in _journey_executions:
        _journey_executions[journey_id] = []
    _journey_executions[journey_id].append(log_entry)

    journey = _journeys.get(journey_id)
    if journey:
        journey.setdefault("stats", {})
        journey["stats"]["executed_count"] = (
            journey["stats"].get("executed_count", 0) + 1
        )


def _parse_dt(iso_str: str) -> datetime:
    """
    解析 ISO 8601 字符串为 aware datetime（UTC）。
    若解析失败返回 epoch，确保不会无限等待。
    """
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, AttributeError):
        return datetime(1970, 1, 1, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# 辅助查询函数（供外部调试/测试使用）
# ---------------------------------------------------------------------------


def get_all_instances() -> list[dict]:
    """返回所有旅程实例（调试用）。"""
    return list(_journey_instances.values())


def get_instance_by_id(instance_id: str) -> dict | None:
    """按 instance_id 查询实例。"""
    return _journey_instances.get(instance_id)


def clear_all_instances() -> None:
    """清空所有实例和索引（仅测试用）。"""
    _journey_instances.clear()
    _active_instance_index.clear()
