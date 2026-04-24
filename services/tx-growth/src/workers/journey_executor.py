"""旅程执行引擎 — 驱动已发布旅程的节点逐步执行

运行方式：
    APScheduler 每60秒调用 JourneyExecutor().tick(db)

节点类型处理：
    wait         → 检查等待时间是否已到，到了则推进
    send_content → 调用 ChannelEngine 发送内容
    send_offer   → 通过 tx-member 发券
    condition    → 查询会员行为，判断是否转化，走 true/false 分支
    tag_user     → 调用 tx-member API 打标签
    notify_staff → 调用 tx-ops 发企微通知

数据模型说明：
    - 旅程定义存储在 journey_orchestrator._journeys（内存 dict，暂未迁移）
    - 旅程实例（JourneyInstance）持久化存储在 journey_instances 表（v026 迁移）
    - 执行日志追加写入 journey_orchestrator._journey_executions（内存，暂未迁移）
"""

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import redis.asyncio as aioredis  # type: ignore
import structlog
from models.journey_instance import JourneyInstance
from services.journey_orchestrator import (
    _journey_executions,
    _journeys,
)
from services.roi_attribution import ROIAttributionService
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

_roi_service = ROIAttributionService()

logger = structlog.get_logger(__name__)

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

    架构：
    - 旅程实例持久化存储在 PostgreSQL journey_instances 表（v026 迁移）。
    - 外部服务调用均使用 httpx.AsyncClient，timeout=10 秒。
    - 所有 DB 操作通过传入的 AsyncSession 执行，带 tenant_id 过滤，RLS 兜底。
    """

    TX_MEMBER_URL: str = os.getenv("TX_MEMBER_SERVICE_URL", "http://tx-member:8000")
    TX_OPS_URL: str = os.getenv("TX_OPS_SERVICE_URL", "http://tx-ops:8000")

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    async def tick(self, db: AsyncSession) -> dict[str, int]:
        """
        主入口：APScheduler 每60秒调用一次。

        Args:
            db: AsyncSession，由调用方（main.py _run_journey_tick）负责创建和关闭。

        Returns:
            本次 tick 的简要统计：
            {"triggers_created": int, "nodes_advanced": int, "nodes_failed": int}
        """
        log = logger.bind(tick_at=datetime.now(timezone.utc).isoformat())
        log.info("journey_executor_tick_start")

        triggers_created = await self._scan_triggers(db)
        advanced, failed = await self._advance_pending_nodes(db)

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

    async def _scan_triggers(self, db: AsyncSession) -> int:
        """
        扫描所有 status="published" 的旅程，按触发类型找出匹配客户，
        并为每个尚无运行中实例的客户创建 JourneyInstance（INSERT DB）。

        当前实现：
          - no_visit_30d         ✅ 实现（查 tx-member 客户列表）
          - birthday_approaching ✅ 实现（查 tx-member 客户列表）
          - 其余触发类型          TODO 预留，结构已对齐

        Returns:
            本次新建的实例数量
        """
        now = datetime.now(timezone.utc)
        created_count = 0

        published_journeys = [j for j in _journeys.values() if j.get("status") == "published"]

        for journey in published_journeys:
            journey_id: str = journey["journey_id"]
            trigger_type: str = journey.get("trigger", {}).get("type", "")
            # tenant_id 来自旅程定义，旅程创建时由调用方写入；若无则跳过（无法写 DB）
            tenant_id_str: str = journey.get("tenant_id", "")
            if not tenant_id_str:
                logger.warning(
                    "journey_missing_tenant_id",
                    journey_id=journey_id,
                )
                continue

            try:
                tenant_uuid = uuid.UUID(tenant_id_str)
            except ValueError:
                logger.warning(
                    "journey_invalid_tenant_id",
                    journey_id=journey_id,
                    tenant_id=tenant_id_str,
                )
                continue

            nodes: list[dict] = journey.get("nodes", [])
            if not nodes:
                continue

            first_node_id: str = nodes[0].get("node_id", "")

            # 按触发类型拉取候选客户 ID 列表
            candidate_ids: list[str] = await self._fetch_trigger_candidates(
                trigger_type, tenant_id_str, journey.get("trigger", {})
            )

            for customer_id_str in candidate_ids:
                try:
                    customer_uuid = uuid.UUID(customer_id_str)
                except ValueError:
                    logger.warning(
                        "invalid_customer_id_skipped",
                        customer_id=customer_id_str,
                        journey_id=journey_id,
                    )
                    continue

                # 防重复触发：查 DB 是否已存在 running 实例
                existing = await db.execute(
                    select(JourneyInstance.id).where(
                        JourneyInstance.journey_id == journey_id,
                        JourneyInstance.customer_id == customer_uuid,
                        JourneyInstance.tenant_id == tenant_uuid,
                        JourneyInstance.status == "running",
                    )
                )
                if existing.scalar_one_or_none() is not None:
                    # 已有运行中实例，跳过
                    continue

                instance = JourneyInstance(
                    journey_id=journey_id,
                    customer_id=customer_uuid,
                    tenant_id=tenant_uuid,
                    status="running",
                    current_node_id=first_node_id,
                    next_execute_at=now,
                    retry_count=0,
                    last_error=None,
                    completed_nodes=[],
                    started_at=now,
                    completed_at=None,
                )
                db.add(instance)
                # flush 以便后续同一 tick 内查询能看到本条记录（防止同次 tick 重复触发）
                await db.flush()
                created_count += 1

                logger.info(
                    "journey_instance_created",
                    journey_id=journey_id,
                    customer_id=customer_id_str,
                    instance_id=str(instance.id),
                    trigger_type=trigger_type,
                )

        return created_count

    async def _trigger_for_customer(
        self,
        trigger_type: str,
        customer_id: uuid.UUID,
        tenant_id: uuid.UUID,
        db: AsyncSession,
    ) -> int:
        """为指定客户立即触发匹配 trigger_type 的所有旅程（事件驱动专用）。

        与 _scan_triggers 逻辑一致，但只针对单个客户执行，
        由 JourneyEventListener 在收到 Redis Stream 事件后调用。

        Args:
            trigger_type: 触发类型字符串（如 "first_visit_no_repeat_48h"）
            customer_id:  客户 UUID
            tenant_id:    租户 UUID
            db:           数据库异步会话

        Returns:
            本次为该客户新建的旅程实例数量
        """
        now = datetime.now(timezone.utc)
        created_count = 0

        # 找到该租户下所有 published 状态、匹配 trigger_type 的旅程
        matching_journeys = [
            j
            for j in _journeys.values()
            if j.get("status") == "published"
            and j.get("trigger", {}).get("type") == trigger_type
            and j.get("tenant_id") == str(tenant_id)
        ]

        for journey in matching_journeys:
            journey_id: str = journey["journey_id"]
            nodes: list[dict] = journey.get("nodes", [])
            if not nodes:
                continue

            first_node_id: str = nodes[0].get("node_id", "")

            # 防重复触发
            existing = await db.execute(
                select(JourneyInstance.id).where(
                    JourneyInstance.journey_id == journey_id,
                    JourneyInstance.customer_id == customer_id,
                    JourneyInstance.tenant_id == tenant_id,
                    JourneyInstance.status == "running",
                )
            )
            if existing.scalar_one_or_none() is not None:
                continue

            instance = JourneyInstance(
                journey_id=journey_id,
                customer_id=customer_id,
                tenant_id=tenant_id,
                status="running",
                current_node_id=first_node_id,
                next_execute_at=now,
                retry_count=0,
                last_error=None,
                completed_nodes=[],
                started_at=now,
                completed_at=None,
            )
            db.add(instance)
            await db.flush()
            created_count += 1

            logger.info(
                "journey_instance_created_by_event",
                journey_id=journey_id,
                customer_id=str(customer_id),
                trigger_type=trigger_type,
                instance_id=str(instance.id),
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
            customer_id 字符串列表
        """
        if trigger_type == "no_visit_30d":
            return await self._fetch_no_visit_customers(days=30, tenant_id=tenant_id)

        elif trigger_type == "no_visit_15d":
            return await self._fetch_no_visit_customers(days=15, tenant_id=tenant_id)

        elif trigger_type == "no_visit_7d":
            return await self._fetch_no_visit_customers(days=7, tenant_id=tenant_id)

        elif trigger_type == "birthday_approaching":
            return await self._fetch_birthday_approaching_customers(within_days=7, tenant_id=tenant_id)

        elif trigger_type == "first_visit_no_repeat_48h":
            return await self._fetch_first_visit_no_repeat_customers(hours=48, tenant_id=tenant_id)

        elif trigger_type == "dish_repurchase_cycle":
            # 招牌菜复购周期到期：复用未到店逻辑，默认周期14天
            days = trigger_params.get("params", {}).get("cycle_days", 14)
            return await self._fetch_no_visit_customers(days=days, tenant_id=tenant_id)

        elif trigger_type == "reservation_abandoned":
            return await self._fetch_reservation_abandoned_customers(tenant_id=tenant_id)

        elif trigger_type == "banquet_lead_no_close":
            days = trigger_params.get("params", {}).get("days", 3)
            return await self._fetch_banquet_lead_no_close_customers(days=days, tenant_id=tenant_id)

        elif trigger_type == "review_improved":
            # 门店评分改善属于全员广播类，返回近30天活跃客户
            return await self._fetch_no_visit_customers(days=30, tenant_id=tenant_id)

        elif trigger_type == "new_dish_launch":
            # 新品上线广播：近60天活跃客户
            return await self._fetch_no_visit_customers(days=60, tenant_id=tenant_id)

        elif trigger_type == "weather_change":
            # 天气触发：近30天活跃客户（天气 API 集成留待后续）
            return await self._fetch_no_visit_customers(days=30, tenant_id=tenant_id)

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

    async def _fetch_first_visit_no_repeat_customers(
        self,
        hours: int,
        tenant_id: str,
    ) -> list[str]:
        """首次到店后 {hours} 小时内无复购的客户。

        API: GET /api/v1/member/customers?first_visit_no_repeat_hours={hours}
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self.TX_MEMBER_URL}/api/v1/member/customers",
                    headers={"X-Tenant-ID": tenant_id},
                    params={"first_visit_no_repeat_hours": hours, "page": 1, "size": 500},
                )
            resp.raise_for_status()
            payload = resp.json()
            items: list[dict] = payload.get("data", {}).get("items", [])
            return [item["customer_id"] for item in items if item.get("customer_id")]
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            logger.warning(
                "fetch_first_visit_no_repeat_error",
                error=str(exc),
                hours=hours,
            )
            return []

    async def _fetch_reservation_abandoned_customers(
        self,
        tenant_id: str,
    ) -> list[str]:
        """查询咨询后未预订的客户（预订状态为 abandoned/no_show）。

        API: GET /api/v1/member/customers?reservation_status=abandoned
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self.TX_MEMBER_URL}/api/v1/member/customers",
                    headers={"X-Tenant-ID": tenant_id},
                    params={"reservation_status": "abandoned", "page": 1, "size": 500},
                )
            resp.raise_for_status()
            payload = resp.json()
            items: list[dict] = payload.get("data", {}).get("items", [])
            return [item["customer_id"] for item in items if item.get("customer_id")]
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            logger.warning(
                "fetch_reservation_abandoned_error",
                error=str(exc),
            )
            return []

    async def _fetch_banquet_lead_no_close_customers(
        self,
        days: int,
        tenant_id: str,
    ) -> list[str]:
        """查询宴会线索超过 {days} 天未成交的客户。

        API: GET /api/v1/member/customers?banquet_lead_no_close_days={days}
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self.TX_MEMBER_URL}/api/v1/member/customers",
                    headers={"X-Tenant-ID": tenant_id},
                    params={"banquet_lead_no_close_days": days, "page": 1, "size": 500},
                )
            resp.raise_for_status()
            payload = resp.json()
            items: list[dict] = payload.get("data", {}).get("items", [])
            return [item["customer_id"] for item in items if item.get("customer_id")]
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            logger.warning(
                "fetch_banquet_lead_no_close_error",
                error=str(exc),
                days=days,
            )
            return []

    # ------------------------------------------------------------------
    # 节点推进：逐步执行待执行节点
    # ------------------------------------------------------------------

    async def _advance_pending_nodes(self, db: AsyncSession) -> tuple[int, int]:
        """
        查询所有 status='running' 且 next_execute_at <= now 的实例（DB 查询），
        逐个执行当前节点。

        Args:
            db: AsyncSession

        Returns:
            (advanced_count, failed_count)
        """
        now = datetime.now(timezone.utc)
        advanced = 0
        failed = 0

        # 查询 DB：取所有到期的 running 实例（跨租户，每个旅程 tenant_id 不同）
        result = await db.execute(
            select(JourneyInstance).where(
                JourneyInstance.status == "running",
                JourneyInstance.next_execute_at <= now,
            )
        )
        pending_instances: list[JourneyInstance] = list(result.scalars().all())

        for instance in pending_instances:
            instance_id: uuid.UUID = instance.id
            journey_id: str = instance.journey_id
            tenant_id_str: str = str(instance.tenant_id)

            journey = _journeys.get(journey_id)
            if not journey:
                logger.warning(
                    "journey_not_found_for_instance",
                    instance_id=str(instance_id),
                    journey_id=journey_id,
                )
                await self._db_mark_instance(
                    db,
                    instance,
                    "failed",
                    error="journey_not_found",
                    now=now,
                )
                failed += 1
                continue

            # 旅程已被暂停，实例随之暂停
            if journey.get("status") == "paused":
                await self._db_mark_instance(db, instance, "paused", now=now)
                continue

            current_node_id: str | None = instance.current_node_id
            if not current_node_id:
                # 无下一节点，旅程完成
                await self._db_mark_instance(db, instance, "completed", now=now, set_completed_at=True)
                logger.info(
                    "journey_instance_completed",
                    instance_id=str(instance_id),
                    journey_id=journey_id,
                )
                advanced += 1
                continue

            node = _find_node(journey, current_node_id)
            if not node:
                logger.warning(
                    "node_not_found",
                    instance_id=str(instance_id),
                    node_id=current_node_id,
                )
                await self._db_mark_instance(
                    db,
                    instance,
                    "failed",
                    error=f"node_not_found:{current_node_id}",
                    now=now,
                    set_completed_at=True,
                )
                failed += 1
                continue

            try:
                result_data = await self._execute_node(instance, node, tenant_id_str, db=db)
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "node_execute_http_error",
                    instance_id=str(instance_id),
                    node_id=current_node_id,
                    status_code=exc.response.status_code,
                )
                result_data = None
            except httpx.RequestError as exc:
                logger.warning(
                    "node_execute_request_error",
                    instance_id=str(instance_id),
                    node_id=current_node_id,
                    error=str(exc),
                )
                result_data = None

            if result_data is None:
                # 执行失败，重试计数 +1
                new_retry = instance.retry_count + 1
                retry_at = now + timedelta(seconds=30)
                if new_retry >= _MAX_RETRY:
                    await db.execute(
                        update(JourneyInstance)
                        .where(JourneyInstance.id == instance_id)
                        .values(
                            status="failed",
                            retry_count=new_retry,
                            last_error=f"max_retry_exceeded at node {current_node_id}",
                            completed_at=now,
                        )
                    )
                    logger.error(
                        "journey_instance_max_retry_exceeded",
                        instance_id=str(instance_id),
                        node_id=current_node_id,
                    )
                    failed += 1
                else:
                    await db.execute(
                        update(JourneyInstance)
                        .where(JourneyInstance.id == instance_id)
                        .values(
                            retry_count=new_retry,
                            next_execute_at=retry_at,
                        )
                    )
                continue

            # 执行成功，写执行日志，推进实例状态
            _append_execution_log(journey_id, str(instance_id), str(instance.customer_id), node, result_data)
            await self._db_advance_instance(db, instance, node, result_data, now)
            advanced += 1

        return advanced, failed

    # ------------------------------------------------------------------
    # DB 状态更新辅助方法
    # ------------------------------------------------------------------

    async def _db_mark_instance(
        self,
        db: AsyncSession,
        instance: JourneyInstance,
        status: str,
        *,
        error: str | None = None,
        now: datetime,
        set_completed_at: bool = False,
    ) -> None:
        """更新实例 status（及可选的 completed_at / last_error）。"""
        values: dict[str, Any] = {"status": status}
        if error is not None:
            values["last_error"] = error
        if set_completed_at:
            values["completed_at"] = now
        await db.execute(update(JourneyInstance).where(JourneyInstance.id == instance.id).values(**values))

    async def _db_advance_instance(
        self,
        db: AsyncSession,
        instance: JourneyInstance,
        node: dict,
        result: dict,
        now: datetime,
    ) -> None:
        """
        执行成功后推进实例状态（DB UPDATE）：
        - 更新 current_node_id 为下一节点
        - 若 wait 节点，更新 next_execute_at
        - 将已完成节点 ID 追加到 completed_nodes
        - 重置 retry_count
        """
        action: str = result.get("action", "")
        completed = list(instance.completed_nodes or [])
        node_id = node.get("node_id")
        if node_id:
            completed.append(node_id)

        if action == "wait":
            resume_at_str: str = result.get("resume_at", now.isoformat())
            try:
                resume_at = datetime.fromisoformat(resume_at_str.replace("Z", "+00:00"))
            except ValueError:
                resume_at = now
            next_node = node.get("next")
            await db.execute(
                update(JourneyInstance)
                .where(JourneyInstance.id == instance.id)
                .values(
                    current_node_id=next_node,
                    next_execute_at=resume_at,
                    retry_count=0,
                    completed_nodes=completed,
                )
            )
        elif action == "branch":
            next_node_id: str | None = result.get("next_node_id")
            await db.execute(
                update(JourneyInstance)
                .where(JourneyInstance.id == instance.id)
                .values(
                    current_node_id=next_node_id,
                    next_execute_at=now,
                    retry_count=0,
                    completed_nodes=completed,
                )
            )
        else:
            next_node = node.get("next")
            await db.execute(
                update(JourneyInstance)
                .where(JourneyInstance.id == instance.id)
                .values(
                    current_node_id=next_node,
                    next_execute_at=now,
                    retry_count=0,
                    completed_nodes=completed,
                )
            )

    # ------------------------------------------------------------------
    # 节点执行分发
    # ------------------------------------------------------------------

    async def _execute_node(
        self,
        instance: JourneyInstance,
        node: dict,
        tenant_id: str,
        db: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """
        按节点类型分发执行，返回执行结果 dict。
        返回 None 表示失败（由调用方处理重试）。

        db 参数可选：当传入时，send_content / send_offer 节点成功后
        会调用 ROI 归因服务记录营销触达（marketing_touches）。
        """
        node_type: str = node.get("type", "")

        if node_type == "wait":
            wait_hours: int = int(node.get("wait_hours", 24))
            resume_at = (datetime.now(timezone.utc) + timedelta(hours=wait_hours)).isoformat()
            return {"action": "wait", "resume_at": resume_at}

        elif node_type == "send_content":
            result = await self._send_content(instance, node, tenant_id)
            if db is not None and result.get("action") == "content_sent":
                await self._record_roi_touch(
                    instance=instance,
                    node=node,
                    tenant_id=tenant_id,
                    channel=result.get("channel", node.get("content_type", "wecom")),
                    offer_id=None,
                    db=db,
                )
            return result

        elif node_type == "send_offer":
            result = await self._send_offer(instance, node, tenant_id)
            if db is not None and result.get("action") == "offer_sent":
                offer_params: dict = node.get("offer_params", {})
                offer_id: str | None = offer_params.get("coupon_id") or node.get("offer_id")
                await self._record_roi_touch(
                    instance=instance,
                    node=node,
                    tenant_id=tenant_id,
                    channel="miniapp",
                    offer_id=offer_id,
                    db=db,
                )
            return result

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

    async def _record_roi_touch(
        self,
        instance: JourneyInstance,
        node: dict,
        tenant_id: str,
        channel: str,
        offer_id: str | None,
        db: AsyncSession,
    ) -> None:
        """
        旅程节点执行成功后，记录营销触达到 marketing_touches 表。

        发生在 send_content / send_offer 节点成功之后，不影响主执行链路：
        即使 ROI 记录失败，也只记录 warning 日志，不回滚节点执行结果。

        Args:
            instance:  当前旅程实例
            node:      已执行的节点配置
            tenant_id: 租户 ID 字符串
            channel:   触达渠道（从节点配置或执行结果中获取）
            offer_id:  优惠ID（send_offer 节点时传入）
            db:        AsyncSession
        """
        try:
            tenant_uuid = uuid.UUID(tenant_id)
            journey = _journeys.get(instance.journey_id, {})
            journey_name: str = journey.get("name", "")

            content_params: dict = node.get("content_params", {})
            message_title: str | None = content_params.get("title") or None

            await _roi_service.record_touch(
                touch_data={
                    "customer_id": instance.customer_id,
                    "touch_type": "journey",
                    "source_id": instance.journey_id,
                    "source_name": journey_name,
                    "channel": channel,
                    "message_title": message_title,
                    "offer_id": offer_id,
                    "touched_at": datetime.now(timezone.utc),
                },
                tenant_id=tenant_uuid,
                db=db,
            )
        except (ValueError, KeyError, OSError) as exc:
            # ROI 记录失败不影响主链路，仅 warning
            logger.warning(
                "roi_touch_record_failed",
                instance_id=str(instance.id),
                journey_id=instance.journey_id,
                node_id=node.get("node_id"),
                error=str(exc),
            )

    async def _send_content(
        self,
        instance: JourneyInstance,
        node: dict,
        tenant_id: str,
    ) -> dict[str, Any]:
        """
        个性化内容生成 + 企微渠道推送。

        节点字段：
            content_type:   "wecom_chat" | "sms" | "miniapp"
            template_key:   个性化模板 key，如 "churn_recovery" / "birthday" / "generic"
            content_params: 额外变量 {"offer_desc": str, "url": str, ...}
                            template_key 缺失时，content_params 中的 title/description
                            作为通用内容透传（generic 模板）

        流程：
            1. PersonalizedContentEngine 从 tx-member 拉取会员画像并生成个性化文案
            2. 查询会员的企微 external_userid
            3. ChannelEngine.send_wecom_message 通过 gateway 内部 API 发送
        """
        from services.channel_engine import ChannelEngine
        from services.content_engine import PersonalizedContentEngine

        content_type: str = node.get("content_type", "wecom_chat")
        template_key: str = node.get("template_key", "generic")
        extra_vars: dict = node.get("content_params", {})
        tenant_uuid = uuid.UUID(tenant_id)

        # 1. 生成个性化内容
        content_engine = PersonalizedContentEngine()
        personalized_content: dict = await content_engine.generate_content(
            template_key=template_key,
            customer_id=instance.customer_id,
            tenant_id=tenant_uuid,
            extra_vars=extra_vars,
        )
        # 将 content_params 中的 url 传入内容（如有）
        if "url" in extra_vars:
            personalized_content["url"] = extra_vars["url"]

        channel = "wecom" if "wecom" in content_type else content_type

        if channel == "wecom":
            # 2. 查询企微 external_userid
            wecom_user_id: str | None = await self._get_wecom_user_id(instance.customer_id, tenant_id)
            if not wecom_user_id:
                logger.warning(
                    "send_content_no_wecom_binding",
                    customer_id=str(instance.customer_id),
                    instance_id=str(instance.id),
                )
                return {"action": "skipped", "reason": "no_wecom_binding"}

            # 3. 通过渠道引擎发送
            channel_engine = ChannelEngine()
            result = await channel_engine.send_wecom_message(
                user_id=wecom_user_id,
                content=personalized_content,
                tenant_id=tenant_uuid,
                offer_id=extra_vars.get("offer_id"),
            )
            return {"action": "content_sent", **result}

        # sms / miniapp — 预留，透传到 tx-ops（原有逻辑）
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{self.TX_OPS_URL}/api/v1/ops/notifications",
                headers={"X-Tenant-ID": tenant_id},
                json={
                    "recipient_id": str(instance.customer_id),
                    "channel": channel,
                    "title": personalized_content.get("title", ""),
                    "content": personalized_content.get("description", ""),
                },
            )
        resp.raise_for_status()
        data: dict = resp.json().get("data", {})
        return {"action": "content_sent", "channel": channel, **data}

    async def _get_wecom_user_id(
        self,
        customer_id: uuid.UUID,
        tenant_id: str,
    ) -> str | None:
        """从 tx-member 查询会员绑定的企微 external_userid

        Returns:
            wecom_external_userid 字符串，未绑定或查询失败时返回 None
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self.TX_MEMBER_URL}/api/v1/member/customers/{customer_id}",
                    headers={"X-Tenant-ID": tenant_id},
                )
            resp.raise_for_status()
            customer: dict = resp.json().get("data", {})
            wecom_id: str | None = customer.get("wecom_external_userid") or None
            return wecom_id
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "get_wecom_user_id_http_error",
                customer_id=str(customer_id),
                status_code=exc.response.status_code,
            )
            return None
        except httpx.RequestError as exc:
            logger.warning(
                "get_wecom_user_id_request_error",
                customer_id=str(customer_id),
                error=str(exc),
            )
            return None

    async def _send_offer(
        self,
        instance: JourneyInstance,
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
                    "customer_id": str(instance.customer_id),
                    "coupon_type": node.get("offer_type", "coupon"),
                    **offer_params,
                },
            )
        resp.raise_for_status()
        data: dict = resp.json().get("data", {})
        return {"action": "offer_sent", "offer_type": node.get("offer_type", "coupon"), **data}

    async def _check_condition(
        self,
        instance: JourneyInstance,
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
            next_node_id = node.get("true_next") if is_converted else node.get("false_next")
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
            instance_id=str(instance.id),
        )
        return {
            "action": "branch",
            "condition_type": condition_type,
            "result": False,
            "next_node_id": node.get("false_next"),
        }

    async def _query_is_converted(
        self,
        instance: JourneyInstance,
        tenant_id: str,
    ) -> bool:
        """
        查询会员在旅程实例创建后是否产生了新订单（视为转化）。
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self.TX_MEMBER_URL}/api/v1/member/customers/{instance.customer_id}",
                    headers={"X-Tenant-ID": tenant_id},
                )
            resp.raise_for_status()
            customer: dict = resp.json().get("data", {})
            last_order_at: str | None = customer.get("last_order_at")
            if not last_order_at:
                return False
            last_order_dt = datetime.fromisoformat(last_order_at.replace("Z", "+00:00"))
            started_at: datetime = instance.started_at
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=timezone.utc)
            return last_order_dt > started_at
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "query_is_converted_http_error",
                status_code=exc.response.status_code,
                customer_id=str(instance.customer_id),
            )
            return False
        except httpx.RequestError as exc:
            logger.warning(
                "query_is_converted_request_error",
                error=str(exc),
                customer_id=str(instance.customer_id),
            )
            return False

    async def _tag_user(
        self,
        instance: JourneyInstance,
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
                f"{self.TX_MEMBER_URL}/api/v1/member/customers/{instance.customer_id}/tags",
                headers={"X-Tenant-ID": tenant_id},
                json={"tags": tags},
            )
        resp.raise_for_status()
        data: dict = resp.json().get("data", {})
        return {"action": "user_tagged", "tags": tags, **data}

    async def _notify_staff(
        self,
        instance: JourneyInstance,
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
        customer_id_str: str = str(instance.customer_id)
        content_template: str = node.get(
            "content",
            f"请跟进客户 {customer_id_str}",
        )
        content = content_template.replace("{customer_id}", customer_id_str)

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
        return {
            "action": "staff_notified",
            "staff_id": node.get("staff_id", "store_manager"),
            **data,
        }


# ---------------------------------------------------------------------------
# 辅助函数（模块级）
# ---------------------------------------------------------------------------


def _find_node(journey: dict, node_id: str) -> dict | None:
    """在旅程的 nodes 列表中按 node_id 查找节点。"""
    for node in journey.get("nodes", []):
        if node.get("node_id") == node_id:
            return node
    return None


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
        journey["stats"]["executed_count"] = journey["stats"].get("executed_count", 0) + 1


# ── JourneyEventListener ─────────────────────────────────────────────────────


class JourneyEventListener:
    """Redis Stream 消费器 — 实时触发旅程（与 APScheduler 轮询并行，双保险）。

    事件到触发类型映射（EVENT_TO_TRIGGER）：
        - MEMBER_REGISTERED → first_visit_no_repeat_48h（新客首单48h未复购）
        - ORDER_PAID        → dish_repurchase_cycle（招牌菜复购周期）
        - 其他事件          → None（不触发旅程）

    与 APScheduler 60s 轮询的关系：
        - 轮询负责覆盖所有客户的批量扫描（保底）
        - 事件监听负责单个客户的实时触发（<1s 延迟）
        - 两者通过 _trigger_for_customer 的防重复校验确保不会重复创建实例

    启动方式（tx-growth/main.py lifespan 中）：
        listener = JourneyEventListener()
        task = asyncio.create_task(listener.listen(db))
    """

    from shared.events.member_events import MemberEventType as _MET

    # 事件类型 → 旅程触发类型映射
    EVENT_TO_TRIGGER: dict[str, str | None] = {
        "member.registered": "first_visit_no_repeat_48h",
        "member.order.paid": "dish_repurchase_cycle",
        "member.sv.recharged": None,  # 储值充值不触发旅程
        "member.order.placed": None,
        "member.order.cancelled": None,
    }

    def __init__(self) -> None:
        from shared.events.event_consumer import MemberEventConsumer

        self._consumer = MemberEventConsumer(
            group_name="journey_executor",
            consumer_name="journey_trigger",
        )
        self._executor = JourneyExecutor()

    async def listen(self, db: AsyncSession) -> None:
        """持续监听 Redis Stream，实时触发旅程。

        Args:
            db: 长存活的 AsyncSession（从调用方传入）
                注意：调用方负责 session 生命周期管理。
        """
        import asyncio

        from shared.events.event_consumer import DLQ_STREAM_KEY, STREAM_KEY
        from shared.events.event_publisher import MemberEventPublisher

        redis = await MemberEventPublisher.get_redis()
        await self._consumer.ensure_group(redis)

        logger.info(
            "journey_event_listener_started",
            group=self._consumer.group_name,
        )

        while True:
            try:
                messages = await redis.xreadgroup(
                    groupname=self._consumer.group_name,
                    consumername=self._consumer.consumer_name,
                    streams={STREAM_KEY: ">"},
                    count=10,
                    block=1000,
                )
            except OSError as exc:
                logger.warning(
                    "journey_event_listener_redis_error",
                    error=str(exc),
                )
                MemberEventPublisher._redis = None
                await asyncio.sleep(5)
                redis = await MemberEventPublisher.get_redis()
                await self._consumer.ensure_group(redis)
                continue

            if not messages:
                continue

            for _stream, entries in messages:
                for entry_id, fields in entries:
                    await self._handle_event(redis, entry_id, fields, db, STREAM_KEY, DLQ_STREAM_KEY)

    async def _handle_event(
        self,
        redis: "aioredis.Redis",  # type: ignore[name-defined]
        entry_id: str,
        fields: dict[str, str],
        db: AsyncSession,
        stream_key: str,
        dlq_key: str,
    ) -> None:
        """处理单条 Stream 事件，映射到对应旅程触发类型后调用执行器。"""
        event_type_str: str = fields.get("event_type", "")
        trigger_type: str | None = self.EVENT_TO_TRIGGER.get(event_type_str)

        if trigger_type is None:
            # 该事件类型无需触发旅程，直接 ACK
            await redis.xack(stream_key, self._consumer.group_name, entry_id)
            return

        try:
            customer_id = uuid.UUID(fields["customer_id"])
            tenant_id = uuid.UUID(fields["tenant_id"])
        except (KeyError, ValueError) as exc:
            logger.error(
                "journey_listener_invalid_fields",
                entry_id=entry_id,
                error=str(exc),
            )
            await redis.xack(stream_key, self._consumer.group_name, entry_id)
            return

        try:
            count = await self._executor._trigger_for_customer(
                trigger_type=trigger_type,
                customer_id=customer_id,
                tenant_id=tenant_id,
                db=db,
            )
            await db.commit()
            await redis.xack(stream_key, self._consumer.group_name, entry_id)

            if count:
                logger.info(
                    "journey_event_triggered",
                    trigger_type=trigger_type,
                    customer_id=str(customer_id),
                    instances_created=count,
                )
        except (OSError, RuntimeError, ValueError) as exc:
            await db.rollback()
            logger.error(
                "journey_event_trigger_failed",
                entry_id=entry_id,
                trigger_type=trigger_type,
                customer_id=str(customer_id),
                error=str(exc),
                exc_info=True,
            )
            from datetime import datetime
            from datetime import timezone as tz

            await redis.xadd(
                dlq_key,
                {
                    **fields,
                    "original_entry_id": entry_id,
                    "failure_reason": "journey_trigger_failed",
                    "error_message": str(exc),
                    "failed_at": datetime.now(tz.utc).isoformat(),
                    "consumer_group": self._consumer.group_name,
                },
                maxlen=50_000,
                approximate=True,
            )
            await redis.xack(stream_key, self._consumer.group_name, entry_id)
