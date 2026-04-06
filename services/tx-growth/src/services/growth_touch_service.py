"""增长触达服务 — 执行触达、频控、归因

管理 growth_touch_executions 表。
依赖 channel_engine (发送) 和 roi_attribution (归因)。

金额单位：分(fen)
"""
import asyncio
import re
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events.src.emitter import emit_event

GROWTH_EVT_PREFIX = "growth"
ATTRIBUTION_WINDOW_HOURS = 168  # 7天归因窗口

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# GrowthTouchService
# ---------------------------------------------------------------------------


class GrowthTouchService:
    """增长触达服务 — 执行触达 + 频控 + 归因"""

    VALID_EXECUTION_STATES = (
        "pending", "sent", "delivered", "failed", "blocked", "opted_out",
    )
    VALID_CHANNELS = (
        "wecom", "sms", "miniapp", "app_push", "pos_receipt",
        "reservation_page", "store_task",
    )

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    async def _set_tenant(self, db: AsyncSession, tenant_id: str) -> None:
        await db.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )

    # ------------------------------------------------------------------
    # 模板渲染
    # ------------------------------------------------------------------

    async def render_template(
        self,
        template_code: str,
        variables: dict,
        tenant_id: str,
        db: AsyncSession,
    ) -> str:
        """查touch_template + 替换变量"""
        await self._set_tenant(db, tenant_id)

        result = await db.execute(
            text("""
                SELECT content_template
                FROM growth_touch_templates
                WHERE tenant_id = :tid AND template_code = :code AND is_deleted = false
                LIMIT 1
            """),
            {"tid": tenant_id, "code": template_code},
        )
        row = result.fetchone()
        if row is None:
            raise ValueError(f"Touch template not found: {template_code}")

        content = row._mapping["content_template"]
        # 替换 {变量名} 占位符
        for key, value in variables.items():
            content = content.replace(f"{{{key}}}", str(value))

        # 检查未替换的占位符
        unreplaced = re.findall(r"\{(\w+)\}", content)
        if unreplaced:
            logger.warning(
                "touch_template_unreplaced_vars",
                template_code=template_code,
                unreplaced=unreplaced,
            )
        return content

    # ------------------------------------------------------------------
    # 执行触达
    # ------------------------------------------------------------------

    async def execute_touch(
        self,
        customer_id: UUID,
        enrollment_id: Optional[UUID],
        template_id: UUID,
        step_no: Optional[int],
        channel: str,
        mechanism_type: Optional[str],
        variables: dict,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict:
        """执行触达: 渲染 -> 频控检查 -> 投诉检查 -> 发送 -> 记录"""
        await self._set_tenant(db, tenant_id)

        if channel not in self.VALID_CHANNELS:
            raise ValueError(f"Invalid channel: {channel}")

        execution_id = str(uuid4())
        execution_state = "pending"
        block_reason: Optional[str] = None

        # 1. 查touch_template渲染内容
        # 从template steps中查出touch_template_code
        touch_template_code: Optional[str] = None
        if step_no is not None:
            step_result = await db.execute(
                text("""
                    SELECT touch_template_code
                    FROM growth_journey_template_steps
                    WHERE tenant_id = :tid AND template_id = :tmpl_id
                      AND step_no = :step_no AND is_deleted = false
                """),
                {"tid": tenant_id, "tmpl_id": str(template_id), "step_no": step_no},
            )
            step_row = step_result.fetchone()
            if step_row is not None:
                touch_template_code = step_row._mapping["touch_template_code"]

        rendered_content: Optional[str] = None
        if touch_template_code:
            try:
                rendered_content = await self.render_template(
                    touch_template_code, variables, tenant_id, db
                )
            except ValueError:
                logger.warning(
                    "touch_template_not_found",
                    template_code=touch_template_code,
                    customer_id=str(customer_id),
                )
                rendered_content = None

        # 2. 频控检查: marketing_pause_until 和 growth_opt_out
        profile_result = await db.execute(
            text("""
                SELECT marketing_pause_until, growth_opt_out, service_repair_status
                FROM customer_growth_profiles
                WHERE tenant_id = :tid AND customer_id = :cid AND is_deleted = false
            """),
            {"tid": tenant_id, "cid": str(customer_id)},
        )
        profile_row = profile_result.fetchone()

        if profile_row is not None:
            profile = profile_row._mapping
            # opt-out检查
            if profile["growth_opt_out"]:
                execution_state = "opted_out"
                block_reason = "customer_opted_out"

            # 营销暂停检查
            if execution_state == "pending" and profile["marketing_pause_until"] is not None:
                pause_until = profile["marketing_pause_until"]
                if isinstance(pause_until, datetime) and pause_until > datetime.now(timezone.utc):
                    execution_state = "blocked"
                    block_reason = "marketing_paused"

            # 3. 投诉检查
            if execution_state == "pending" and profile["service_repair_status"] == "complaint_open":
                execution_state = "blocked"
                block_reason = "complaint_open"

        # 4. 实际发送（如果未被阻止）
        send_result_data: Optional[dict] = None
        if execution_state == "pending":
            try:
                # 通过channel_engine发送
                from services.channel_engine import ChannelEngine

                engine = ChannelEngine()
                send_result_data = await engine.send_message(
                    channel=channel,
                    customer_id=str(customer_id),
                    content=rendered_content or "",
                    tenant_id=tenant_id,
                    db=db,
                )
                if send_result_data and send_result_data.get("ok"):
                    execution_state = "delivered"
                else:
                    execution_state = "failed"
                    block_reason = send_result_data.get("error", "send_failed") if send_result_data else "send_failed"
            except (RuntimeError, ConnectionError, OSError) as exc:
                execution_state = "failed"
                block_reason = str(exc)
                logger.warning(
                    "touch_send_failed",
                    customer_id=str(customer_id),
                    channel=channel,
                    error=str(exc),
                )

        # 5. INSERT growth_touch_executions
        result = await db.execute(
            text("""
                INSERT INTO growth_touch_executions
                    (id, tenant_id, customer_id, enrollment_id, template_id,
                     step_no, channel, mechanism_type, rendered_content,
                     execution_state, block_reason)
                VALUES
                    (:id, :tenant_id, :customer_id, :enrollment_id, :template_id,
                     :step_no, :channel, :mechanism_type, :rendered_content,
                     :execution_state, :block_reason)
                RETURNING id, tenant_id, customer_id, enrollment_id, template_id,
                          step_no, channel, execution_state, block_reason,
                          created_at
            """),
            {
                "id": execution_id,
                "tenant_id": tenant_id,
                "customer_id": str(customer_id),
                "enrollment_id": str(enrollment_id) if enrollment_id else None,
                "template_id": str(template_id),
                "step_no": step_no,
                "channel": channel,
                "mechanism_type": mechanism_type,
                "rendered_content": rendered_content,
                "execution_state": execution_state,
                "block_reason": block_reason,
            },
        )
        execution = dict(result.fetchone()._mapping)

        # 6. emit_event
        asyncio.create_task(
            emit_event(
                event_type=f"{GROWTH_EVT_PREFIX}.touch.executed",
                tenant_id=tenant_id,
                stream_id=execution_id,
                payload={
                    "execution_id": execution_id,
                    "customer_id": str(customer_id),
                    "channel": channel,
                    "execution_state": execution_state,
                    "block_reason": block_reason,
                },
                source_service="tx-growth",
            )
        )

        # 7. 写归因触点（仅delivered状态）
        if execution_state == "delivered":
            try:
                from services.roi_attribution import ROIAttributionService

                attr_svc = ROIAttributionService()
                await attr_svc.record_touch(
                    touch_data={
                        "customer_id": str(customer_id),
                        "touch_type": "journey",
                        "source_id": str(template_id),
                        "source_name": f"growth_journey_{template_id}",
                        "channel": channel,
                        "message_title": touch_template_code,
                    },
                    tenant_id=UUID(tenant_id),
                    db=db,
                )
            except (ValueError, RuntimeError, OSError) as exc:
                logger.warning(
                    "touch_attribution_record_failed",
                    execution_id=execution_id,
                    error=str(exc),
                )

        logger.info(
            "touch_executed",
            execution_id=execution_id,
            customer_id=str(customer_id),
            channel=channel,
            execution_state=execution_state,
            tenant_id=tenant_id,
        )
        return execution

    # ------------------------------------------------------------------
    # 更新执行状态
    # ------------------------------------------------------------------

    async def update_execution_state(
        self, execution_id: UUID, state: str, tenant_id: str, db: AsyncSession
    ) -> dict:
        """更新触达执行状态"""
        if state not in self.VALID_EXECUTION_STATES:
            raise ValueError(f"Invalid execution_state: {state}")

        await self._set_tenant(db, tenant_id)

        result = await db.execute(
            text("""
                UPDATE growth_touch_executions
                SET execution_state = :state, updated_at = NOW()
                WHERE tenant_id = :tid AND id = :eid AND is_deleted = false
                RETURNING id, customer_id, channel, execution_state, updated_at
            """),
            {"tid": tenant_id, "eid": str(execution_id), "state": state},
        )
        row = result.fetchone()
        if row is None:
            raise ValueError(f"Touch execution {execution_id} not found")

        updated = dict(row._mapping)
        logger.info(
            "execution_state_updated",
            execution_id=str(execution_id),
            state=state,
            tenant_id=tenant_id,
        )
        return updated

    # ------------------------------------------------------------------
    # 订单归因
    # ------------------------------------------------------------------

    async def attribute_order(
        self,
        customer_id: UUID,
        order_id: UUID,
        revenue_fen: int,
        profit_fen: int,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict:
        """72h窗口内最近一次未归因触达 → 归因订单"""
        await self._set_tenant(db, tenant_id)

        # 查找ATTRIBUTION_WINDOW_HOURS内最近一次已delivered且未归因的触达
        result = await db.execute(
            text(f"""
                SELECT id, channel, template_id, enrollment_id
                FROM growth_touch_executions
                WHERE tenant_id = :tid
                  AND customer_id = :cid
                  AND execution_state = 'delivered'
                  AND attributed_order_id IS NULL
                  AND created_at > NOW() - INTERVAL '{ATTRIBUTION_WINDOW_HOURS} hours'
                  AND is_deleted = false
                ORDER BY created_at DESC
                LIMIT 1
            """),
            {"tid": tenant_id, "cid": str(customer_id)},
        )
        row = result.fetchone()
        if row is None:
            return {
                "attributed": False,
                "reason": "no_eligible_touch_in_window",
                "customer_id": str(customer_id),
                "order_id": str(order_id),
            }

        touch = row._mapping
        execution_id = touch["id"]

        await db.execute(
            text("""
                UPDATE growth_touch_executions
                SET attributed_order_id = :order_id,
                    revenue_fen = :revenue_fen,
                    profit_fen = :profit_fen,
                    updated_at = NOW()
                WHERE tenant_id = :tid AND id = :eid
            """),
            {
                "tid": tenant_id,
                "eid": str(execution_id),
                "order_id": str(order_id),
                "revenue_fen": revenue_fen,
                "profit_fen": profit_fen,
            },
        )

        asyncio.create_task(
            emit_event(
                event_type=f"{GROWTH_EVT_PREFIX}.touch.attributed",
                tenant_id=tenant_id,
                stream_id=str(execution_id),
                payload={
                    "execution_id": str(execution_id),
                    "customer_id": str(customer_id),
                    "order_id": str(order_id),
                    "revenue_fen": revenue_fen,
                    "profit_fen": profit_fen,
                    "channel": touch["channel"],
                },
                source_service="tx-growth",
            )
        )
        logger.info(
            "touch_attributed",
            execution_id=str(execution_id),
            customer_id=str(customer_id),
            order_id=str(order_id),
            revenue_fen=revenue_fen,
            tenant_id=tenant_id,
        )
        return {
            "attributed": True,
            "execution_id": str(execution_id),
            "customer_id": str(customer_id),
            "order_id": str(order_id),
            "channel": touch["channel"],
            "revenue_fen": revenue_fen,
            "profit_fen": profit_fen,
        }

    # ------------------------------------------------------------------
    # 分页查询触达历史
    # ------------------------------------------------------------------

    async def list_executions(
        self,
        tenant_id: str,
        db: AsyncSession,
        customer_id: Optional[str] = None,
        enrollment_id: Optional[str] = None,
        page: int = 1,
        size: int = 20,
    ) -> dict:
        """分页列出触达执行记录（通用，支持按customer_id或enrollment_id筛选）"""
        await self._set_tenant(db, tenant_id)

        where_clauses = ["tenant_id = :tid", "is_deleted = false"]
        params: dict = {"tid": tenant_id}

        if customer_id is not None:
            where_clauses.append("customer_id = :cid")
            params["cid"] = customer_id
        if enrollment_id is not None:
            where_clauses.append("journey_enrollment_id = :eid")
            params["eid"] = enrollment_id

        where_sql = " AND ".join(where_clauses)
        offset = (page - 1) * size

        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM growth_touch_executions WHERE {where_sql}"),
            params,
        )
        total = count_result.scalar() or 0

        params["lim"] = size
        params["off"] = offset
        rows_result = await db.execute(
            text(f"""
                SELECT id, customer_id, journey_enrollment_id, journey_template_id,
                       step_no, touch_template_id, channel, mechanism_type,
                       execution_state, blocked_reason, rendered_content,
                       attributed_order_id, attributed_revenue_fen,
                       attributed_gross_profit_fen,
                       created_at, updated_at
                FROM growth_touch_executions
                WHERE {where_sql}
                ORDER BY created_at DESC
                LIMIT :lim OFFSET :off
            """),
            params,
        )
        items = [dict(r._mapping) for r in rows_result.fetchall()]
        return {"items": items, "total": total}

    async def update_attribution_by_execution(
        self,
        execution_id: UUID,
        order_id: UUID,
        revenue_fen: int,
        profit_fen: int,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict:
        """通过execution_id回写归因（先查customer_id再调attribute_order）"""
        await self._set_tenant(db, tenant_id)

        # 查execution获取customer_id
        exec_result = await db.execute(
            text("""
                SELECT id, customer_id, channel, journey_template_id, journey_enrollment_id
                FROM growth_touch_executions
                WHERE tenant_id = :tid AND id = :eid AND is_deleted = false
            """),
            {"tid": tenant_id, "eid": str(execution_id)},
        )
        exec_row = exec_result.fetchone()
        if exec_row is None:
            raise ValueError(f"Touch execution {execution_id} not found")

        execution = exec_row._mapping
        customer_id = UUID(str(execution["customer_id"]))

        # 直接更新该execution的归因
        await db.execute(
            text("""
                UPDATE growth_touch_executions
                SET attributed_order_id = :order_id,
                    attributed_revenue_fen = :revenue_fen,
                    attributed_gross_profit_fen = :profit_fen,
                    updated_at = NOW()
                WHERE tenant_id = :tid AND id = :eid
            """),
            {
                "tid": tenant_id,
                "eid": str(execution_id),
                "order_id": str(order_id),
                "revenue_fen": revenue_fen,
                "profit_fen": profit_fen,
            },
        )

        asyncio.create_task(
            emit_event(
                event_type=f"{GROWTH_EVT_PREFIX}.touch.attributed",
                tenant_id=tenant_id,
                stream_id=str(execution_id),
                payload={
                    "execution_id": str(execution_id),
                    "customer_id": str(customer_id),
                    "order_id": str(order_id),
                    "revenue_fen": revenue_fen,
                    "profit_fen": profit_fen,
                    "channel": execution["channel"],
                },
                source_service="tx-growth",
            )
        )
        logger.info(
            "touch_attributed_by_execution",
            execution_id=str(execution_id),
            customer_id=str(customer_id),
            order_id=str(order_id),
            revenue_fen=revenue_fen,
            tenant_id=tenant_id,
        )
        return {
            "attributed": True,
            "execution_id": str(execution_id),
            "customer_id": str(customer_id),
            "order_id": str(order_id),
            "channel": execution["channel"],
            "revenue_fen": revenue_fen,
            "profit_fen": profit_fen,
        }

    async def list_by_customer(
        self,
        customer_id: UUID,
        tenant_id: str,
        page: int,
        size: int,
        db: AsyncSession,
    ) -> dict:
        """分页查询客户触达历史"""
        await self._set_tenant(db, tenant_id)

        offset = (page - 1) * size

        count_result = await db.execute(
            text("""
                SELECT COUNT(*)
                FROM growth_touch_executions
                WHERE tenant_id = :tid AND customer_id = :cid AND is_deleted = false
            """),
            {"tid": tenant_id, "cid": str(customer_id)},
        )
        total = count_result.scalar() or 0

        rows_result = await db.execute(
            text("""
                SELECT id, customer_id, enrollment_id, template_id, step_no,
                       channel, mechanism_type, execution_state, block_reason,
                       attributed_order_id, revenue_fen, profit_fen,
                       created_at, updated_at
                FROM growth_touch_executions
                WHERE tenant_id = :tid AND customer_id = :cid AND is_deleted = false
                ORDER BY created_at DESC
                LIMIT :lim OFFSET :off
            """),
            {"tid": tenant_id, "cid": str(customer_id), "lim": size, "off": offset},
        )
        items = [dict(r._mapping) for r in rows_result.fetchall()]
        return {"items": items, "total": total}
