"""HR事件消费器

监听Redis Stream中的HR相关事件，触发对应Agent动作：
- org.attendance.absent       -> attendance_recovery Agent (缺勤补位)
- org.attendance.exception    -> compliance_alert Agent (合规预警)
- org.leave.approved          -> 排班缺口检测
- org.employee.contract_expiring -> 合规预警
- org.schedule.cancelled      -> 自动创建排班缺口
- org.shift_gap.opened        -> 触发补位Agent

事件来源: shared/events/org_events.py 中定义的 OrgEventType
Redis Stream key: org_events
"""

from __future__ import annotations

import asyncio
import json
from datetime import date
from typing import Any, Optional

import structlog
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from shared.ontology.src.database import async_session_factory

log = structlog.get_logger(__name__)


class HREventConsumer:
    """HR域事件消费器

    从 Redis Stream 读取组织人事域事件，分发到对应的 Agent 处理器。
    使用 Consumer Group 保证每条消息只被一个消费者处理。
    """

    STREAM_KEY = "org_events"
    GROUP_NAME = "hr_agent_group"
    CONSUMER_NAME = "hr_consumer_1"

    # 事件类型 -> 处理方法名
    EVENT_HANDLERS: dict[str, str] = {
        "org.attendance.absent": "_handle_absence",
        "org.attendance.exception": "_handle_attendance_exception",
        "org.leave.approved": "_handle_leave_approved",
        "org.employee.contract_expiring": "_handle_contract_expiring",
        "org.schedule.cancelled": "_handle_schedule_cancelled",
        "org.shift_gap.opened": "_handle_gap_opened",
    }

    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis_url = redis_url
        self.redis: Optional[Redis] = None
        self.running = False

    async def start(self) -> None:
        """启动事件消费循环"""
        self.redis = Redis.from_url(self.redis_url, decode_responses=False)
        # 创建消费组（幂等）
        try:
            await self.redis.xgroup_create(
                self.STREAM_KEY,
                self.GROUP_NAME,
                id="0",
                mkstream=True,
            )
        except Exception:  # noqa: BLE001 — 组已存在时 Redis 抛 BUSYGROUP
            pass
        self.running = True
        log.info("hr_event_consumer_started", stream=self.STREAM_KEY, group=self.GROUP_NAME)

        while self.running:
            try:
                messages = await self.redis.xreadgroup(
                    self.GROUP_NAME,
                    self.CONSUMER_NAME,
                    {self.STREAM_KEY: ">"},
                    count=10,
                    block=5000,
                )
                for stream, events in messages:
                    for event_id, event_data in events:
                        await self._process_event(event_id, event_data)
                        await self.redis.xack(self.STREAM_KEY, self.GROUP_NAME, event_id)
            except asyncio.CancelledError:
                log.info("hr_event_consumer_cancelled")
                break
            except ConnectionError as exc:
                log.error("hr_event_consumer_redis_connection_error", error=str(exc))
                await asyncio.sleep(5)
            except Exception as exc:  # noqa: BLE001 — 消费循环最外层兜底
                log.error("hr_event_consumer_error", error=str(exc), exc_info=True)
                await asyncio.sleep(5)

    async def _process_event(self, event_id: bytes, event_data: dict[bytes, bytes]) -> None:
        """分发事件到对应处理器"""
        event_type = event_data.get(b"event_type", b"").decode()
        handler_name = self.EVENT_HANDLERS.get(event_type)
        if not handler_name:
            return

        handler = getattr(self, handler_name, None)
        if handler is None:
            log.warning("hr_event_handler_missing", event_type=event_type, handler=handler_name)
            return

        payload = self._decode_payload(event_data)
        try:
            await handler(payload)
            log.info(
                "hr_event_processed",
                event_type=event_type,
                event_id=event_id.decode() if isinstance(event_id, bytes) else str(event_id),
            )
        except Exception as exc:  # noqa: BLE001 — 单条消息处理失败不应中断消费循环
            log.error(
                "hr_event_handler_failed",
                event_type=event_type,
                error=str(exc),
                exc_info=True,
            )

    # ── 事件处理器 ───────────────────────────────────────────────────

    async def _handle_absence(self, payload: dict[str, Any]) -> None:
        """缺勤事件 -> 触发缺勤补位Agent

        Agent Level 2: 自动执行 + 30分钟回滚窗口
        1. 从payload提取employee_id, store_id, schedule_date
        2. 自动创建shift_gap（如果不存在）
        3. 调用attendance_recovery Agent查找候选人
        4. 如果urgency=critical，自动发送补位通知
        """
        employee_id = payload.get("employee_id", "")
        store_id = payload.get("store_id", "")
        tenant_id = payload.get("tenant_id", "")
        schedule_date = payload.get("schedule_date", date.today().isoformat())

        log.info(
            "absence_event_received",
            employee_id=employee_id,
            store_id=store_id,
            date=schedule_date,
        )

        # 自动创建排班缺口事件
        if self.redis:
            gap_event = {
                "event_type": "org.shift_gap.opened",
                "tenant_id": tenant_id,
                "store_id": store_id,
                "employee_id": employee_id,
                "payload": json.dumps(
                    {
                        "reason": "absence",
                        "schedule_date": schedule_date,
                        "urgency": "high",
                        "auto_created": True,
                    }
                ),
            }
            await self.redis.xadd(self.STREAM_KEY, gap_event)
            log.info("shift_gap_auto_created", store_id=store_id, date=schedule_date)

    async def _handle_attendance_exception(self, payload: dict[str, Any]) -> None:
        """考勤异常 -> 更新合规预警

        Agent Level 1: 记录异常，由店长决定处理方式
        """
        employee_id = payload.get("employee_id", "")
        exception_type = payload.get("exception_type", "unknown")
        log.info(
            "attendance_exception_received",
            employee_id=employee_id,
            exception_type=exception_type,
        )
        tenant_id = payload.get("tenant_id", "")
        try:
            async with async_session_factory() as db:
                await db.execute(
                    text("""
                        INSERT INTO compliance_alerts
                            (tenant_id, employee_id, alert_type, severity, title, detail, source)
                        VALUES
                            (:tenant_id, :employee_id, 'attendance_exception', 'warning',
                             :title, :detail, 'agent')
                    """),
                    {
                        "tenant_id": tenant_id,
                        "employee_id": employee_id or None,
                        "title": f"考勤异常: {exception_type}",
                        "detail": json.dumps(
                            {"employee_id": employee_id, "exception_type": exception_type},
                            ensure_ascii=False,
                        ),
                    },
                )
                await db.commit()
                log.info(
                    "compliance_alert_created",
                    alert_type="attendance_exception",
                    employee_id=employee_id,
                )
        except (OperationalError, SQLAlchemyError) as exc:
            log.warning(
                "compliance_alert_insert_failed",
                alert_type="attendance_exception",
                employee_id=employee_id,
                error=str(exc),
            )

    async def _handle_leave_approved(self, payload: dict[str, Any]) -> None:
        """请假审批通过 -> 检查排班缺口

        Agent Level 2: 自动检测是否有排班受影响，若有则创建缺口
        """
        employee_id = payload.get("employee_id", "")
        store_id = payload.get("store_id", "")
        tenant_id = payload.get("tenant_id", "")
        leave_start = payload.get("leave_start", "")
        leave_end = payload.get("leave_end", "")

        log.info(
            "leave_approved_received",
            employee_id=employee_id,
            leave_start=leave_start,
            leave_end=leave_end,
        )
        conflicting_schedules: list[dict[str, Any]] = []
        try:
            async with async_session_factory() as db:
                result = await db.execute(
                    text("""
                        SELECT id, store_id, date
                        FROM employee_schedules
                        WHERE employee_id = :eid
                          AND date BETWEEN :start AND :end
                          AND is_deleted = FALSE
                    """),
                    {"eid": employee_id, "start": leave_start, "end": leave_end},
                )
                rows = result.mappings().all()
                conflicting_schedules = [dict(r) for r in rows]
        except (OperationalError, SQLAlchemyError) as exc:
            log.warning(
                "leave_schedule_query_failed",
                employee_id=employee_id,
                error=str(exc),
            )

        log.info(
            "leave_schedule_conflicts_found",
            employee_id=employee_id,
            conflict_count=len(conflicting_schedules),
        )

        if conflicting_schedules and self.redis:
            for sched in conflicting_schedules:
                sched_store_id = str(sched.get("store_id", store_id))
                sched_date = str(sched.get("date", ""))
                gap_event = {
                    "event_type": "org.shift_gap.opened",
                    "tenant_id": tenant_id,
                    "store_id": sched_store_id,
                    "employee_id": employee_id,
                    "payload": json.dumps(
                        {
                            "reason": "leave_approved",
                            "schedule_date": sched_date,
                            "urgency": "medium",
                            "auto_created": True,
                            "schedule_id": str(sched.get("id", "")),
                        }
                    ),
                }
                await self.redis.xadd(self.STREAM_KEY, gap_event)
            log.info(
                "shift_gaps_created_for_leave",
                employee_id=employee_id,
                gap_count=len(conflicting_schedules),
            )

    async def _handle_contract_expiring(self, payload: dict[str, Any]) -> None:
        """合同到期预警 -> 合规Agent

        Agent Level 1: 生成预警，通知HR和店长
        """
        employee_id = payload.get("employee_id", "")
        expiry_date = payload.get("expiry_date", "")
        tenant_id = payload.get("tenant_id", "")
        log.info(
            "contract_expiring_received",
            employee_id=employee_id,
            expiry_date=expiry_date,
        )
        try:
            async with async_session_factory() as db:
                await db.execute(
                    text("""
                        INSERT INTO compliance_alerts
                            (tenant_id, employee_id, alert_type, severity, title, detail,
                             due_date, source)
                        VALUES
                            (:tenant_id, :employee_id, 'contract_expiry', 'warning',
                             '员工合同即将到期', :detail, :due_date, 'system')
                    """),
                    {
                        "tenant_id": tenant_id,
                        "employee_id": employee_id or None,
                        "detail": json.dumps(
                            {"employee_id": employee_id, "expiry_date": expiry_date},
                            ensure_ascii=False,
                        ),
                        "due_date": expiry_date or None,
                    },
                )
                await db.commit()
                log.info(
                    "compliance_alert_created",
                    alert_type="contract_expiry",
                    employee_id=employee_id,
                    expiry_date=expiry_date,
                )
        except (OperationalError, SQLAlchemyError) as exc:
            log.warning(
                "compliance_alert_insert_failed",
                alert_type="contract_expiry",
                employee_id=employee_id,
                error=str(exc),
            )
        # TODO: 接入 im_notification_service

    async def _handle_schedule_cancelled(self, payload: dict[str, Any]) -> None:
        """排班取消 -> 自动创建缺口

        Agent Level 2: 自动创建缺口并触发补位流程
        """
        store_id = payload.get("store_id", "")
        tenant_id = payload.get("tenant_id", "")
        schedule_date = payload.get("schedule_date", "")

        log.info(
            "schedule_cancelled_received",
            store_id=store_id,
            date=schedule_date,
        )

        if self.redis:
            gap_event = {
                "event_type": "org.shift_gap.opened",
                "tenant_id": tenant_id,
                "store_id": store_id,
                "employee_id": payload.get("employee_id", ""),
                "payload": json.dumps(
                    {
                        "reason": "schedule_cancelled",
                        "schedule_date": schedule_date,
                        "urgency": "medium",
                        "auto_created": True,
                    }
                ),
            }
            await self.redis.xadd(self.STREAM_KEY, gap_event)

    async def _handle_gap_opened(self, payload: dict[str, Any]) -> None:
        """缺口创建 -> 触发补位Agent

        Agent Level 2: 自动查找候选人并发送补位通知
        1. 查询同岗位可用员工（非排班中、非请假中）
        2. 按距离/意愿度/技能匹配度排序
        3. 发送企微补位请求通知
        4. 30分钟内无人接单则升级为Level 1通知店长
        """
        store_id = payload.get("store_id", "")
        schedule_date = payload.get("schedule_date", "")
        urgency = payload.get("urgency", "medium")

        tenant_id = payload.get("tenant_id", "")
        log.info(
            "gap_opened_received",
            store_id=store_id,
            date=schedule_date,
            urgency=urgency,
        )
        candidates: list[dict[str, Any]] = []
        try:
            async with async_session_factory() as db:
                result = await db.execute(
                    text("""
                        SELECT id, emp_name, role
                        FROM employees
                        WHERE store_id = :sid
                          AND status = 'active'
                          AND is_deleted = FALSE
                          AND id NOT IN (
                              SELECT employee_id
                              FROM employee_schedules
                              WHERE date = :sdate
                                AND is_deleted = FALSE
                          )
                        LIMIT 5
                    """),
                    {"sid": store_id, "sdate": schedule_date},
                )
                rows = result.mappings().all()
                candidates = [dict(r) for r in rows]
        except (OperationalError, SQLAlchemyError) as exc:
            log.warning(
                "gap_candidates_query_failed",
                store_id=store_id,
                schedule_date=schedule_date,
                error=str(exc),
            )

        log.info(
            "gap_fill_candidates_found",
            store_id=store_id,
            schedule_date=schedule_date,
            candidate_count=len(candidates),
            candidate_ids=[str(c.get("id", "")) for c in candidates],
        )
        # TODO: 接入 im_notification_service

    # ── 辅助方法 ─────────────────────────────────────────────────────

    @staticmethod
    def _decode_payload(event_data: dict[bytes, bytes]) -> dict[str, Any]:
        """将Redis Stream的bytes数据解码为dict"""
        result: dict[str, Any] = {}
        for k, v in event_data.items():
            key = k.decode() if isinstance(k, bytes) else str(k)
            val = v.decode() if isinstance(v, bytes) else str(v)
            if key == "payload":
                try:
                    result.update(json.loads(val))
                except (json.JSONDecodeError, TypeError):
                    result[key] = val
            else:
                result[key] = val
        return result

    async def stop(self) -> None:
        """停止消费循环"""
        self.running = False
        if self.redis:
            await self.redis.close()
            self.redis = None
        log.info("hr_event_consumer_stopped")
